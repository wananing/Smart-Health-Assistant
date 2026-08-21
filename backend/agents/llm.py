"""Central model configuration for chat and vision calls.

All configured providers use an OpenAI-compatible API. ``ark`` remains the
default so existing deployments continue to work without changing ``.env``.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_openai import ChatOpenAI


ModelPurpose = Literal["chat", "vision"]


class LLMConfigurationError(ValueError):
    """Raised when model provider environment variables are incomplete."""


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    api_key: str = field(repr=False)
    model: str
    base_url: str | None
    extra_body: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class _ProviderProfile:
    api_key_envs: tuple[str, ...]
    model_envs: tuple[str, ...]
    base_url_envs: tuple[str, ...] = ()
    vision_model_envs: tuple[str, ...] = ()
    default_base_url: str | None = None
    default_model: str | None = None
    requires_base_url: bool = False
    extra_body: Mapping[str, Any] | None = None


_PROVIDERS: dict[str, _ProviderProfile] = {
    "ark": _ProviderProfile(
        api_key_envs=("ARK_API_KEY",),
        model_envs=("ARK_MODEL_ID",),
        base_url_envs=("ARK_BASE_URL",),
        vision_model_envs=("ARK_VISION_MODEL_ID",),
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-seed-1-6-flash-250828",
        extra_body={"thinking": {"type": "disabled"}},
    ),
    "openai": _ProviderProfile(
        api_key_envs=("OPENAI_API_KEY",),
        model_envs=("OPENAI_MODEL",),
        base_url_envs=("OPENAI_BASE_URL",),
        vision_model_envs=("OPENAI_VISION_MODEL",),
    ),
    "deepseek": _ProviderProfile(
        api_key_envs=("DEEPSEEK_API_KEY",),
        model_envs=("DEEPSEEK_MODEL",),
        base_url_envs=("DEEPSEEK_BASE_URL",),
        vision_model_envs=("DEEPSEEK_VISION_MODEL",),
        default_base_url="https://api.deepseek.com",
    ),
    "qwen": _ProviderProfile(
        api_key_envs=("DASHSCOPE_API_KEY",),
        model_envs=("QWEN_MODEL", "DASHSCOPE_MODEL"),
        base_url_envs=("DASHSCOPE_BASE_URL",),
        vision_model_envs=("QWEN_VISION_MODEL",),
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    "zhipu": _ProviderProfile(
        api_key_envs=("ZAI_API_KEY", "ZHIPU_API_KEY"),
        model_envs=("ZHIPU_MODEL", "ZAI_MODEL"),
        base_url_envs=("ZHIPU_BASE_URL", "ZAI_BASE_URL"),
        vision_model_envs=("ZHIPU_VISION_MODEL", "ZAI_VISION_MODEL"),
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
    ),
    "custom": _ProviderProfile(
        api_key_envs=(),
        model_envs=(),
        requires_base_url=True,
    ),
}

_PROVIDER_ALIASES = {
    "volcengine": "ark",
    "doubao": "ark",
    "dashscope": "qwen",
    "tongyi": "qwen",
    "glm": "zhipu",
    "zai": "zhipu",
    "compatible": "custom",
    "openai-compatible": "custom",
}

_PRESETS: dict[str, float] = {
    "router": 0.0,
    "precise": 0.2,
    "balanced": 0.4,
    "fast": 0.7,
}


def _first_value(env: Mapping[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return ""


def _canonical_provider(raw_provider: str) -> str:
    normalized = raw_provider.strip().lower().replace("_", "-") or "ark"
    provider = _PROVIDER_ALIASES.get(normalized, normalized)
    if provider not in _PROVIDERS:
        supported = ", ".join(_PROVIDERS)
        raise LLMConfigurationError(
            f"Unsupported LLM_PROVIDER '{raw_provider}'. Supported providers: {supported}"
        )
    return provider


def resolve_model_settings(
    env: Mapping[str, str] | None = None,
    *,
    purpose: ModelPurpose = "chat",
) -> ModelSettings:
    """Resolve and validate provider settings without making a network call."""
    if purpose not in ("chat", "vision"):
        raise LLMConfigurationError("Model purpose must be 'chat' or 'vision'")

    values = os.environ if env is None else env
    chat_provider = _canonical_provider(values.get("LLM_PROVIDER", "ark"))
    vision_provider_raw = values.get("VISION_PROVIDER", "")
    provider = (
        _canonical_provider(vision_provider_raw)
        if purpose == "vision" and vision_provider_raw.strip()
        else chat_provider
    )
    profile = _PROVIDERS[provider]
    inherits_chat_settings = purpose == "chat" or provider == chat_provider

    api_key_names = ("LLM_API_KEY", *profile.api_key_envs)
    model_names = ("LLM_MODEL", *profile.model_envs)
    base_url_names = ("LLM_BASE_URL", *profile.base_url_envs)

    if purpose == "vision":
        api_key_names = (
            "VISION_API_KEY",
            *(("LLM_API_KEY",) if inherits_chat_settings else ()),
            *profile.api_key_envs,
        )
        model_names = (
            "VISION_MODEL",
            *profile.vision_model_envs,
            *(("LLM_MODEL",) if inherits_chat_settings else ()),
            *profile.model_envs,
        )
        base_url_names = (
            "VISION_BASE_URL",
            *(("LLM_BASE_URL",) if inherits_chat_settings else ()),
            *profile.base_url_envs,
        )

    api_key = _first_value(values, api_key_names)
    if not api_key:
        raise LLMConfigurationError(
            f"Missing model API key. Configure one of: {', '.join(api_key_names)}"
        )

    model = _first_value(values, model_names) or profile.default_model or ""
    if not model:
        raise LLMConfigurationError(
            f"Missing model name. Configure one of: {', '.join(model_names)}"
        )

    base_url = _first_value(values, base_url_names) or profile.default_base_url
    if profile.requires_base_url and not base_url:
        raise LLMConfigurationError(
            f"Missing compatible API base URL. Configure one of: {', '.join(base_url_names)}"
        )

    return ModelSettings(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
        extra_body=profile.extra_body,
    )


def get_chat_llm(
    preset: str = "balanced",
    *,
    streaming: bool = True,
    temperature: float | None = None,
) -> ChatOpenAI:
    """Return the configured OpenAI-compatible LangChain chat model."""
    settings = resolve_model_settings()
    resolved_temp = temperature if temperature is not None else _PRESETS.get(preset, 0.4)

    kwargs: dict[str, Any] = {
        "api_key": settings.api_key,
        "model": settings.model,
        "temperature": resolved_temp,
        "streaming": streaming,
    }
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if settings.extra_body:
        kwargs["extra_body"] = settings.extra_body

    return ChatOpenAI(**kwargs)
