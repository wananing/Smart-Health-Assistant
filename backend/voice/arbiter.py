"""
Output arbitration: generations, a single speaker, interruptibility, receipts.

* **Generation.** Every piece of outgoing audio (and its ``tts.sentence``
  frame) is stamped with the generation current when its job was queued.
  A barge-in, an emergency or a hang-up bumps the generation; the ``Outbox``
  drops anything stamped with an older one *inside its send lock*. Stale
  output is filtered, not chased through queues, so TTS audio that arrives
  late after ``tts.stop`` can never reach the client.
* **Single speaker.** One ``Speaker`` task plays queued ``SpeechJob``s in
  order; nothing else sends audio.
* **A stopped turn stays silent.** ``Speaker.stop()`` is the only way to cut
  speech and remembers the highest turn id it told the client to stop. The
  client drops every sentence and audio frame with ``turn_id <=`` that id,
  so ``enqueue`` gives any later job at or below it a fresh turn id
  (``new_turn_id``). Callers never have to know whether "their" turn was
  stopped — the emergency line or a follow-up spoken after a tap is heard.
* **Interruptible or not.** The emergency safety line is not; every sentence
  is also protected for its first ``protect_window`` seconds.
* **Receipts.** With ``playback_receipts`` the speaker waits for the client's
  ``playback.ended``; without, it waits for the audio's real-time duration.
"""
from __future__ import annotations

import asyncio
import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from voice.asr import SpeechProviderError
from voice.protocol import pack_downlink_audio, tts_sentence_frame
from voice.tts import TtsProvider, pcm_duration_ms
from voice.turns import TurnTrace, VoiceTimings


class Transport(Protocol):
    async def receive(self) -> str | bytes | None: ...

    async def send_text(self, text: str) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


@dataclass
class Utterance:
    text: str
    pcm: bytes | None = None  # pre-synthesised (cues); None → synthesise now


_job_ids = itertools.count(1)


@dataclass
class SpeechJob:
    turn_id: int
    utterances: list[Utterance]
    trace: TurnTrace | None = None
    interruptible: bool = True
    cue: bool = False
    # A terminal job closes its turn with ``done`` when it plays to the end;
    # fillers and "您还在吗" are not terminal.
    terminal: bool = True
    speak_mode: str = "none"
    generation: int = -1
    job_id: int = field(default_factory=lambda: next(_job_ids))
    done: asyncio.Event = field(default_factory=asyncio.Event)


