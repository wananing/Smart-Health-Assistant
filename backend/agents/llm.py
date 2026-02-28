"""
LLM Configuration Module.

Centralises all LangChain LLM client creation for the agent system.
To switch providers or models, update this single file.

Usage:
    from agents.llm import get_chat_llm

    llm = get_chat_llm()            # default (balanced)
    llm = get_chat_llm("precise")   # low-temp, for factual tasks
    llm = get_chat_llm("fast")      # higher-temp, for creative tasks
    llm = get_chat_llm("router")    # deterministic, for classification
"""
import os
from langchain_openai import ChatOpenAI

# ──────────────────────────────────────────────
# Shared API settings (pulled from .env)
# ──────────────────────────────────────────────
_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

def _ark_api_key() -> str:
    return os.environ.get("ARK_API_KEY", "")

def _model_id() -> str:
    return os.environ.get("ARK_MODEL_ID", "doubao-seed-1-6-flash-250828")

# ──────────────────────────────────────────────
# Temperature presets
# ──────────────────────────────────────────────
_PRESETS: dict[str, float] = {
    "router":   0.0,   # deterministic – used for intent classification
    "precise":  0.2,   # low creativity – used for medical/factual reports
    "balanced": 0.4,   # default – used for triage / clinic Q&A
    "fast":     0.7,   # more creative – used for general health advice
}


def get_chat_llm(
    preset: str = "balanced",
    *,
    streaming: bool = True,
    temperature: float | None = None,
) -> ChatOpenAI:
    """
    Return a configured ChatOpenAI instance.

    Args:
        preset:      One of 'router', 'precise', 'balanced', 'fast'.
                     Ignored when `temperature` is explicitly provided.
        streaming:   Enable token streaming (default True).
        temperature: Override the preset temperature.

    Returns:
        A ChatOpenAI instance ready to use with LangChain/LangGraph.
    """
    resolved_temp = temperature if temperature is not None else _PRESETS.get(preset, 0.4)

    return ChatOpenAI(
        api_key=_ark_api_key(),
        base_url=_BASE_URL,
        model=_model_id(),
        temperature=resolved_temp,
        streaming=streaming,
        extra_body={"thinking": {"type": "disabled"}}

    )
