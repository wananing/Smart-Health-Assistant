"""
Swarm-style handoffs between the specialist agents.

Why not ``Command(goto=..., graph=Command.PARENT)`` straight from the tool?
Four of the five specialists are plain node *functions* that call
``create_react_agent(...).ainvoke(...)`` internally. That inner agent is its own
Pregel run, so a ``Command`` raised inside one of its tools can only reach that
inner graph — never the master graph. The robust pattern used here instead:

  1. ``transfer_to_<agent>`` is an ordinary tool. It returns a recognisable JSON
     payload ``{"handoff": "<agent_id>"}`` as its ``ToolMessage``.
  2. After ``ainvoke`` returns, the node function calls :func:`apply_handoff`,
     which scans the newly produced messages for that payload.
  3. On a hit the node returns ``Command(goto=<target node>, update={...})`` so
     the master graph re-dispatches the *same* user turn to the right agent.

The clinic agent is a mounted subgraph, so it hands off with
``Command(graph=Command.PARENT, ...)`` — see ``apply_handoff(parent=True)``.

``handoff_count`` in ``MainAgentState`` caps this at
``MAX_HANDOFFS_PER_TURN`` hop per turn so two agents cannot ping-pong forever.
``router_node`` resets it at the start of every turn.
"""
from __future__ import annotations

import json
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.types import Command

# Agent id (the value kept in ``MainAgentState['active_agent']``) → graph node.
AGENT_TO_NODE: dict[str, str] = {
    "clinic_agent": "clinic_node",
    "insurance_agent": "insurance_node",
    "report_agent": "report_node",
    "pharmacy_agent": "pharmacy_node",
    "advisor_agent": "advisor_node",
}

# Agent id → (tool name, what that specialist is responsible for).
_HANDOFF_SPECS: dict[str, tuple[str, str]] = {
    "clinic_agent": (
        "transfer_to_clinic",
        "预问诊助手：用户描述身体不适或症状，想知道该看哪个科、是否需要就医。",
    ),
    "insurance_agent": (
        "transfer_to_insurance",
        "医保助手：医保余额、报销比例与政策、消费明细、缴费记录、异地就医备案。",
    ),
    "report_agent": (
        "transfer_to_report",
        "报告解读助手：化验单、体检报告、检验指标数值的解读。",
    ),
    "pharmacy_agent": (
        "transfer_to_pharmacy",
        "用药咨询助手：药品说明书、用法用量、副作用、药物相互作用、附近药店、OTC 推荐。",
    ),
    "advisor_agent": (
        "transfer_to_advisor",
        "健康顾问：通用健康科普、饮食作息建议、以及与上述专科都无关的闲聊问候。",
    ),
}

# At most this many handoffs may be honoured within a single user turn.
MAX_HANDOFFS_PER_TURN = 1

HANDOFF_TOOL_NAMES: frozenset[str] = frozenset(
    name for name, _ in _HANDOFF_SPECS.values()
)

# tool name → the display label main.py shows while the transfer runs.
HANDOFF_TOOL_LABELS: dict[str, str] = {
    "transfer_to_clinic": "正在转接预问诊助手…",
    "transfer_to_insurance": "正在转接医保助手…",
    "transfer_to_report": "正在转接报告解读助手…",
    "transfer_to_pharmacy": "正在转接用药咨询助手…",
    "transfer_to_advisor": "正在转接健康顾问…",
}


def _build_handoff_tool(agent_id: str) -> BaseTool:
    """Create the ``transfer_to_<agent>`` tool for one target specialist."""
    tool_name, responsibility = _HANDOFF_SPECS[agent_id]
    description = (
        f"把当前对话转接给{responsibility}\n"
        "当用户这一轮的请求明显属于该专家的职责范围、而不属于你自己时调用本工具。"
        "调用后不要再尝试回答用户的问题，接手的专家会回答。"
    )

    @tool(tool_name, description=description)
    def _handoff(reason: str = "") -> str:
        """Hand the conversation over to another specialist agent."""
        print(f"--- [Handoff] → {agent_id} ({reason or 'no reason given'}) ---", flush=True)
        return json.dumps({"handoff": agent_id, "reason": reason}, ensure_ascii=False)

    return _handoff


def get_handoff_tools(exclude: str) -> list[BaseTool]:
    """Handoff tools for every agent *except* ``exclude`` (the caller itself)."""
    return [
        _build_handoff_tool(agent_id)
        for agent_id in _HANDOFF_SPECS
        if agent_id != exclude
    ]


