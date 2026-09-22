"""
Shared deterministic doubles for the backend test-suite.

`ScriptedChatModel` is a real `BaseChatModel`, so it can be handed straight to
`create_react_agent`: it replays a fixed list of `AIMessage`s (tool calls
included), one per invocation, and never touches the network.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class ScriptedChatModel(BaseChatModel):
    """Replays `script[i]` on the i-th invocation; repeats the last entry after."""

    script: list[AIMessage] = []
    invocations: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        index = len(self.invocations)
        self.invocations.append(list(messages))
        message = self.script[min(index, len(self.script) - 1)]
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Stream the scripted reply so `on_chat_model_stream` events fire."""
        index = len(self.invocations)
        self.invocations.append(list(messages))
        message = self.script[min(index, len(self.script) - 1)]
        chunk = AIMessageChunk(
            content=message.content,
            tool_call_chunks=[
                {
                    "name": call["name"],
                    "args": json.dumps(call.get("args") or {}, ensure_ascii=False),
                    "id": call.get("id"),
                    "index": position,
                }
                for position, call in enumerate(message.tool_calls or [])
            ],
        )
        yield ChatGenerationChunk(message=chunk)


def scripted(*messages: AIMessage) -> ScriptedChatModel:
    """Build a fresh `ScriptedChatModel` with its own invocation log."""
    return ScriptedChatModel(script=list(messages), invocations=[])


def tool_call(name: str, args: dict | None = None, call_id: str = "call_1") -> AIMessage:
    """An `AIMessage` that asks for exactly one tool call."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {}, "id": call_id}],
    )


class FakeKnowledgeBase:
    """A knowledge base that always returns nothing, so RAG stays offline."""

    async def aretrieve(self, _query: str, k: int = 3) -> list:
        return []

    async def amulti_query_retrieve(self, _queries: list[str], k: int = 4) -> list:
        return []

    def format_context(self, _docs: list) -> str:
        return ""
