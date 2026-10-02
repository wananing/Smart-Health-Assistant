"""
Clinic Agent — a compiled LangGraph subgraph mounted as ``clinic_node``.

The clinic line is the only agent with a real multi-step state machine. It owns
its private ``ClinicState`` and is mounted as a subgraph inside the master graph
in ``agents/graph.py``:

    ┌──► emergency_gate ──CRITICAL─────────────────────────────────────► END
    │          │                                                          ▲
    │          │ safe enough to interview                                 │
    │          ▼                                                          │
    │    extract_symptoms ──► check_sufficiency ──enough──► conclude ─────┘
    │                               │      │                  ▲
    │                               │      │ voice only       │ affirmed /
    │         missing required facts│      └─► confirm_facts ─┘ cap reached
    │                               ▼              │
    ├──── await_answer ◄──── ask_followup          │ correction
    └──────────────────────────────────────────────┘

Node responsibilities:
  emergency_gate    Pure rule matching (no LLM). Calls ``EmergencyTriageSkill``
                    directly so the red-flag gate can never be skipped by an
                    LLM that decides not to call the tool. CRITICAL short-
                    circuits the whole subgraph with the verbatim safety text.
                    It runs on entry AND on every resumed answer, so a red
                    flag mentioned while answering a follow-up is caught too.
  extract_symptoms  ONE structured LLM call (``InterviewStep``): the symptom
                    facts, merged into ``ClinicState['collected']``, and a
                    drafted next question (empty when nothing is missing).
  check_sufficiency Deterministic check for the required fields.
  ask_followup      No LLM: asks the drafted question (or a template when the
                    draft is empty / too long) — exactly one question.
  await_answer      ``interrupt({"kind": "followup", ...})`` — suspends the
                    whole graph until the next request on the same
                    ``thread_id`` resumes it with the user's answer, which
                    loops back through the emergency gate.
  confirm_facts     Voice channel only. Reads the collected facts back from a
                    template (no LLM) with ``interrupt({"kind": "confirm",
                    ...})``; an anchored affirmative goes on to conclude, any
                    other answer is a correction and is re-extracted. At most
                    ``MAX_CONFIRMATIONS`` read-backs per turn.
  conclude          ReAct agent (clinic skills + RAG) writes the triage text,
                    then a structured recommendation is streamed to the client
                    as a ``clinic_recommendation`` card.

Contract with the parent graph: the subgraph returns ``{"messages": [...]}``
containing ONLY the messages produced during this turn (see ``_replace``).
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

# Node signatures spell the config parameter ``Optional[RunnableConfig]``: with
# postponed annotations LangGraph matches the annotation *string* and only
# injects the config for "RunnableConfig" / "Optional[RunnableConfig]".
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from agents.handoff import apply_handoff, get_handoff_tools, handoff_prompt_section
from agents.llm import get_chat_llm
from agents.streaming import emit_custom
from rag.knowledge_base import get_knowledge_base
from skills import get_agent_tools, load_skill
from skills.emergency_triage.skill import EmergencyTriageSkill

AGENT_ID = "clinic_agent"

CLINIC_SYSTEM_PROMPT = """你是大健康App中的"AI预问诊助手"，态度温和、专业。

你的任务是通过友好的对话帮助用户描述清楚症状，然后给出合理的分诊建议。

【对话要求】
1. **禁止下绝对诊断**：不允许说"您得了XX病"，只能说"从症状来看，可能需要就诊XX科"。
2. **安全第一**：如果用户提到剧烈胸痛、呼吸困难、突发意识丧失等急症，必须立刻提示"请立即拨打 120！"
3. **信息已收集完毕**：症状要点已由系统结构化整理，请直接据此给出结论，不要再反复追问。
4. **输出分诊建议**：以清晰的格式给出建议，包括：可能的科室、就诊优先级（紧急/较快/可择期）、初步注意事项。
5. **语气**：温和、关怀、专业，像一个有经验的家庭医生。

