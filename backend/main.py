from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import os
import json
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from agents.insurance import INSURANCE_CARD_TOOLS
from agents.pharmacy import PHARMACY_TOOL_TO_CARD_TYPE
from agents.vision import (
    SCAN_TYPE_TO_AGENT,
    VisionInputError,
    compose_agent_message,
    normalize_scan_type,
    recognize_image,
    validate_image_upload,
)

load_dotenv()

# ─── OBSERVABILITY: LangSmith Tracing (LangChain Architecture best practice) ──
# Enable by setting LANGCHAIN_API_KEY in .env
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_PROJECT=bigh-health-assistant
_langsmith_key = os.environ.get("LANGCHAIN_API_KEY", "")
if _langsmith_key:
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", os.environ.get("LANGCHAIN_PROJECT", "bigh-health-assistant"))
    print("--- [Observability] LangSmith tracing enabled ---", flush=True)

app = FastAPI(title="大健康 AI 后端", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],  # Vite dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy-load the graph to speed up startup
_master_app = None

def get_master_app():
    global _master_app
    if _master_app is None:
        from agents.graph import master_app
        _master_app = master_app
    return _master_app


# --- 工具名称映射 (Tool / Node display names) ---
_NODE_LABELS = {
    "router": "分析您的需求",
    "clinic_node": "进入预问诊模块",
    "insurance_node": "进入医保咨询模块",
    "report_node": "进入报告解读模块",
    "advisor_node": "进入健康顾问模块",
    "pharmacy_node": "进入用药咨询模块",
}

# --- 技能工具 → 前端展示标签 ---
_SKILL_LABELS: dict[str, str] = {
    # insurance tools
    "get_insurance_balance":    "正在查询医保余额…",
    "get_consumption_records":  "正在查询消费明细…",
    "get_payment_records":      "正在查询缴费记录…",
    "get_cross_region_info":    "正在查询异地就医信息…",
    "search_insurance_policy":  "正在检索医保政策知识库…",
    # pharmacy tools
    "search_drug_info":         "正在查询药品信息…",
    "check_drug_interaction":   "正在检查药物相互作用…",
    "find_nearby_pharmacy":     "正在查找附近药店…",
    "get_otc_recommendation":   "正在检索用药建议…",
    # skills
    "load_skill":               "正在加载技能模块…",
    "emergency_triage":         "正在进行急症安全评估…",
    "symptom_scorer":           "正在评估症状严重程度…",
    "health_calculator":        "正在计算健康指标…",
    "lab_interpreter":          "正在解读化验指标…",
    "risk_assessor":            "正在评估慢性病风险…",
    "medication_calculator":    "正在计算用药剂量…",
}

# --- 医保工具 → 前端卡片 payload type 映射 ---
_INSURANCE_TOOL_TO_CARD_TYPE = {
    "get_insurance_balance": "insurance_balance",
    "get_consumption_records": "insurance_expenses",
    "get_payment_records": "insurance_payments",
    "get_cross_region_info": "insurance_cross_region",
}

_REPORT_TOOL_TO_CARD_TYPE = {
    "lab_interpreter": "report_analysis",
}

_MODE_TO_AGENT = {
    "clinic": "clinic_agent",
    "insurance": "insurance_agent",
    "report": "report_agent",
    "pharmacy": "pharmacy_agent",
    "general": "advisor_agent",
    "dashboard": "advisor_agent",
}


class ChatMessage(BaseModel):
    role: str
    content: str


class UserInfo(BaseModel):
    name: str = "用户"
    age: int | None = None
    medical_history: str = "无"
    elder_mode: bool = False
    region: str = ""


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    user_info: UserInfo | None = None
    chat_mode: str = "general"


def _sse_payload(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_lc_messages(messages: list[ChatMessage]) -> list[HumanMessage | AIMessage]:
    return [
        HumanMessage(content=msg.content)
        if msg.role == "user"
        else AIMessage(content=msg.content)
        for msg in messages
        if msg.role in ("user", "assistant") and msg.content.strip()
    ]


def _build_initial_state(
    messages: list[ChatMessage],
    user_info: UserInfo | None,
    active_agent: str,
) -> dict:
    user_info_dict = user_info.model_dump() if user_info else {}
    return {
        "messages": _build_lc_messages(messages)[-10:],
        "user_info": user_info_dict,
        "next_agent": "",
        "active_agent": active_agent,
    }


def _parse_user_info_json(raw: str) -> UserInfo:
    try:
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            raise ValueError("user_info must be an object")
        return UserInfo(**data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"user_info 格式错误: {exc}") from exc


def _parse_messages_json(raw: str) -> list[ChatMessage]:
    try:
        data = json.loads(raw) if raw else []
        if not isinstance(data, list):
            raise ValueError("messages must be a list")
        return [ChatMessage(**item) for item in data if isinstance(item, dict)]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"messages 格式错误: {exc}") from exc


