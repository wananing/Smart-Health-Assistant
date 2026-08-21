"""DeepEval adapter backed by the repository's configured chat model."""

from __future__ import annotations

from typing import Any

from deepeval.models.base_model import DeepEvalBaseLLM
from pydantic import BaseModel

from agents.llm import get_chat_llm, resolve_model_settings


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return str(content) if content is not None else ""


class ProjectEvaluationModel(DeepEvalBaseLLM):
    """Expose the configured OpenAI-compatible LangChain model to DeepEval."""

    def __init__(self) -> None:
        self.model = get_chat_llm("precise", streaming=False)
        settings = resolve_model_settings()
        self._model_name = f"{settings.provider}:{settings.model}"

    def load_model(self):
        return self.model

    def generate(
        self, prompt: str, schema: type[BaseModel] | None = None
    ) -> str | BaseModel:
        model = self.load_model()
        if schema is not None:
            return model.with_structured_output(schema).invoke(prompt)
        return _content_text(model.invoke(prompt).content)

    async def a_generate(
        self, prompt: str, schema: type[BaseModel] | None = None
    ) -> str | BaseModel:
        model = self.load_model()
        if schema is not None:
            return await model.with_structured_output(schema).ainvoke(prompt)
        response = await model.ainvoke(prompt)
        return _content_text(response.content)

    def get_model_name(self) -> str:
        return self._model_name
