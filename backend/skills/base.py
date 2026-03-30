"""
BaseSkill — abstract contract every skill must implement.

Design principles (from prompt-engineering-patterns + langchain-architecture best practices):
  - Pydantic I/O schemas for validated, LLM-friendly tool calls
  - Structured output with confidence scores
  - Each skill is self-describing (name, description, tags) so agents can
    decide whether to load it based on the user's intent
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class SkillInput(BaseModel):
    """Base class for all skill input schemas."""
    pass


class SkillOutput(BaseModel):
    """Base class for all skill output schemas."""
    skill_name: str
    success: bool
    confidence: float = 1.0          # 0.0–1.0; surfaced in UI for transparency
    disclaimer: str = ""


class BaseSkill(ABC):
    """
    Abstract base for every skill in the registry.

    Subclasses must declare:
      name        — unique snake_case identifier used by the registry
      description — one-line description shown to the LLM as a tool hint
      tags        — categories (e.g. ['clinic', 'pharmacy']) controlling which
                    agents can auto-load this skill
    """
    name: str
    description: str
    tags: list[str] = []

    @abstractmethod
    def run(self, **kwargs: Any) -> SkillOutput:
        """Synchronous execution entry point."""
        ...

    async def arun(self, **kwargs: Any) -> SkillOutput:
        """
        Async execution entry point.
        Default implementation wraps run() — override for true async work.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.run(**kwargs))

    def to_tool_description(self) -> str:
        """Returns the string passed to the LLM as the tool's description."""
        return f"[Skill: {self.name}] {self.description}"