【可用技能（Skills）调用规则】
- **symptom_scorer**：根据已收集的症状信息调用，获取严重程度分数（0-100）和分诊颜色，用于辅助分诊建议。
- **health_calculator**：用户询问BMI、体重、热量时调用，需提供身高、体重、年龄、性别。
- **risk_assessor**：用户有多项慢性病风险因素时调用，评估心血管和糖尿病10年风险。
- **medication_calculator**：用户询问按体重/年龄计算药物剂量时调用。
- **lab_interpreter**：用户同时提供化验数值时调用，对指标进行结构化判读。

急症安全评估已由系统在进入本节点前完成，无需再调用 emergency_triage。
请直接开始回答，不要重复系统提示内容。"""

# One structured call does both halves of an interview step (it used to be
# two serial LLM calls, extract then ask): the facts, and the next question.
INTERVIEW_SYSTEM_PROMPT = """你是预问诊助手的"信息整理 + 追问"环节。请阅读预问诊对话，一次完成两件事。

一、抽取结构化症状要点（facts）：
- 只抽取用户明确说过的内容，没有提到的字段一律留空字符串或空数组，禁止推测或编造。
- duration 用原话表达（如"三天"、"两周"、"今天早上开始"）。
- severity 归一化为"轻微"/"中等"/"严重"之一。
- 用户后来更正的内容以更正为准（例如先说"三天"、后来说"其实是五天"，duration 取"五天"）。
- 不要输出诊断结论。

二、写下一个追问（next_question）：
- 必须收集的信息是：主要不适（主诉）、持续时间、严重程度。三项都已明确时，next_question 留空字符串。
- 否则像一位温和的预问诊护士，针对缺失的信息只问**一个**问题，不超过 40 个字，不要编号，不要罗列多个问题。
- 语气关怀、口语化，可以先用半句话共情再提问。
- 不要给出诊断、用药或就诊建议。
- 不要重复已经问过的问题。"""

RECOMMENDATION_SYSTEM_PROMPT = """请把下面这段预问诊结论压缩成结构化分诊建议。

规则：
- department 给出 1-3 个最贴切的科室名称（如"呼吸内科"）。
- urgency 只能是 emergency（需立即急诊）/ soon（建议尽快就诊）/ routine（可择期就诊）之一。
- summary 用一句话概括建议，不超过 60 个字。
- notes 给出 1-4 条就诊前注意事项。
- 只依据给定文本，不要新增结论。"""

# Voice channel only: the first line of the conclusion is what the call says
# out loud while the body is still streaming to the screen.
VOICE_LEAD_INSTRUCTION = """

