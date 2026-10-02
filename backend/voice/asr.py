"""
Streaming ASR adapter contract.

Generic code (``gateway``, ``turns``) only ever looks at ``AsrCapabilities``;
it never branches on a vendor name. A provider without server-side endpoint
events simply relies on the "说完了" button (``turn.end``); one without
confidence scores never triggers the low-confidence ladder.

Provider implementations live in ``voice/providers/``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal, Protocol

AsrEventKind = Literal["speech_start", "partial", "final", "silence"]


@dataclass(frozen=True)
class AsrCapabilities:
    partials: bool = True          # emits interim hypotheses
    endpoint_events: bool = True   # emits speech_start / silence
    hotwords: bool = False         # accepts a boosting word list
    confidence: bool = False       # finals carry a usable confidence
    # How late ``silence`` arrives after speech really stopped (a server VAD
    # that already waited its own end window). The gateway subtracts it from
    # its adaptive endpoint wait so the two waits do not stack.
    silence_lag: float = 0.0


@dataclass(frozen=True)
class AsrEvent:
    """
    One recogniser event.

    ``partial.text`` is the hypothesis of the utterance in progress (replace,
    don't append); ``final.text`` is a definite segment; ``silence`` means the
    speaker stopped and endpointing may start its adaptive wait.
    """

    kind: AsrEventKind
    text: str = ""
    confidence: float | None = None


class SpeechProviderError(RuntimeError):
    """A provider failure, classified for the client's ``error`` frame."""

    def __init__(self, message: str, *, error_class: str = "transient") -> None:
        super().__init__(message)
        self.error_class = error_class


class AsrStream(Protocol):
    async def send_audio(self, pcm: bytes) -> None: ...

    async def flush(self) -> AsrEvent | None:
        """Force out whatever is still pending as a ``final`` (or None)."""
        ...

    def events(self) -> AsyncIterator[AsrEvent]: ...

    async def close(self) -> None: ...


class AsrProvider(Protocol):
    name: str
    capabilities: AsrCapabilities

    async def open_stream(
        self, *, sample_rate: int, hotwords: tuple[str, ...] = ()
    ) -> AsrStream: ...


# Boosting list for providers that declare ``hotwords``: common symptoms and
# OTC drug names that general-purpose ASR tends to mishear.
DEFAULT_HOTWORDS: tuple[str, ...] = (
    "头疼", "头晕", "发烧", "咳嗽", "咳痰", "胸闷", "胸痛", "心慌", "气短",
    "腹痛", "腹泻", "恶心", "呕吐", "乏力", "失眠", "喉咙痛", "鼻塞", "流鼻涕",
    "皮疹", "瘙痒", "尿频", "尿急", "尿痛", "便秘", "关节痛", "腰疼",
    "布洛芬", "对乙酰氨基酚", "阿莫西林", "头孢", "奥美拉唑", "氯雷他定",
    "二甲双胍", "硝苯地平", "阿司匹林", "蒙脱石散",
)