class Arbiter:
    def __init__(self, timings: VoiceTimings) -> None:
        self.timings = timings
        self.generation = 0
        self.current: SpeechJob | None = None
        self.sentence_started_at: float | None = None
        self._bumped = asyncio.Event()

    def bump(self) -> int:
        """Invalidate everything queued or in flight."""
        self.generation += 1
        self._bumped.set()
        self._bumped = asyncio.Event()
        return self.generation

    async def wait_or_bump(self, timeout: float) -> bool:
        """Sleep up to ``timeout``; True if the generation changed meanwhile."""
        if timeout <= 0:
            return False
        bumped = self._bumped
        try:
            await asyncio.wait_for(bumped.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def can_barge_in(self, now: float) -> bool:
        job = self.current
        if job is None or not job.interruptible:
            return False
        if self.sentence_started_at is None:
            return False
        return now - self.sentence_started_at >= self.timings.protect_window


class Outbox:
    """Serialised writes to the transport with the generation filter applied."""

    def __init__(self, transport: Transport, arbiter: Arbiter) -> None:
        self._transport = transport
        self._arbiter = arbiter
        self._lock = asyncio.Lock()
        self.closed = False
        # Audio frames discarded by the generation filter (trace / tests).
        self.dropped_audio = 0

    async def send_json(self, frame: dict, *, generation: int | None = None) -> bool:
        async with self._lock:
            if self.closed:
                return False
            if generation is not None and generation != self._arbiter.generation:
                return False
            try:
                await self._transport.send_text(json.dumps(frame, ensure_ascii=False))
            except Exception:
                self.closed = True
                return False
            return True

    async def send_audio(
        self, generation: int, turn_id: int, sentence_id: int, seq: int, pcm: bytes
    ) -> bool:
        async with self._lock:
            if self.closed or generation != self._arbiter.generation:
                self.dropped_audio += 1
                return False
            try:
                await self._transport.send_bytes(pack_downlink_audio(turn_id, sentence_id, seq, pcm))
            except Exception:
                self.closed = True
                return False
            return True

    async def close(self, code: int = 1000) -> None:
        async with self._lock:
            if self.closed:
                return
            self.closed = True
            try:
                await self._transport.close(code)
            except Exception:
                pass


SpeakerEvent = Callable[[str, SpeechJob, dict[str, Any]], Awaitable[None]]


class Speaker:
    """The only producer of downlink audio."""

    CUE_CHUNK_MS = 100

    def __init__(
        self,
        *,
        outbox: Outbox,
        arbiter: Arbiter,
        tts: TtsProvider,
        timings: VoiceTimings,
        notify: SpeakerEvent,
        speed: float = 1.0,
        receipts: bool = False,
        new_turn_id: Callable[[], int] | None = None,
    ) -> None:
        self._outbox = outbox
        self._arbiter = arbiter
        self._tts = tts
        self._timings = timings
        self._notify = notify
        self._speed = speed
        self._receipts = receipts
        self._queue: asyncio.Queue[SpeechJob] = asyncio.Queue()
        self._sentence_ids = itertools.count(1)
        self._ended: dict[tuple[int, int], asyncio.Event] = {}
        self._played_ms: dict[int, int] = {}
        self._new_turn_id = new_turn_id or itertools.count(1_000_000).__next__
        # Highest turn id the client was told to stop (it then drops <= this).
        self.stopped_turn = -1

    @property
    def sample_rate(self) -> int:
        return self._tts.capabilities.sample_rate

    def enqueue(self, job: SpeechJob) -> SpeechJob:
        if job.turn_id <= self.stopped_turn:
            # The client would drop it: speak under a fresh, higher turn id.
            job.turn_id = self._new_turn_id()
        job.generation = self._arbiter.generation
        self._queue.put_nowait(job)
        return job

    def stop(self) -> SpeechJob | None:
        """
        Cut whatever is playing and drop the queue. Returns the job that was
        playing (the caller sends ``tts.stop`` for its turn id); from now on
        that id and every lower one are never spoken under again.
        """
        current = self._arbiter.current
        self._arbiter.bump()
        self.clear()
        if current is not None:
            self.stopped_turn = max(self.stopped_turn, current.turn_id)
        return current

    def clear(self) -> None:
        """Drop queued jobs (the caller bumps the generation for the current one)."""
        while not self._queue.empty():
            job = self._queue.get_nowait()
            job.done.set()

    @property
    def idle(self) -> bool:
        return self._arbiter.current is None and self._queue.empty()

    # --- receipts --------------------------------------------------------
    def on_playback(self, kind: str, turn_id: int, sentence_id: int, played_ms: int, now: float) -> None:
        job = self._arbiter.current
        if kind == "playback.started":
            if job is not None and job.turn_id == turn_id:
                self._arbiter.sentence_started_at = now
        elif kind in ("playback.ended", "playback.interrupted"):
            if job is not None and job.turn_id == turn_id:
                self._played_ms[job.job_id] = self._played_ms.get(job.job_id, 0) + max(0, played_ms)
            event = self._ended.get((turn_id, sentence_id))
            if event is not None:
                event.set()

    # --- main loop -------------------------------------------------------
    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            job = await self._queue.get()
            if job.generation != self._arbiter.generation:
                job.done.set()
                continue
            self._arbiter.current = job
            self._arbiter.sentence_started_at = None
            started = loop.time()
            try:
                result = await self._play(job)
            finally:
                if self._arbiter.current is job:
                    self._arbiter.current = None
                    self._arbiter.sentence_started_at = None
                job.done.set()
            elapsed_ms = int((loop.time() - started) * 1000)
            played = self._played_ms.pop(job.job_id, None)
            if played is None:
                played = min(elapsed_ms, result["generated_ms"])
            result["played_ms"] = played
            await self._notify("speech_done", job, result)

    async def _chunks(self, utterance: Utterance):
        if utterance.pcm is not None:
            step = max(2, self.sample_rate * self.CUE_CHUNK_MS // 1000 * 2)
            for offset in range(0, len(utterance.pcm), step):
                yield utterance.pcm[offset:offset + step]
            return
        source = self._tts.synthesize(utterance.text, speed=self._speed)
        try:
            async for chunk in source:
                yield chunk
        finally:
            # Close the vendor stream now (not at GC time) so a barge-in stops
            # synthesis immediately.
            await source.aclose()

    async def _play(self, job: SpeechJob) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        generation = job.generation
        generated_ms = 0.0
        start = loop.time()
        first_sound = True
        last_key: tuple[int, int] | None = None
        result: dict[str, Any] = {"completed": False, "generated_ms": 0, "error": None}

        for utterance in job.utterances:
            if generation != self._arbiter.generation:
                return result
            sentence_id = next(self._sentence_ids)
            frame = tts_sentence_frame(
                job.turn_id,
                sentence_id,
                utterance.text,
                interruptible=job.interruptible,
                sample_rate=self.sample_rate,
                cue=job.cue,
            )
            if not await self._outbox.send_json(frame, generation=generation):
                return result
            if self._receipts:
                if last_key is not None:
                    self._ended.pop(last_key, None)
                last_key = (job.turn_id, sentence_id)
                self._ended[last_key] = asyncio.Event()
            sentence_start_set = False
            seq = 0
            chunks = self._chunks(utterance)
            try:
                async for chunk in chunks:
                    if not await self._outbox.send_audio(generation, job.turn_id, sentence_id, seq, chunk):
                        result["generated_ms"] = int(generated_ms)
                        return result
                    seq += 1
                    if not sentence_start_set and not self._receipts:
                        self._arbiter.sentence_started_at = loop.time()
                        sentence_start_set = True
                    if first_sound:
                        first_sound = False
                        await self._notify("speech_started", job, {})
                    generated_ms += pcm_duration_ms(len(chunk), self.sample_rate)
                    ahead = generated_ms / 1000 - (loop.time() - start)
                    if ahead > self._timings.audio_lead:
                        if await self._arbiter.wait_or_bump(ahead - self._timings.audio_lead):
                            result["generated_ms"] = int(generated_ms)
                            return result
            except SpeechProviderError as exc:
                result["generated_ms"] = int(generated_ms)
                result["error"] = exc.error_class
                return result
            finally:
                await chunks.aclose()
            if self._receipts and not sentence_start_set and self._arbiter.sentence_started_at is None:
                # No playback.started yet: fall back to "sent" so barge-in still works.
                self._arbiter.sentence_started_at = loop.time()

        result["generated_ms"] = int(generated_ms)
        remaining = generated_ms / 1000 - (loop.time() - start)
        if self._receipts and last_key is not None:
            ended = self._ended[last_key]
            waiter = asyncio.ensure_future(ended.wait())
            bump = asyncio.ensure_future(self._arbiter.wait_or_bump(max(remaining, 0) + self._timings.playback_grace))
            done, pending = await asyncio.wait({waiter, bump}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            self._ended.pop(last_key, None)
        elif remaining > 0:
            await self._arbiter.wait_or_bump(remaining)
        result["completed"] = generation == self._arbiter.generation
        return result