【语音通道】用户正在语音通话中。回答的第一行必须是一句给用户听的口语结论：
- 不超过 40 个字，包含建议就诊的科室和紧急程度（例如"建议您今天去神经内科看看。"）；
- 不下诊断，不用 Markdown，不用编号，以句号结尾；
然后换行，再写完整的分诊建议正文。"""

MAX_SPOKEN_LEAD_CHARS = 60
_LEAD_END = "。！？!?\n"

# Fields the interview must collect before the agent is allowed to conclude.
REQUIRED_FIELDS: tuple[str, ...] = ("chief_complaint", "duration", "severity")

# Safety valve: never interrogate the user more than this many times per turn.
MAX_FOLLOWUPS = 3

# A drafted question longer than this is not "one short question": use the template.
MAX_QUESTION_CHARS = 60

# Voice channel: read the facts back at most this many times, then conclude.
MAX_CONFIRMATIONS = 2

# Answers that confirm a read-back. The whole reply must consist of these
# tokens (split on punctuation), so 对，但是是五天 is a correction, not a yes.
AFFIRMATIVE_PHRASES = frozenset(
    {
        "对", "对的", "对对", "对对对", "对啊", "对呀", "是", "是的", "是啊",
        "是呀", "是这样", "没错", "没错没错", "嗯", "嗯嗯", "嗯对", "好", "好的",
        "可以", "行", "没问题", "正确", "继续",
    }
)
_ANSWER_BOUNDARY = " \t　，,。.！!？?；;、~～…·"

_FIELD_LABELS = {
    "chief_complaint": "主要不适（主诉）",
    "location": "不适的具体部位",
    "duration": "症状持续了多久",
    "severity": "严重程度（轻微/中等/严重）",
    "associated_symptoms": "是否伴随其他症状",
    "onset": "症状是怎么开始的",
    "triggers": "有没有诱因或加重/缓解因素",
}

_URGENCY_TO_SEVERITY = {
    "emergency": "high",
    "soon": "medium",
    "routine": "low",
}


# ─── Structured schemas ───────────────────────────────────────────────────────

class SymptomFacts(BaseModel):
    """Structured symptom profile extracted from the interview transcript."""

    chief_complaint: str = Field(default="", description="主诉，用户最主要的不适")
    location: str = Field(default="", description="不适部位")
    duration: str = Field(default="", description="症状持续时间，保留用户原话")
    severity: str = Field(default="", description="严重程度：轻微 / 中等 / 严重")
    associated_symptoms: list[str] = Field(default_factory=list, description="伴随症状列表")
    onset: str = Field(default="", description="起病方式，如突发 / 逐渐加重")
    triggers: str = Field(default="", description="诱因或加重、缓解因素")


class InterviewStep(BaseModel):
    """One interview step: the facts so far and the next question (if any)."""

    facts: SymptomFacts = Field(default_factory=SymptomFacts, description="结构化症状要点")
    next_question: str = Field(
        default="",
        description="下一个追问（一个问题，不超过40字）；主诉、持续时间、严重程度都已明确时留空",
    )


class TriageRecommendation(BaseModel):
    """Structured triage result rendered by the frontend clinic card."""

    department: list[str] = Field(default_factory=list, description="推荐就诊科室")
    urgency: Literal["emergency", "soon", "routine"] = Field(
        default="routine", description="就诊优先级"
    )
    summary: str = Field(default="", description="一句话分诊建议")
    notes: list[str] = Field(default_factory=list, description="就诊前注意事项")


# ─── Subgraph state ───────────────────────────────────────────────────────────

def _replace(_current: Any, incoming: Any) -> Any:
    """Last-write-wins reducer."""
    return incoming


def _merge_facts(current: dict | None, incoming: dict | None) -> dict:
    """Merge newly extracted facts, never overwriting a known value with a blank."""
    merged = dict(current or {})
    for key, value in (incoming or {}).items():
        if value in ("", [], None):
            continue
        merged[key] = value
    return merged


class ClinicState(TypedDict, total=False):
    """
    Private state of the clinic subgraph.

    ``messages`` is deliberately a last-write-wins channel: on entry it holds
    the conversation history handed down by the master graph, and terminal
    nodes overwrite it with ONLY the messages produced during this turn. The
    parent's ``operator.add`` reducer then appends exactly those, which keeps
    the ``{"messages": new_messages}`` contract the rest of the app expects.
    """

    messages: Annotated[Sequence[BaseMessage], _replace]
    user_info: dict
    # Mirrored from MainAgentState so conclude() can respect the per-turn
    # handoff budget before escaping to the parent graph.
    handoff_count: int
    # Messages produced inside this turn (follow-up Q&A + final triage answer).
    turn_messages: Annotated[list[BaseMessage], operator.add]
    # Symptom facts merged across extraction rounds.
    collected: Annotated[dict, _merge_facts]
    emergency_level: str
    missing_fields: list[str]
    is_sufficient: bool
    followup_count: int
    pending_question: str
    # Question drafted by extract_symptoms in the same call as the facts;
    # used by ask_followup only if check_sufficiency finds something missing.
    draft_question: str
    recommendation: dict
    # "text" (default) or "voice"; mirrored from MainAgentState.
    channel: str
    # Voice read-back bookkeeping (confirm_facts).
    confirm_count: int
    facts_confirmed: bool


# ─── Helpers ──────────────────────────────────────────────────────────────────

# Alias kept for readability inside this module; the implementation is shared
# with the other agents in agents/streaming.py.
_emit = emit_custom


def _transcript(state: ClinicState) -> list[BaseMessage]:
    """Inbound history plus everything produced during this turn, in order."""
    return [*state.get("messages", []), *state.get("turn_messages", [])]


def _message_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return str(content)


def _latest_user_text(state: ClinicState) -> str:
    for message in reversed(_transcript(state)):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def _format_transcript(state: ClinicState) -> str:
    lines = []
    for message in _transcript(state):
        if isinstance(message, HumanMessage):
            lines.append(f"用户：{_message_text(message)}")
        elif isinstance(message, AIMessage):
            text = _message_text(message)
            if text:
                lines.append(f"助手：{text}")
    return "\n".join(lines)


def _user_age(state: ClinicState) -> int | None:
    age = state.get("user_info", {}).get("age")
    return age if isinstance(age, int) else None


def _format_collected(collected: dict) -> str:
    lines = []
    for key, label in _FIELD_LABELS.items():
        value = collected.get(key)
        if not value:
            continue
        rendered = "、".join(value) if isinstance(value, list) else str(value)
        lines.append(f"- {label}：{rendered}")
    return "\n".join(lines) or "- （暂无结构化要点）"


def _missing_fields(collected: dict) -> list[str]:
    return [field for field in REQUIRED_FIELDS if not collected.get(field)]


def _channel(state: ClinicState, config: RunnableConfig | None = None) -> str:
    """
    The channel of *this request*. Callers put it in the run config
    (``configurable.channel``) on every run, including ``Command(resume=…)``,
    so a voice call that hung up on a read-back and is answered from the text
    chat continues as text. The state's ``channel`` (checkpointed at the
    start of the interview) is only a fallback for callers that don't set it.
    """
    configured = ((config or {}).get("configurable") or {}).get("channel")
    return str(configured or state.get("channel") or "text")


def _is_voice(state: ClinicState, config: RunnableConfig | None = None) -> bool:
    return _channel(state, config) == "voice"


def is_affirmative_answer(text: str) -> bool:
    """
    True when a read-back answer is a plain "yes".

    Anchored like ``router.is_exit_request`` but stricter: every
    punctuation-separated piece must be an affirmative token, so ``对，继续``
    confirms while ``对，但是是五天`` is treated as a correction.
    """
    pieces = [
        piece
        for piece in "".join(
            " " if char in _ANSWER_BOUNDARY else char for char in text.strip()
        ).split()
        if piece
    ]
    return bool(pieces) and all(piece in AFFIRMATIVE_PHRASES for piece in pieces)


_SEVERITY_READBACK = {"轻微": "比较轻", "中等": "中等程度", "严重": "比较严重"}


def build_readback(collected: dict) -> str:
    """Template read-back of the collected facts — never an LLM, never a diagnosis."""
    parts: list[str] = []
    if collected.get("chief_complaint"):
        parts.append(str(collected["chief_complaint"]))
    if collected.get("location"):
        parts.append(f"部位在{collected['location']}")
    if collected.get("duration"):
        duration = str(collected["duration"])
        parts.append(duration if duration.startswith(("持续", "从", "今天", "昨天")) else f"持续{duration}")
    if collected.get("severity"):
        severity = str(collected["severity"])
        parts.append(_SEVERITY_READBACK.get(severity, severity))
    associated = collected.get("associated_symptoms") or []
    if isinstance(associated, list) and associated:
        parts.append("还伴有" + "、".join(str(item) for item in associated[:3]))
    if not parts:
        return "我确认一下：您还没有说具体哪里不舒服，对吗？"
    return f"我确认一下：{'，'.join(parts)}，对吗？"


def extract_spoken_lead(text: str) -> str:
    """
    The one-sentence spoken conclusion at the start of a voice-channel answer,
    or "" when the answer does not start with one (heading, too long, no end).
    Shared with the voice gateway, which cuts the same sentence off the stream.
    """
    stripped = text.lstrip()
    if not stripped or stripped.startswith(("#", "-", "*", "|", ">")):
        return ""
    for index, char in enumerate(stripped[: MAX_SPOKEN_LEAD_CHARS + 1]):
        if char in _LEAD_END:
            return stripped[: index + (char != "\n")].strip()
    return ""


def _clinic_card(recommendation: dict) -> dict:
    """Build the ``clinic_recommendation`` card payload the frontend renders."""
    urgency = recommendation.get("urgency", "routine")
    return {
        "type": "card",
        "payload": {
            "type": "clinic_recommendation",
            "data": {
                "summary": recommendation.get("summary", ""),
                "departments": recommendation.get("department", []),
                "severity": _URGENCY_TO_SEVERITY.get(urgency, "low"),
                "urgency": urgency,
                "notes": recommendation.get("notes", []),
            },
        },
    }


# ─── Nodes ────────────────────────────────────────────────────────────────────

async def emergency_gate(state: ClinicState) -> dict:
    """
    Code-level red-flag gate. Runs the ``emergency_triage`` skill directly —
    never through the LLM — so a CRITICAL presentation always short-circuits.
    """
    result = EmergencyTriageSkill().run(
        symptoms_text=_latest_user_text(state),
        age=_user_age(state),
    )
    if result.level != "CRITICAL":
        return {"emergency_level": result.level}

    flags = "、".join(result.triggered_flags)
    safety_text = result.safety_message
    if flags:
        safety_text += f"\n\n识别到的危险信号：{flags}。"
    safety_text += f"\n\n{result.disclaimer}"

    recommendation = {
        "department": ["急诊科"],
        "urgency": "emergency",
        "summary": f"检测到危急征象（{flags or '危急症状'}），请立即拨打120或前往最近急诊。",
        "notes": ["不要自行驾车前往医院", "保持电话畅通并有人陪同", "记录症状开始时间供医生参考"],
    }

    _emit({"type": "text", "content": safety_text})
    _emit(_clinic_card(recommendation))

    answer = AIMessage(content=safety_text)
    return {
        "emergency_level": result.level,
        "turn_messages": [answer],
        # On a resumed answer the follow-up Q&A of this turn must reach the
        # parent history too; on entry turn_messages is still empty.
        "messages": [*state.get("turn_messages", []), answer],
        "recommendation": recommendation,
    }


def route_after_gate(state: ClinicState) -> str:
    """CRITICAL ends the subgraph immediately; anything else (re)enters the interview."""
    return END if state.get("emergency_level") == "CRITICAL" else "extract_symptoms"


async def extract_symptoms(state: ClinicState) -> dict:
    """
    One structured LLM call: merge the transcript's symptom facts and draft
    the next follow-up question. Whether the question is used is still decided
    deterministically by ``check_sufficiency``.
    """
    transcript = _format_transcript(state)
    if not transcript:
        return {}

    llm = get_chat_llm("precise", streaming=False)
    try:
        step = await llm.with_structured_output(InterviewStep).ainvoke(
            [
                SystemMessage(content=INTERVIEW_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"已收集到的信息：\n{_format_collected(state.get('collected', {}))}\n\n"
                        f"预问诊对话：\n{transcript}"
                    )
                ),
            ]
        )
    except Exception as exc:  # pragma: no cover - provider/network dependent
        print(f"--- [Clinic] interview step failed: {type(exc).__name__} ---", flush=True)
        return {"draft_question": ""}

    if isinstance(step, dict):
        step = InterviewStep.model_validate(step)
    if not isinstance(step, InterviewStep):
        return {"draft_question": ""}
    return {
        "collected": step.facts.model_dump(),
        "draft_question": step.next_question.strip(),
    }


async def check_sufficiency(state: ClinicState, config: Optional[RunnableConfig] = None) -> dict:
    """Deterministic gate: are all required fields present (or out of retries)?"""
    collected = state.get("collected", {})
    missing = _missing_fields(collected)
    exhausted = state.get("followup_count", 0) >= MAX_FOLLOWUPS
    channel = _channel(state, config)
    if channel == "voice":
        # Drives the voice call's symptom panel; the text channel never sees it
        # (main._STREAMABLE_CUSTOM_TYPES does not forward "facts" over SSE).
        _emit({"type": "facts", "collected": dict(collected), "missing": missing})
    return {
        # Routing below reads the request's channel, not the checkpointed one.
        "channel": channel,
        "missing_fields": missing,
        "is_sufficient": not missing or exhausted,
    }


def route_after_sufficiency(state: ClinicState) -> str:
    """
    Route to ``conclude`` when the interview has what it needs.

    On the voice channel the facts are read back first (``confirm_facts``)
    unless the user already confirmed or the read-back budget is spent.
    """
    if not state.get("is_sufficient"):
        return "ask_followup"
    if (
        _is_voice(state)
        and state.get("collected")
        and not state.get("facts_confirmed")
        and state.get("confirm_count", 0) < MAX_CONFIRMATIONS
    ):
        return "confirm_facts"
    return "conclude"


async def ask_followup(state: ClinicState) -> dict:
    """
    Ask exactly one gentle follow-up question about the missing facts.

    No LLM call of its own: the question was drafted together with the facts
    in ``extract_symptoms``. If that draft is empty or not a short single
    question, a template asks for the missing fields instead.
    """
    missing = state.get("missing_fields") or list(REQUIRED_FIELDS)
    wanted = "、".join(_FIELD_LABELS.get(field, field) for field in missing)
    question = (state.get("draft_question") or "").strip()
    if not question or len(question) > MAX_QUESTION_CHARS:
        question = f"方便再多说一点吗？想了解一下您的{wanted}。"

    return {
        "pending_question": question,
        "draft_question": "",
        "turn_messages": [AIMessage(content=question)],
    }


async def await_answer(state: ClinicState) -> dict:
    """
    Suspend the whole graph until the user answers.

    ``interrupt()`` persists the pending question in the checkpoint; the next
    request on the same ``thread_id`` resumes with ``Command(resume=<answer>)``
    and the answer re-enters the interview through ``emergency_gate``, so a
    red flag in the answer is caught before anything else runs.
    The interrupt value is ``{"kind": "followup", "question": …}``;
    ``main._interrupt_question`` turns it back into the plain SSE text.
    """
    question = state.get("pending_question", "")
    answer = interrupt({"kind": "followup", "question": question})
    return {
        "turn_messages": [HumanMessage(content=str(answer))],
        "followup_count": state.get("followup_count", 0) + 1,
        "pending_question": "",
    }


async def confirm_facts(state: ClinicState) -> dict:
    """
    Voice only: read the collected facts back and wait for a yes or a fix.

    The read-back is a template (``build_readback``), not an LLM call, so what
    the user hears is exactly what is on the symptom panel. Re-running this
    node on resume recomputes the same sentence from the same state.
    """
    collected = dict(state.get("collected", {}))
    question = build_readback(collected)
    answer = str(interrupt({"kind": "confirm", "question": question, "facts": collected}))
    return {
        "turn_messages": [AIMessage(content=question), HumanMessage(content=answer)],
        "confirm_count": state.get("confirm_count", 0) + 1,
        "facts_confirmed": is_affirmative_answer(answer),
    }


def route_after_confirm(state: ClinicState) -> str:
    """A plain yes concludes; anything else is a correction re-read through the gate."""
    return "conclude" if state.get("facts_confirmed") else "emergency_gate"


async def _build_system_prompt(state: ClinicState) -> str:
    user_info = state.get("user_info", {})
    name = user_info.get("name", "您")
    age = user_info.get("age", "")
    history = user_info.get("medical_history", "无")
    lang_note = "请使用极度通俗易懂的语言。" if user_info.get("elder_mode") else ""

    system = f"""{CLINIC_SYSTEM_PROMPT}

