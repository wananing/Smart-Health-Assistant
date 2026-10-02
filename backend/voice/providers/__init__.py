"""
ASR / TTS provider selection, modelled on ``agents/llm.py``.

``ASR_PROVIDER`` and ``TTS_PROVIDER`` pick a provider each; every provider has
its own credential env names, and the generic ``ASR_*`` / ``TTS_*`` names
override any provider. ``resolve_speech_settings()`` validates without a
network call and is what ``test_voice_providers.py`` exercises;
``create_asr_provider()`` / ``create_tts_provider()`` build the adapter.

Providers:
  fake        Scripted, offline doubles (tests and UI development only: the
              fake ASR never hears anything, the fake TTS speaks silence).
  volcengine  火山引擎 streaming ASR (sauc bigmodel) + bidirectional TTS,
              verified live; see ``providers/volcengine.py``.
  dashscope   阿里云百炼. Credentials resolve; the adapter is not implemented.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from voice.asr import AsrProvider
from voice.protocol import DEFAULT_TTS_SAMPLE_RATE
from voice.tts import TtsProvider

SpeechPurpose = Literal["asr", "tts"]


class SpeechConfigurationError(ValueError):
    """Raised when speech provider environment variables are unusable."""


@dataclass(frozen=True)
class SpeechSettings:
    purpose: SpeechPurpose
    provider: str
    api_key: str = field(default="", repr=False)
    app_id: str = ""
    access_token: str = field(default="", repr=False)
    resource_id: str = ""
    endpoint: str = ""
    voice: str = ""
    sample_rate: int = DEFAULT_TTS_SAMPLE_RATE
    model: str = ""
    # ASR: server-side endpoint window (silence before an utterance is definite).
    end_window_ms: int = 600


@dataclass(frozen=True)
class _SpeechProfile:
    api_key_envs: tuple[str, ...] = ()
    app_id_envs: tuple[str, ...] = ()
    access_token_envs: tuple[str, ...] = ()
    resource_id_envs: tuple[str, ...] = ()
    voice_envs: tuple[str, ...] = ()
    endpoint_envs: tuple[str, ...] = ()
    model_envs: tuple[str, ...] = ()
    default_resource_id: str = ""
    default_endpoint: str = ""
    default_voice: str = ""
    default_model: str = ""
    # Either an API key, or app id + access token (older consoles).
    accepts_app_token_pair: bool = False
    requires_credentials: bool = True
    requires_voice: bool = False


# Endpoints and resource ids below are the values shown in the vendors'
# public docs at the time of writing; they are defaults only.
_ASR_PROFILES: dict[str, _SpeechProfile] = {
    "fake": _SpeechProfile(requires_credentials=False),
    "volcengine": _SpeechProfile(
        api_key_envs=("VOLC_VOICE_API_KEY", "VOLC_SPEECH_API_KEY"),
        app_id_envs=("VOLC_SPEECH_APP_ID",),
        access_token_envs=("VOLC_SPEECH_ACCESS_TOKEN",),
        resource_id_envs=("VOLC_ASR_RESOURCE_ID",),
        endpoint_envs=("ASR_URL",),
        model_envs=("ASR_MODEL_NAME",),
        default_resource_id="volc.seedasr.sauc.duration",
        # bigmodel_async: partials + server endpointing (verified live). The
        # bigmodel_nostream endpoint also works but gives no partials.
        default_endpoint="wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
        default_model="bigmodel",
        accepts_app_token_pair=True,
    ),
    "dashscope": _SpeechProfile(api_key_envs=("DASHSCOPE_API_KEY",)),
}

_TTS_PROFILES: dict[str, _SpeechProfile] = {
    "fake": _SpeechProfile(requires_credentials=False),
    "volcengine": _SpeechProfile(
        api_key_envs=("VOLC_VOICE_API_KEY", "VOLC_SPEECH_API_KEY"),
        app_id_envs=("VOLC_SPEECH_APP_ID",),
        access_token_envs=("VOLC_SPEECH_ACCESS_TOKEN",),
        resource_id_envs=("VOLC_TTS_RESOURCE_ID",),
        voice_envs=("TTS_SPEAKER", "VOLC_TTS_VOICE"),
        endpoint_envs=("TTS_URL",),
        default_resource_id="seed-tts-1.0",
        default_endpoint="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
        # Confirmed live with resource seed-tts-1.0.
        default_voice="zh_female_shuangkuaisisi_moon_bigtts",
        accepts_app_token_pair=True,
    ),
    "dashscope": _SpeechProfile(
        api_key_envs=("DASHSCOPE_API_KEY",),
        voice_envs=("DASHSCOPE_TTS_VOICE",),
        requires_voice=True,
    ),
}

_PROVIDER_ALIASES = {
    "volc": "volcengine",
    "doubao": "volcengine",
    "bytedance": "volcengine",
    "bailian": "dashscope",
    "aliyun": "dashscope",
    "qwen": "dashscope",
    "mock": "fake",
}


def _first_value(env: Mapping[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return ""


def _canonical_provider(raw: str, purpose: SpeechPurpose) -> str:
    env_name = f"{purpose.upper()}_PROVIDER"
    normalized = raw.strip().lower().replace("_", "-")
    if not normalized:
        raise SpeechConfigurationError(
            f"{env_name} is not set; voice calls are disabled. "
            f"Supported providers: {', '.join(_ASR_PROFILES)}"
        )
    provider = _PROVIDER_ALIASES.get(normalized, normalized)
    profiles = _ASR_PROFILES if purpose == "asr" else _TTS_PROFILES
    if provider not in profiles:
        raise SpeechConfigurationError(
            f"Unsupported {env_name} '{raw}'. Supported providers: {', '.join(profiles)}"
        )
    return provider


def resolve_speech_settings(
    env: Mapping[str, str] | None = None,
    *,
    purpose: SpeechPurpose,
) -> SpeechSettings:
    """Resolve and validate ASR or TTS settings without making a network call."""
    if purpose not in ("asr", "tts"):
        raise SpeechConfigurationError("Speech purpose must be 'asr' or 'tts'")

    values = os.environ if env is None else env
    prefix = purpose.upper()
    provider = _canonical_provider(values.get(f"{prefix}_PROVIDER", ""), purpose)
    profile = (_ASR_PROFILES if purpose == "asr" else _TTS_PROFILES)[provider]

    api_key_names = (f"{prefix}_API_KEY", *profile.api_key_envs)
    app_id_names = (f"{prefix}_APP_ID", *profile.app_id_envs)
    token_names = (f"{prefix}_ACCESS_TOKEN", *profile.access_token_envs)
    resource_names = (f"{prefix}_RESOURCE_ID", *profile.resource_id_envs)
    voice_names = (f"{prefix}_VOICE", *profile.voice_envs)

    api_key = _first_value(values, api_key_names)
    app_id = _first_value(values, app_id_names)
    access_token = _first_value(values, token_names)

    if profile.requires_credentials and not api_key:
        if not (profile.accepts_app_token_pair and app_id and access_token):
            options = ", ".join(api_key_names)
            if profile.accepts_app_token_pair:
                options += f" (or both {app_id_names[-1]} and {token_names[-1]})"
            raise SpeechConfigurationError(
                f"Missing {purpose.upper()} credentials. Configure one of: {options}"
            )

    voice = _first_value(values, voice_names) or profile.default_voice
    if profile.requires_voice and not voice:
        raise SpeechConfigurationError(
            f"Missing TTS voice. Configure one of: {', '.join(voice_names)}"
        )

    sample_rate = DEFAULT_TTS_SAMPLE_RATE
    raw_rate = values.get(f"{prefix}_SAMPLE_RATE", "").strip()
    if purpose == "tts" and raw_rate:
        try:
            sample_rate = int(raw_rate)
        except ValueError as exc:
            raise SpeechConfigurationError("TTS_SAMPLE_RATE must be an integer") from exc
        if sample_rate not in (8_000, 16_000, 22_050, 24_000, 32_000, 44_100, 48_000):
            raise SpeechConfigurationError(f"Unsupported TTS_SAMPLE_RATE {sample_rate}")

    end_window_ms = 600
    raw_window = values.get("ASR_END_WINDOW_MS", "").strip()
    if purpose == "asr" and raw_window:
        try:
            end_window_ms = int(raw_window)
        except ValueError as exc:
            raise SpeechConfigurationError("ASR_END_WINDOW_MS must be an integer") from exc
        if not 200 <= end_window_ms <= 5000:
            raise SpeechConfigurationError("ASR_END_WINDOW_MS must be between 200 and 5000")

    endpoint = _first_value(values, (f"{prefix}_ENDPOINT", *profile.endpoint_envs)) or profile.default_endpoint
    if endpoint and not endpoint.startswith(("wss://", "ws://")):
        raise SpeechConfigurationError(f"{purpose.upper()} endpoint must be a ws:// or wss:// URL")

    return SpeechSettings(
        purpose=purpose,
        provider=provider,
        api_key=api_key,
        app_id=app_id,
        access_token=access_token,
        resource_id=_first_value(values, resource_names) or profile.default_resource_id,
        endpoint=endpoint,
        voice=voice,
        sample_rate=sample_rate,
        model=_first_value(values, (f"{prefix}_MODEL", *profile.model_envs)) or profile.default_model,
        end_window_ms=end_window_ms,
    )


def create_asr_provider(settings: SpeechSettings) -> AsrProvider:
    if settings.provider == "fake":
        from voice.providers.fake import FakeAsrProvider

        return FakeAsrProvider()
    if settings.provider == "volcengine":
        from voice.providers.volcengine import create_volcengine_asr

        return create_volcengine_asr(settings)
    if settings.provider == "dashscope":
        raise SpeechConfigurationError(
            "The DashScope (百炼) ASR adapter is not implemented yet; "
            "use ASR_PROVIDER=fake for UI development."
        )
    raise SpeechConfigurationError(f"Unsupported ASR provider '{settings.provider}'")


def create_tts_provider(settings: SpeechSettings) -> TtsProvider:
    if settings.provider == "fake":
        from voice.providers.fake import FakeTtsProvider

        return FakeTtsProvider(sample_rate=settings.sample_rate)
    if settings.provider == "volcengine":
        from voice.providers.volcengine import create_volcengine_tts

        return create_volcengine_tts(settings)
    if settings.provider == "dashscope":
        raise SpeechConfigurationError(
            "The DashScope (百炼) TTS adapter is not implemented yet; "
            "use TTS_PROVIDER=fake for UI development."
        )
    raise SpeechConfigurationError(f"Unsupported TTS provider '{settings.provider}'")


def load_speech_providers(
    env: Mapping[str, str] | None = None,
) -> tuple[AsrProvider, TtsProvider]:
    """Resolve both providers from the environment; raises SpeechConfigurationError."""
    asr = create_asr_provider(resolve_speech_settings(env, purpose="asr"))
    tts = create_tts_provider(resolve_speech_settings(env, purpose="tts"))
    return asr, tts


__all__ = [
    "SpeechConfigurationError",
    "SpeechSettings",
    "create_asr_provider",
    "create_tts_provider",
    "load_speech_providers",
    "resolve_speech_settings",
]
