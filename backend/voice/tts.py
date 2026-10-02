"""
Sentence-level TTS adapter contract.

Everything the call speaks is a complete, pre-checked short sentence (see
``render``), so the contract is one ``synthesize()`` per sentence yielding
PCM16 mono chunks at ``capabilities.sample_rate``. No LLM token stream is
ever piped into TTS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from voice.asr import SpeechProviderError
from voice.protocol import DEFAULT_TTS_SAMPLE_RATE


@dataclass(frozen=True)
class TtsCapabilities:
    speed_control: bool = False      # honours ``speed`` (elder mode uses 0.85)
    sentence_duration: bool = False  # can report a sentence's duration up front
    sample_rate: int = DEFAULT_TTS_SAMPLE_RATE


class TtsProvider(Protocol):
    name: str
    capabilities: TtsCapabilities

    def synthesize(self, text: str, *, speed: float = 1.0) -> AsyncIterator[bytes]: ...


def pcm_duration_ms(num_bytes: int, sample_rate: int) -> float:
    """Duration of PCM16 mono audio."""
    return (num_bytes / 2) / sample_rate * 1000 if sample_rate else 0.0


__all__ = ["SpeechProviderError", "TtsCapabilities", "TtsProvider", "pcm_duration_ms"]