【当前用户】姓名：{name}  年龄：{age}  既往病史：{history}
{lang_note}

【系统已结构化的症状要点】
{_format_collected(state.get("collected", {}))}
【系统急症安全评估】{state.get("emergency_level", "NON_URGENT")}"""

    query = _latest_user_text(state) or state.get("collected", {}).get("chief_complaint", "")
    if query:
        kb = get_knowledge_base()
        docs = await kb.amulti_query_retrieve(
            [query, f"{query} 疾病 症状 诊断", f"{query} 就诊科室 治疗"],
            k=4,
        )
        rag_context = kb.format_context(docs)
        if rag_context:
            system += (
                "\n\n## 参考临床知识\n"
                "以下为相关疾病知识，用于辅助分诊判断（不要直接引用，结合症状灵活使用）：\n\n"
                f"{rag_context}"
            )
    return system


async def _summarize_recommendation(triage_text: str, state: ClinicState, *, voice: bool = False) -> dict:
    """Derive the structured triage card from the ReAct agent's answer."""
    # Voice: the first line was already spoken; the card must say the same.
    lead = extract_spoken_lead(triage_text) if voice else ""
    lead_hint = f"\n\n正文第一句已经念给用户听：「{lead}」。summary 请直接使用这句话。" if lead else ""
    llm = get_chat_llm("precise", streaming=False)
    try:
        result = await llm.with_structured_output(TriageRecommendation).ainvoke(
            [
                SystemMessage(content=RECOMMENDATION_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"症状要点：\n{_format_collected(state.get('collected', {}))}\n\n"
                        f"预问诊结论：\n{triage_text}{lead_hint}"
                    )
                ),
            ]
        )
    except Exception as exc:  # pragma: no cover - provider/network dependent
        print(f"--- [Clinic] recommendation summary failed: {exc} ---", flush=True)
        return {}

    if isinstance(result, TriageRecommendation):
        recommendation = result.model_dump()
    elif isinstance(result, dict):
        recommendation = dict(result)
    else:
        return {}
    if lead:
        recommendation["summary"] = lead
    return recommendation


