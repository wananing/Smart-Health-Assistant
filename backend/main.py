from contextlib import asynccontextmanager
import asyncio
import inspect
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
import os
from typing import Any
from uuid import uuid4
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command
from agents.handoff import HANDOFF_TOOL_LABELS
from agents.llm import LLMConfigurationError, resolve_model_settings
from agents.router import is_exit_request
from agents.vision import (
    SCAN_TYPE_TO_AGENT,
    VisionInputError,
    compose_agent_message,
    normalize_scan_type,
    recognize_image,
    validate_image_upload,
)
from observability import configure_observability
from voice.gateway import GraphBridge, StarletteTransport, serve_voice_call
from voice.protocol import error_frame
from voice.providers import SpeechConfigurationError, load_speech_providers

load_dotenv()

_observability_runtime = configure_observability()
if _observability_runtime.provider != "none":
    print(
        f"--- [Observability] {_observability_runtime.provider} tracing enabled ---",
        flush=True,
    )


async def _close_checkpointer() -> None:
    """Release the checkpointer's backing connection (sqlite) on shutdown."""
    connection = getattr(getattr(_master_app, "checkpointer", None), "conn", None)
    close = getattr(connection, "close", None)
    if close is None:
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # pragma: no cover - shutdown best effort
        print(f"--- [API] Checkpointer close failed: {exc} ---", flush=True)


