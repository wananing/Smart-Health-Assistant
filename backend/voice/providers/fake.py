"""
Scripted, offline ASR / TTS doubles — in the spirit of ``test_fakes.ScriptedChatModel``.

``FakeAsrProvider`` never recognises audio by itself: a test grabs the stream
it opened (``provider.streams[-1]``) and pushes the recogniser events it wants
(``push("partial", "头疼")``, ``push("silence")``…). Audio frames are only
counted, never stored.

``FakeTtsProvider`` "speaks" silence whose length is proportional to the text,
records what it was asked to say, and can be made to fail or to stall mid-
sentence (``gate``) so tests can deliver audio after a barge-in.

Selectable with ``ASR_PROVIDER=fake`` / ``TTS_PROVIDER=fake`` for frontend work
without vendor credentials: the call then runs on typed input and silent audio.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from voice.asr import AsrCapabilities, AsrEvent, SpeechProviderError
from voice.protocol import DEFAULT_TTS_SAMPLE_RATE
from voice.tts import TtsCapabilities

_CLOSED = object()


class FakeAsrStream:
    def __init__(self, *, flush_partial: bool = True) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._pending_partial = ""
        self._flush_partial = flush_partial
        self.frames_received = 0
        self.closed = False
        # What the next flush() returns, for providers without partials.
        self.flush_text: str | None = None

    # --- scripting API ---------------------------------------------------
    def push(self, kind: str, text: str = "", confidence: float | None = None) -> None:
        if kind == "partial":
            self._pending_partial = text
        elif kind == "final":
            self._pending_partial = ""
        self._queue.put_nowait(AsrEvent(kind=kind, text=text, confidence=confidence))  # type: ignore[arg-type]

    def fail(self, error_class: str = "transient") -> None:
        self._queue.put_nowait(SpeechProviderError("fake ASR failure", error_class=error_class))

    # --- AsrStream -------------------------------------------------------
    async def send_audio(self, pcm: bytes) -> None:
        self.frames_received += 1

    async def flush(self) -> AsrEvent | None:
        if self.flush_text is not None:
            text, self.flush_text = self.flush_text, None
            return AsrEvent(kind="final", text=text)
        if self._flush_partial and self._pending_partial:
            text, self._pending_partial = self._pending_partial, ""
            return AsrEvent(kind="final", text=text)
        return None

    async def events(self) -> AsyncIterator[AsrEvent]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(_CLOSED)


class FakeAsrProvider:
    name = "fake"

    def __init__(
        self,
        capabilities: AsrCapabilities | None = None,
        *,
        open_error: SpeechProviderError | None = None,
    ) -> None:
        self.capabilities = capabilities or AsrCapabilities(
            partials=True, endpoint_events=True, hotwords=True, confidence=True
        )
        self.open_error = open_error
        self.streams: list[FakeAsrStream] = []
        self.hotwords: tuple[str, ...] = ()

    async def open_stream(self, *, sample_rate: int, hotwords: tuple[str, ...] = ()) -> FakeAsrStream:
        if self.open_error is not None:
            raise self.open_error
        self.hotwords = hotwords
        stream = FakeAsrStream()
        self.streams.append(stream)
        return stream


class FakeTtsProvider:
    name = "fake"

    def __init__(
        self,
        *,
        sample_rate: int = DEFAULT_TTS_SAMPLE_RATE,
        ms_per_char: float = 5.0,
        chunk_ms: int = 40,
        fail: bool = False,
    ) -> None:
        self.capabilities = TtsCapabilities(
            speed_control=True, sentence_duration=False, sample_rate=sample_rate
        )
        self.ms_per_char = ms_per_char
        self.chunk_ms = chunk_ms
        self.fail = fail
        self.spoken: list[str] = []
        self.speeds: list[float] = []
        # When set, synthesis stalls after the first chunk until the event is set.
        self.gate: asyncio.Event | None = None

    async def synthesize(self, text: str, *, speed: float = 1.0) -> AsyncIterator[bytes]:
        if self.fail:
            raise SpeechProviderError("fake TTS failure", error_class="degraded")
        self.spoken.append(text)
        self.speeds.append(speed)
        total_samples = max(1, int(len(text) * self.ms_per_char * self.capabilities.sample_rate / 1000))
        chunk_samples = max(1, self.capabilities.sample_rate * self.chunk_ms // 1000)
        sent = 0
        first = True
        while sent < total_samples:
            size = min(chunk_samples, total_samples - sent)
            yield b"\x00\x00" * size
            sent += size
            if first and self.gate is not None:
                first = False
                await self.gate.wait()
            await asyncio.sleep(0)