async def conclude(state: ClinicState, config: Optional[RunnableConfig] = None) -> Command | dict:
    """
    ReAct triage answer + structured ``clinic_recommendation`` card.

    Clinic is a mounted subgraph, so a handoff here leaves through
    ``Command(graph=Command.PARENT, ...)`` rather than a plain node ``Command``.
    """
    system = await _build_system_prompt(state) + handoff_prompt_section(AGENT_ID)
    voice = _is_voice(state, config)
    if voice:
        system += VOICE_LEAD_INSTRUCTION
    skill_tools = get_agent_tools(tags=["clinic"])
    agent = create_react_agent(
        get_chat_llm("balanced"),
        tools=[load_skill, *skill_tools, *get_handoff_tools(AGENT_ID)],
        prompt=SystemMessage(content=system),
    )

    transcript = _transcript(state)
    sub_result = await agent.ainvoke({"messages": transcript})
    produced = list(sub_result["messages"][len(transcript):])

    handoff = apply_handoff(
        state,
        produced,
        parent=True,
        prefix_messages=state.get("turn_messages", []),
    )
    if isinstance(handoff, Command):
        return handoff

    triage_text = next(
        (
            _message_text(message)
            for message in reversed(produced)
            if isinstance(message, AIMessage) and _message_text(message).strip()
        ),
        "",
    )

    update: dict = {
        "turn_messages": produced,
        "messages": [*state.get("turn_messages", []), *produced],
    }
    if triage_text:
        recommendation = await _summarize_recommendation(triage_text, state, voice=voice)
        if recommendation:
            update["recommendation"] = recommendation
            _emit(_clinic_card(recommendation))
    return update