async def _warm_knowledge_base() -> None:
    """Load the RAG index at startup so the first clinic conclusion doesn't pay for it."""
    import time

    started = time.perf_counter()
    try:
        from rag.knowledge_base import get_knowledge_base

        await get_knowledge_base().warm()
    except Exception as exc:  # never block serving on RAG
        print(f"--- [RAG] Warm-up failed ({type(exc).__name__}); will retry lazily ---", flush=True)
        return
    print(f"--- [RAG] Knowledge base warmed in {time.perf_counter() - started:.1f}s ---", flush=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # In the background: serving starts immediately; a request that needs RAG
    # before warm-up finishes simply waits on the same init lock.
    warmup = asyncio.create_task(_warm_knowledge_base())
    yield
    warmup.cancel()
    await _close_checkpointer()
    _observability_runtime.shutdown()


app = FastAPI(title="大健康 AI 后端", version="0.5.0", lifespan=lifespan)

# Vite dev servers. Shared by CORS and the /api/voice WebSocket Origin check
# (CORS does not apply to WebSocket handshakes).
ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    # Comma-separated extras, e.g. a LAN address when testing on a phone.
    *(o.strip() for o in os.getenv("EXTRA_ALLOWED_ORIGINS", "").split(",") if o.strip()),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
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
    # clinic subgraph internals
    "emergency_gate": "正在进行急症安全筛查…",
    "extract_symptoms": "正在整理症状要点…",
    "check_sufficiency": "正在检查信息是否完整…",
    "ask_followup": "正在准备追问…",
    "conclude": "正在生成分诊建议…",
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
    # agent-to-agent handoffs
    **HANDOFF_TOOL_LABELS,
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
    # Server-side conversation id. When supplied, the checkpointer holds the
    # history and only the newest user message is sent to the graph.
    thread_id: str | None = None


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
    channel: str = "text",
) -> dict:
    user_info_dict = user_info.model_dump() if user_info else {}
    return {
        "messages": _build_lc_messages(messages)[-10:],
        "user_info": user_info_dict,
        "next_agent": "",
        "active_agent": active_agent,
        "handoff_count": 0,
        "channel": channel,
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


# Custom-stream payloads an agent may push straight through to the client via
# agents.streaming. They must reuse the SSE event types the frontend already
# understands — this whitelist is the only place event types are gated.
_STREAMABLE_CUSTOM_TYPES = {"card", "text"}


def _latest_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content
    return ""


def _split_stream_chunk(chunk: Any) -> tuple[str, Any] | None:
    """
    Decode a root-level `astream` chunk into (stream_mode, payload).

    With `subgraphs=True` the root chunk is `(namespace, mode, payload)`; node
    level `on_chain_stream` events carry plain dicts and are ignored here.
    """
    if not isinstance(chunk, tuple):
        return None
    if len(chunk) == 3:
        return chunk[1], chunk[2]
    if len(chunk) == 2 and isinstance(chunk[0], str):
        return chunk[0], chunk[1]
    return None


def _interrupt_question(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("question", "content", "text"):
            if isinstance(value.get(key), str):
                return value[key]
    return json.dumps(value, ensure_ascii=False, default=str)


async def _resolve_graph_input(
    config: dict,
    turn_state: dict,
    full_state: dict,
    user_text: str,
) -> Any:
    """
    Decide what to feed the graph for this request.

    - pending interrupt + exit phrase -> None, meaning "drop this thread"
    - pending interrupt on the thread -> resume it with the user's answer
    - known thread                    -> only the newest message
    - unknown thread                  -> the full history from the request
    """
    master_app = get_master_app()
    try:
        snapshot = await master_app.aget_state(config)
    except Exception as exc:  # pragma: no cover - checkpointer backend dependent
        print(f"--- [API] Unable to read thread state: {exc} ---", flush=True)
        return full_state

    pending = [
        interrupt
        for task in getattr(snapshot, "tasks", ())
        for interrupt in getattr(task, "interrupts", ())
    ]
    if pending:
        if is_exit_request(user_text):
            # Never swallow an exit phrase as an answer to a follow-up question.
            print("--- [API] Exit phrase during an interrupt, dropping thread ---", flush=True)
            return None
        print("--- [API] Resuming a pending interrupt ---", flush=True)
        return Command(resume=user_text)

    if getattr(snapshot, "values", None):
        return turn_state
    return full_state


def _interrupt_kind(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("kind"), str):
        return value["kind"]
    return None


async def _iter_agent_events(
    graph_input: Any,
    config: dict | None = None,
    *,
    custom_types: frozenset[str] | set[str] | None = None,
):
    """
    Translate one graph run into transport-neutral event dicts.

    Consumed by the SSE wrapper below and by the voice gateway. Every dict has
    the exact shape of the SSE event it becomes; the only extra is ``kind`` on
    ``interrupt`` events, which the SSE wrapper strips to keep ``/api/chat``
    byte-for-byte unchanged. ``custom_types`` widens the custom-stream
    whitelist for a caller that understands more (voice adds ``facts``).
    """
    allowed_custom = _STREAMABLE_CUSTOM_TYPES if custom_types is None else custom_types
    seen_interrupts: set[str] = set()
    try:
        print("--- [API] Starting event stream ---", flush=True)
        master_app = get_master_app()
        async for event in master_app.astream_events(
            graph_input,
            config=config,
            version="v2",
            stream_mode=["updates", "custom"],
            subgraphs=True,
        ):
            kind = event["event"]
            node_name = event.get("name", "")

            if kind not in (
                "on_chat_model_stream",
                "on_chat_model_start",
                "on_chat_model_end",
                "on_chain_stream",
            ):
                print(f"--- [Event] {kind} | Node: {node_name} ---", flush=True)

            # 1. LLM is streaming text tokens
            if kind == "on_chat_model_stream":
                chunk_content = event["data"]["chunk"].content
                if chunk_content:
                    yield {"type": "text", "content": chunk_content}

            # 1b. Root-level stream chunks: custom card/text events pushed by
            #     the agents themselves (agents/streaming.py), plus interrupts.
            elif kind == "on_chain_stream":
                decoded = _split_stream_chunk(event.get("data", {}).get("chunk"))
                if decoded is None:
                    continue
                stream_mode, stream_payload = decoded
                if stream_mode == "custom":
                    if (
                        isinstance(stream_payload, dict)
                        and stream_payload.get("type") in allowed_custom
                    ):
                        yield stream_payload
                elif stream_mode == "updates" and isinstance(stream_payload, dict):
                    for item in stream_payload.get("__interrupt__", ()) or ():
                        marker = str(getattr(item, "id", "") or id(item))
                        if marker in seen_interrupts:
                            continue
                        seen_interrupts.add(marker)
                        value = getattr(item, "value", item)
                        question = _interrupt_question(value)
                        yield {"type": "text", "content": question}
                        interrupt_event = {"type": "interrupt", "content": question}
                        interrupt_kind = _interrupt_kind(value)
                        if interrupt_kind:
                            interrupt_event["kind"] = interrupt_kind
                        yield interrupt_event

            # 2. A graph node is starting (shows agent status in UI)
            elif kind == "on_chain_start":
                label = _NODE_LABELS.get(node_name)
                if label:
                    yield {"type": "node_start", "node": node_name, "content": label}

            # 3. A graph node finished
            elif kind == "on_chain_end":
                if node_name in _NODE_LABELS:
                    yield {"type": "node_end", "node": node_name}

            # 4. Tool / skill calls
            elif kind == "on_tool_start":
                tool_name = event.get("name", "tool")
                label = _SKILL_LABELS.get(tool_name, f"正在调用：{tool_name}")
                yield {"type": "tool_start", "tool": tool_name, "content": label}

            elif kind == "on_tool_end":
                tool_name = event.get("name", "tool")
                yield {"type": "tool_end", "tool": tool_name}
                # `card` events are NOT derived here: every card-producing tool
                # (or its agent node) writes the payload itself through
                # agents.streaming, and it arrives on the `custom` stream above.

        print("--- [API] Event stream finished successfully ---", flush=True)
        yield {"type": "finish"}

    except Exception as e:
        print(f"--- [API] Event stream error: {e} ---", flush=True)
        yield {"type": "error", "content": str(e)}


async def _stream_agent_events(graph_input: Any, config: dict | None = None):
    """SSE wrapper around ``_iter_agent_events`` used by the HTTP endpoints."""
    async for event in _iter_agent_events(graph_input, config):
        if event.get("type") == "interrupt" and "kind" in event:
            event = {key: value for key, value in event.items() if key != "kind"}
        yield _sse_payload(event)


@app.get("/")
async def root():
    return {"message": "大健康 AI 后端 v0.5 (LangGraph)"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        resolve_model_settings()
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"大模型配置错误：{exc}") from exc

    active_agent = _MODE_TO_AGENT.get(request.chat_mode, "advisor_agent")
    thread_id = (request.thread_id or "").strip() or uuid4().hex
    config = {"configurable": {"thread_id": thread_id, "channel": "text"}}
    full_state = _build_initial_state(request.messages, request.user_info, active_agent)
    turn_state = _build_initial_state(request.messages[-1:], request.user_info, active_agent)
    user_text = _latest_user_text(request.messages)

    async def event_generator():
        active_thread_id = thread_id
        active_config = config
        graph_input = await _resolve_graph_input(config, turn_state, full_state, user_text)
        if graph_input is None:
            # The user left mid-interview: abandon the suspended thread so the
            # router gets to see the exit phrase on a clean conversation.
            active_thread_id = uuid4().hex
            active_config = {"configurable": {"thread_id": active_thread_id, "channel": "text"}}
            graph_input = full_state
        yield _sse_payload({"type": "session", "thread_id": active_thread_id})
        async for payload in _stream_agent_events(graph_input, active_config):
            yield payload

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/vision-chat")
async def vision_chat(
    file: UploadFile = File(...),
    scan_type: str = Form(...),
    user_info: str = Form("{}"),
    messages: str = Form("[]"),
    thread_id: str = Form(""),
):
    normalized_scan_type = normalize_scan_type(scan_type)
    parsed_user_info = _parse_user_info_json(user_info)
    parsed_messages = _parse_messages_json(messages)

    image_bytes = await file.read()
    try:
        validate_image_upload(file.content_type, len(image_bytes))
    except VisionInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved_thread_id = thread_id.strip() or uuid4().hex
    config = {"configurable": {"thread_id": resolved_thread_id, "channel": "text"}}

    async def event_generator():
        try:
            yield _sse_payload({"type": "session", "thread_id": resolved_thread_id})
            # An image upload is never an exit phrase, so the thread always holds.
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
            latest_message = ChatMessage(role="user", content=injected_message)
            vision_messages = [*parsed_messages[-9:], latest_message]
            active_agent = SCAN_TYPE_TO_AGENT[normalized_scan_type]
            full_state = _build_initial_state(vision_messages, parsed_user_info, active_agent)
            turn_state = _build_initial_state([latest_message], parsed_user_info, active_agent)
            graph_input = await _resolve_graph_input(
                config, turn_state, full_state, injected_message
            )
            async for payload in _stream_agent_events(graph_input or full_state, config):
                yield payload

        except VisionInputError as exc:
            yield _sse_payload({"type": "error", "content": str(exc)})
        except Exception as exc:
            print(f"--- [Vision] Event stream error: {exc} ---", flush=True)
            yield _sse_payload({"type": "error", "content": "图片识别失败，请稍后再试"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ─── /api/voice: real-time voice clinic ──────────────────────────────────────

_speech_providers = None


def _get_speech_providers():
    """Resolve ASR/TTS once (cue audio is cached per provider instance)."""
    global _speech_providers
    if _speech_providers is None:
        _speech_providers = load_speech_providers()
    return _speech_providers


def _build_voice_state(text: str, user_info: dict, channel: str) -> dict:
    try:
        parsed = UserInfo(**(user_info or {}))
    except Exception:
        parsed = UserInfo()
    return _build_initial_state(
        [ChatMessage(role="user", content=text)], parsed, "clinic_agent", channel=channel
    )


async def _get_thread_state(config: dict):
    return await get_master_app().aget_state(config, subgraphs=True)


async def _abandon_pending_run(config: dict) -> None:
    """
    Close out a run the voice gateway had to cancel (stall / hard cap).

    A cancelled run leaves its step pending in the checkpoint — typically the
    clinic subgraph still "waiting" on the interrupt it was resuming, with the
    old answer already bound to it. Resuming that would silently drop the
    user's next words, so the pending node is marked finished. What the
    subgraph had already produced this turn (its ``turn_messages``: follow-up
    questions, answers, the read-back) is written to the parent history with
    it, so the next message starts a normal turn over the full transcript and
    the interview continues where it stopped.
    """
    app = get_master_app()
    snapshot = await app.aget_state(config, subgraphs=True)
    for task in getattr(snapshot, "tasks", ()) or ():
        sub_values = getattr(getattr(task, "state", None), "values", None)
        kept = list(sub_values.get("turn_messages") or []) if isinstance(sub_values, dict) else []
        await app.aupdate_state(config, {"messages": kept}, as_node=task.name)


def _voice_bridge() -> GraphBridge:
    # Late-bound lambdas so tests can patch the module-level functions.
    return GraphBridge(
        resolve_input=lambda *args: _resolve_graph_input(*args),
        iter_events=lambda *args, **kwargs: _iter_agent_events(*args, **kwargs),
        build_state=lambda *args: _build_voice_state(*args),
        get_state=lambda config: _get_thread_state(config),
        check_config=lambda: resolve_model_settings(),
        abandon_run=lambda config: _abandon_pending_run(config),
    )


def _origin_allowed(origin: str | None) -> bool:
    return origin in ALLOWED_ORIGINS


@app.websocket("/api/voice")
async def voice(websocket: WebSocket):
    # CORS does not cover WebSocket handshakes: check Origin ourselves.
    # Closing before accept() makes the server reject the handshake (HTTP 403).
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin):
        print(f"--- [Voice] Rejected WebSocket origin: {origin!r} ---", flush=True)
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        asr, tts = _get_speech_providers()
    except SpeechConfigurationError as exc:
        await websocket.send_text(
            json.dumps(error_frame("fatal", f"语音服务配置错误：{exc}"), ensure_ascii=False)
        )
        await websocket.close(code=1011)
        return

    await serve_voice_call(
        StarletteTransport(websocket),
        bridge=_voice_bridge(),
        asr=asr,
        tts=tts,
    )
