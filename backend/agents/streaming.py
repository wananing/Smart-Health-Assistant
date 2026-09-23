"""
Custom-stream helpers shared by every agent module.

LangGraph exposes a per-run writer through ``langgraph.config.get_stream_writer``.
Anything pushed through it lands on the graph's ``custom`` stream, which
``main.py`` forwards to the browser verbatim as an SSE event. That is how the
agents own their own UI output: a tool (or a node) emits an already-shaped SSE
payload instead of ``main.py`` sniffing tool names on ``on_tool_end``.

Only the payload types listed in ``main._STREAMABLE_CUSTOM_TYPES`` (``card`` and
``text``) are forwarded, so a stray write can never invent a new event type.
"""
from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer


def emit_custom(payload: dict) -> None:
    """Push an SSE-shaped payload onto LangGraph's ``custom`` stream, if any.

    Safe to call outside a graph run (unit tests, plain scripts): the writer is
    simply missing and the payload is dropped.
    """
    try:
        writer = get_stream_writer()
    except Exception:
        # Outside a Pregel run LangGraph raises whatever its config lookup
        # raises (RuntimeError, KeyError('__pregel_runtime'), …). A missing
        # writer is never fatal — the payload is simply dropped.
        return
    if writer is not None:
        writer(payload)


def emit_card(card_type: str, data: Any) -> None:
    """Emit a ``card`` SSE event the frontend ``ChatCardRenderer`` understands."""
    emit_custom({"type": "card", "payload": {"type": card_type, "data": data}})


def emit_text(content: str) -> None:
    """Emit a plain ``text`` SSE event (reuses the normal chat bubble)."""
    if content:
        emit_custom({"type": "text", "content": content})