# ─── Subgraph assembly ────────────────────────────────────────────────────────

def build_clinic_graph() -> StateGraph:
    workflow = StateGraph(ClinicState)

    workflow.add_node("emergency_gate", emergency_gate)
    workflow.add_node("extract_symptoms", extract_symptoms)
    workflow.add_node("check_sufficiency", check_sufficiency)
    workflow.add_node("ask_followup", ask_followup)
    workflow.add_node("await_answer", await_answer)
    workflow.add_node("confirm_facts", confirm_facts)
    workflow.add_node("conclude", conclude)

    workflow.add_edge(START, "emergency_gate")
    workflow.add_conditional_edges(
        "emergency_gate",
        route_after_gate,
        {"extract_symptoms": "extract_symptoms", END: END},
    )
    workflow.add_edge("extract_symptoms", "check_sufficiency")
    workflow.add_conditional_edges(
        "check_sufficiency",
        route_after_sufficiency,
        {
            "ask_followup": "ask_followup",
            "confirm_facts": "confirm_facts",
            "conclude": "conclude",
        },
    )
    workflow.add_edge("ask_followup", "await_answer")
    # Every answer goes back through the rule gate, not straight to extraction.
    workflow.add_edge("await_answer", "emergency_gate")
    workflow.add_conditional_edges(
        "confirm_facts",
        route_after_confirm,
        {"conclude": "conclude", "emergency_gate": "emergency_gate"},
    )
    workflow.add_edge("conclude", END)

    return workflow.compile()


# Compiled subgraph mounted as `clinic_node` in the master graph.
clinic_node = build_clinic_graph()
