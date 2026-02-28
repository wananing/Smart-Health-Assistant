from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import os
import json
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from agents.insurance import INSURANCE_CARD_TOOLS

load_dotenv()

app = FastAPI(title="大健康 AI 后端", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
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
}

# --- 医保工具 → 前端卡片 payload type 映射 ---
_INSURANCE_TOOL_TO_CARD_TYPE = {
    "get_insurance_balance": "insurance_balance",
    "get_consumption_records": "insurance_expenses",
    "get_payment_records": "insurance_payments",
    "get_cross_region_info": "insurance_cross_region",
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

    # Build initial LangGraph state - preserve both user and assistant messages
    lc_messages = [
        HumanMessage(content=msg.content)
        if msg.role == "user"
        else AIMessage(content=msg.content)
        for msg in request.messages
        if msg.role in ("user", "assistant") and msg.content.strip()
    ]

    # Use only the last few messages to avoid token overflow (sliding window)
    lc_messages = lc_messages[-10:]

    user_info_dict = {}
    if request.user_info:
        user_info_dict = request.user_info.model_dump()
        
    # Map frontend ChatMode to backend agent keys (must match _AGENT_MAP in graph.py).
    _MODE_TO_AGENT = {
        "clinic": "clinic_agent",
        "insurance": "insurance_agent",
        "report": "report_agent",
        "general": "advisor_agent",
        "dashboard": "advisor_agent"
    }

    initial_state = {
        "messages": lc_messages,
        "user_info": user_info_dict,
        "next_agent": "",
        "active_agent": _MODE_TO_AGENT.get(request.chat_mode, "advisor_node"),
    }

    async def event_generator():
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
                        payload = json.dumps(
                            {"type": "text", "content": chunk_content},
                            ensure_ascii=False
                        )
                        yield f"data: {payload}\n\n"

                # 2. A graph node is starting (shows agent status in UI)
                elif kind == "on_chain_start":
                    label = _NODE_LABELS.get(node_name)
                    if label:
                        payload = json.dumps(
                            {"type": "node_start", "node": node_name, "content": label},
                            ensure_ascii=False
                        )
                        yield f"data: {payload}\n\n"

                # 3. A graph node finished
                elif kind == "on_chain_end":
                    if node_name in _NODE_LABELS:
                        payload = json.dumps(
                            {"type": "node_end", "node": node_name},
                            ensure_ascii=False
                        )
                        yield f"data: {payload}\n\n"

                # 4. Tool calls (for future tool integration)
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "tool")
                    payload = json.dumps(
                        {"type": "tool_start", "tool": tool_name, "content": f"正在调用：{tool_name}"},
                        ensure_ascii=False
                    )
                    yield f"data: {payload}\n\n"

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "tool")
                    payload = json.dumps(
                        {"type": "tool_end", "tool": tool_name},
                        ensure_ascii=False
                    )
                    yield f"data: {payload}\n\n"

                    # For insurance tools, extract the JSON result and emit a card event
                    card_type = _INSURANCE_TOOL_TO_CARD_TYPE.get(tool_name)
                    if card_type:
                        try:
                            raw_output = event.get("data", {}).get("output", "{}")
                            # output may be a ToolMessage or raw string
                            if hasattr(raw_output, "content"):
                                raw_output = raw_output.content
                            tool_data = json.loads(raw_output)
                            card_payload = json.dumps(
                                {"type": "card", "payload": {"type": card_type, "data": tool_data}},
                                ensure_ascii=False
                            )
                            yield f"data: {card_payload}\n\n"
                        except Exception as parse_err:
                            print(f"--- [Card] Failed to parse tool output for {tool_name}: {parse_err} ---", flush=True)

            print("--- [API] Event stream finished successfully ---", flush=True)
            yield 'data: {"type": "finish"}\n\n'

        except Exception as e:
            print(f"--- [API] Event stream error: {e} ---", flush=True)
            payload = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