async def _stream_agent_events(initial_state: dict, user_info_dict: dict):
    try:
        print(f"--- [API] Starting event stream for user_info: {user_info_dict} ---", flush=True)
        master_app = get_master_app()
        async for event in master_app.astream_events(initial_state, version="v2"):
            kind = event["event"]
            node_name = event.get("name", "")

            if kind not in ("on_chat_model_stream", "on_chat_model_start", "on_chat_model_end"):
                print(f"--- [Event] {kind} | Node: {node_name} ---", flush=True)

            # 1. LLM is streaming text tokens
            if kind == "on_chat_model_stream":
                chunk_content = event["data"]["chunk"].content
                if chunk_content:
                    yield _sse_payload({"type": "text", "content": chunk_content})

            # 2. A graph node is starting (shows agent status in UI)
            elif kind == "on_chain_start":
                label = _NODE_LABELS.get(node_name)
                if label:
                    yield _sse_payload({"type": "node_start", "node": node_name, "content": label})

            # 3. A graph node finished
            elif kind == "on_chain_end":
                if node_name in _NODE_LABELS:
                    yield _sse_payload({"type": "node_end", "node": node_name})

            # 4. Tool / skill calls
            elif kind == "on_tool_start":
                tool_name = event.get("name", "tool")
                label = _SKILL_LABELS.get(tool_name, f"正在调用：{tool_name}")
                yield _sse_payload({"type": "tool_start", "tool": tool_name, "content": label})

            elif kind == "on_tool_end":
                tool_name = event.get("name", "tool")
                yield _sse_payload({"type": "tool_end", "tool": tool_name})

                # Emit a structured card event for tools that have card mappings
                card_type = (
                    _INSURANCE_TOOL_TO_CARD_TYPE.get(tool_name)
                    or PHARMACY_TOOL_TO_CARD_TYPE.get(tool_name)
                    or _REPORT_TOOL_TO_CARD_TYPE.get(tool_name)
                )
                if card_type:
                    try:
                        raw_output = event.get("data", {}).get("output", "{}")
                        # output may be a ToolMessage or raw string
                        if hasattr(raw_output, "content"):
                            raw_output = raw_output.content
                        tool_data = json.loads(raw_output)
                        yield _sse_payload({"type": "card", "payload": {"type": card_type, "data": tool_data}})
                    except Exception as parse_err:
                        print(f"--- [Card] Failed to parse tool output for {tool_name}: {parse_err} ---", flush=True)

        print("--- [API] Event stream finished successfully ---", flush=True)
        yield 'data: {"type": "finish"}\n\n'

    except Exception as e:
        print(f"--- [API] Event stream error: {e} ---", flush=True)
        yield _sse_payload({"type": "error", "content": str(e)})


@app.get("/")
async def root():
    return {"message": "大健康 AI 后端 v2.0 (LangGraph)"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    ark_api_key = os.environ.get("ARK_API_KEY", "")
    if not ark_api_key:
        raise HTTPException(status_code=500, detail="ARK_API_KEY 未配置")

    active_agent = _MODE_TO_AGENT.get(request.chat_mode, "advisor_agent")
    initial_state = _build_initial_state(request.messages, request.user_info, active_agent)
    user_info_dict = initial_state["user_info"]

    return StreamingResponse(
        _stream_agent_events(initial_state, user_info_dict),
        media_type="text/event-stream",
    )


@app.post("/api/vision-chat")
async def vision_chat(
    file: UploadFile = File(...),
    scan_type: str = Form(...),
    user_info: str = Form("{}"),
    messages: str = Form("[]"),
):
    normalized_scan_type = normalize_scan_type(scan_type)
    parsed_user_info = _parse_user_info_json(user_info)
    parsed_messages = _parse_messages_json(messages)

    image_bytes = await file.read()
    try:
        validate_image_upload(file.content_type, len(image_bytes))
    except VisionInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_generator():
        try:
            yield _sse_payload({
                "type": "tool_start",
                "tool": "vision_model",
                "content": "正在识别图片内容…",
            })
            vision_text = await recognize_image(
                image_bytes,
                file.content_type or "",
                normalized_scan_type,
            )
            yield _sse_payload({"type": "tool_end", "tool": "vision_model"})

            injected_message = compose_agent_message(normalized_scan_type, vision_text)
            vision_messages = [
                *parsed_messages[-9:],
                ChatMessage(role="user", content=injected_message),
            ]
            active_agent = SCAN_TYPE_TO_AGENT[normalized_scan_type]
            initial_state = _build_initial_state(vision_messages, parsed_user_info, active_agent)
            async for payload in _stream_agent_events(initial_state, initial_state["user_info"]):
                yield payload

        except VisionInputError as exc:
            yield _sse_payload({"type": "error", "content": str(exc)})
        except Exception as exc:
            print(f"--- [Vision] Event stream error: {exc} ---", flush=True)
            yield _sse_payload({"type": "error", "content": "图片识别失败，请稍后再试"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