def handoff_prompt_section(exclude: str) -> str:
    """The system-prompt paragraph telling an agent when to transfer."""
    lines = [
        f"- {_HANDOFF_SPECS[agent_id][0]} → {_HANDOFF_SPECS[agent_id][1]}"
        for agent_id in _HANDOFF_SPECS
        if agent_id != exclude
    ]
    targets = "\n".join(lines)
    return f"""

【转接其他专家】
如果用户这一轮的问题明显不属于你的职责范围，请调用对应的转接工具，把对话交给更合适的专家：
{targets}

转接规则：
- 只有当用户的需求清楚地属于别人时才转接；不确定就自己先回答。
- 调用转接工具后，只回复一句不超过 20 字的过渡语，不要再回答用户的问题——接手的专家会回答。
- 一轮对话最多转接一次。"""


# ─── Detection ────────────────────────────────────────────────────────────────

def handoff_target(message: BaseMessage) -> str | None:
    """Return the target agent id when ``message`` is a handoff ToolMessage."""
    if not isinstance(message, ToolMessage):
        return None
    if getattr(message, "name", None) not in HANDOFF_TOOL_NAMES:
        return None
    content = message.content
    if not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    target = payload.get("handoff")
    return target if target in AGENT_TO_NODE else None


def split_handoff(
    new_messages: Sequence[BaseMessage],
) -> tuple[str | None, list[BaseMessage]]:
    """
    Split a sub-agent's new messages around the first handoff.

    Returns ``(target_agent_id | None, messages_to_keep)``. Everything from the
    ``AIMessage`` that requested the transfer onwards is dropped: the tool call,
    its ``ToolMessage`` and the sub-agent's transitional wrap-up sentence. That
    keeps the message history internally consistent (no orphaned ``tool_calls``)
    and leaves the user's own question as the last message the target agent sees.
    """
    messages = list(new_messages)
    for index, message in enumerate(messages):
        target = handoff_target(message)
        if target is None:
            continue
        cut = index
        call_id = getattr(message, "tool_call_id", None)
        for back in range(index - 1, -1, -1):
            candidate = messages[back]
            if isinstance(candidate, AIMessage) and any(
                call.get("id") == call_id for call in (candidate.tool_calls or [])
            ):
                cut = back
                break
        return target, messages[:cut]
    return None, messages


def apply_handoff(
    state: dict,
    new_messages: Sequence[BaseMessage],
    *,
    parent: bool = False,
    prefix_messages: Sequence[BaseMessage] | None = None,
) -> Command | dict:
    """
    Turn a sub-agent's output into either a plain state update or a ``Command``.

    ``prefix_messages`` are messages the node produced before running the
    sub-agent (the clinic follow-up Q&A); they are always handed to the parent.
    ``parent=True`` is for the clinic subgraph, whose nodes must target the
    master graph explicitly with ``Command(graph=Command.PARENT, ...)``.
    """
    prefix = list(prefix_messages or [])
    target, kept = split_handoff(new_messages)

    if target is None:
        return {"messages": [*prefix, *new_messages]}

    honoured = int(state.get("handoff_count", 0) or 0)
    if honoured >= MAX_HANDOFFS_PER_TURN:
        # Already transferred once this turn — keep the sub-agent's own reply
        # (tool call included, so the history stays valid) and stop here.
        print(
            f"--- [Handoff] Ignoring a second handoff to {target} this turn ---",
            flush=True,
        )
        return {"messages": [*prefix, *new_messages]}

    print(f"--- [Handoff] Routing to {AGENT_TO_NODE[target]} ---", flush=True)
    update = {
        "messages": [*prefix, *kept],
        "active_agent": target,
        "next_agent": target,
        "handoff_count": honoured + 1,
    }
    if parent:
        return Command(
            graph=Command.PARENT,
            goto=AGENT_TO_NODE[target],
            update=update,
        )
    return Command(goto=AGENT_TO_NODE[target], update=update)


# Every node a handoff-capable agent may jump to, for ``add_node(destinations=)``.
def handoff_destinations(exclude: str) -> tuple[str, ...]:
    """Graph nodes reachable from the agent ``exclude`` via a handoff."""
    return tuple(
        AGENT_TO_NODE[agent_id] for agent_id in _HANDOFF_SPECS if agent_id != exclude
    )
