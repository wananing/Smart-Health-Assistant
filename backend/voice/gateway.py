"""
Voice gateway: one ``VoiceCall`` per ``/api/voice`` WebSocket.

The gateway is a text client of the master graph, exactly like ``/api/chat``:
``chat_mode=clinic``, the same ``thread_id``, and ``Command(resume=…)`` while
an ``interrupt`` is pending (it reuses ``main._resolve_graph_input`` through
``GraphBridge``). It adds listening, endpointing, deciding what to say and
saying it — the medical logic stays in ``agents/clinic.py``.

Concurrency model: a handful of helper tasks (WebSocket receiver, ASR pump,
speaker, graph run, timers) only *post* items to ``inbox``; one loop consumes
them in order and owns all call state. That keeps the turn state machine
deterministic and testable with scripted events.

Privacy: no audio, transcript or health text is ever printed. Trace lines
(``TurnTrace.log_line``) carry ids, enums and durations only. ASR finals and
typed text pass through ``redact_sensitive_text`` before entering the graph.
"""
from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable
from uuid import uuid4

from pydantic import BaseModel

from agents.clinic import _FIELD_LABELS, SymptomFacts
from agents.vision import redact_sensitive_text
from voice import protocol as proto
from voice.arbiter import Arbiter, Outbox, Speaker, SpeechJob, Transport, Utterance
from voice.asr import DEFAULT_HOTWORDS, AsrEvent, AsrProvider, AsrStream, SpeechProviderError
from voice.cues import CueCache, shared_cue_cache
from voice.render import LeadCutter, RunOutcome, SpeechPlan, plan_for_outcome, plan_interrupt
from voice.shortcuts import classify, is_affirmative_answer, is_backchannel, meaningful_length
from voice.tts import TtsProvider
from voice.turns import CallState, NoHearLadder, TurnTrace, VoiceTimings, endpoint_wait

# Custom-stream types the voice channel understands on top of card/text.
VOICE_CUSTOM_TYPES = frozenset({"card", "text", "facts"})

# Graph events forwarded to the client in their SSE shape.
_FORWARDED_EVENTS = {"text", "card", "node_start", "node_end", "tool_start", "tool_end"}

# A node_start for any of these means the turn was handed to another specialist.
_HANDOFF_NODES = {"insurance_node", "report_node", "pharmacy_node", "advisor_node"}

LOW_CONFIDENCE = 0.5
MAX_ASR_RECONNECTS = 3
ELDER_TTS_SPEED = 0.85

_FACT_FIELDS = tuple(SymptomFacts.model_fields)
_SHORT_FACT_LABELS = {
    "chief_complaint": "主要不适",
    "location": "部位",
    "duration": "持续时间",
    "severity": "严重程度",
    "associated_symptoms": "伴随症状",
    "onset": "起病方式",
    "triggers": "诱因",
}


@dataclass
class GraphBridge:
    """What the gateway needs from ``main`` — injected to avoid an import cycle."""

    # (config, turn_state, full_state, user_text) -> graph input | None
    resolve_input: Callable[[dict, dict, dict, str], Awaitable[Any]]
    # (graph_input, config, *, custom_types) -> async iterator of event dicts
    iter_events: Callable[..., AsyncIterator[dict]]
    # (text, user_info, channel) -> MainAgentState for one user message
    build_state: Callable[[str, dict, str], dict]
    # config -> StateSnapshot (with subgraph states)
    get_state: Callable[[dict], Awaitable[Any]]
    # raises when the chat model is misconfigured
    check_config: Callable[[], Any] | None = None
    # config -> None: close out a run the gateway cancelled (watchdog)
    abandon_run: Callable[[dict], Awaitable[Any]] | None = None


class VoiceCall:
    def __init__(
        self,
        transport: Transport,
        *,
        bridge: GraphBridge,
        asr: AsrProvider,
        tts: TtsProvider,
        timings: VoiceTimings | None = None,
        cue_factory: Callable[[TtsProvider, float], CueCache] | None = None,
        hotwords: tuple[str, ...] = DEFAULT_HOTWORDS,
    ) -> None:
        self._transport = transport
        self._bridge = bridge
        self._asr = asr
        self._tts = tts
        self.timings = timings or VoiceTimings()
        self._cue_factory = cue_factory or (lambda provider, speed: shared_cue_cache(provider, speed=speed))
        self._hotwords = hotwords

        self.inbox: asyncio.Queue = asyncio.Queue()
        self.arbiter = Arbiter(self.timings)
        self.outbox = Outbox(transport, self.arbiter)
        self.speaker: Speaker | None = None
        self.cues: CueCache | None = None

        self.state: CallState = "listening"
        self.thread_id = ""
        self.user_info: dict = {}
        self.elder_mode = False
        self.half_duplex = True
        self.receipts = False
        self.ended = False
        self.end_reason: str | None = None
        # 1000 tells the client "the call is over" (it merges the transcript);
        # anything else is a drop it may reconnect from.
        self.close_code = 1011

        self._turn_ids = itertools.count(1)
        self.traces: list[TurnTrace] = []
        self._user_turn: TurnTrace | None = None

        # ASR buffer for the utterance in progress.
        self._asr_stream: AsrStream | None = None
        self._asr_reconnects = 0
        self._segments: list[str] = []
        self._confidences: list[float] = []
        self._partial = ""
        self._speech_active = False
        self._speech_started_at: float | None = None

        # Graph run in flight.
        self._run_task: asyncio.Task | None = None
        self._run_token = 0
        self._run_turn: TurnTrace | None = None
        self._outcome = RunOutcome()
        # The conclusion's first sentence, spoken while the body still streams.
        self._lead: LeadCutter | None = None
        self._lead_spoken = False
        self._buffered: list[tuple[str, TurnTrace]] = []
        self.pending_interrupt: dict | None = None

        # Screen state mirrored for the symptom panel and the summary card.
        self.collected: dict = {}
        self.missing: list[str] = []
        self.facts_version = 0
        self.recommendation: dict | None = None
        self.emergency_flags: tuple[str, ...] = ()
        self._started_at = datetime.now(timezone.utc)

        self._last_spoken: SpeechJob | None = None
        self._timers: dict[str, tuple[int, asyncio.Task]] = {}
        self._timer_tokens = itertools.count(1)
        self._tasks: list[asyncio.Task] = []
        self._no_hear = NoHearLadder(elder_mode=False)
        self._degraded_notified = False
        self._idle_prompted = False
        # Set by the third "didn't hear you": from then on only the client's
        # turn.end (or typed / tapped input) commits a turn — no auto endpointing.
        self.manual_commit = False

    # ─── lifecycle ────────────────────────────────────────────────────────

    def _now(self) -> float:
        return asyncio.get_running_loop().time()

    async def _send(self, frame: dict) -> None:
        await self.outbox.send_json(frame)

    async def run(self) -> None:
        try:
            if not await self._handshake():
                return
            self._tasks.append(asyncio.create_task(self._receiver()))
            self._tasks.append(asyncio.create_task(self._asr_pump()))
            assert self.speaker is not None
            self._tasks.append(asyncio.create_task(self.speaker.run()))
            await self._greet()
            while not self.ended:
                item = await self.inbox.get()
                await self._dispatch(item)
        finally:
            await self._shutdown()

    async def _handshake(self) -> bool:
        try:
            raw = await asyncio.wait_for(self._transport.receive(), self.timings.hello_timeout)
        except asyncio.TimeoutError:
            self.close_code = 1008
            await self._send(proto.error_frame("fatal", "未收到 hello，连接已关闭"))
            return False
        if raw is None:
            return False
        try:
            hello = proto.parse_client_frame(raw) if isinstance(raw, str) else None
        except proto.ProtocolError:
            hello = None
        if not isinstance(hello, proto.HelloFrame):
            self.close_code = 1008
            await self._send(proto.error_frame("fatal", "首帧必须是 hello"))
            return False
        if hello.caps.sample_rate != proto.UPLINK_SAMPLE_RATE:
            self.close_code = 1008
            await self._send(proto.error_frame("fatal", "上行音频必须是 16 kHz PCM16"))
            return False
        if self._bridge.check_config is not None:
            try:
                self._bridge.check_config()
            except Exception as exc:
                await self._send(proto.error_frame("fatal", f"大模型配置错误：{exc}"))
                return False

        self.thread_id = (hello.thread_id or "").strip() or uuid4().hex
        self.user_info = dict(hello.user_info or {})
        self.elder_mode = bool(self.user_info.get("elder_mode"))
        self.half_duplex = not hello.caps.aec
        self.receipts = hello.caps.playback_receipts
        self._no_hear = NoHearLadder(elder_mode=self.elder_mode)

        speed = ELDER_TTS_SPEED if self.elder_mode and self._tts.capabilities.speed_control else 1.0
        self.cues = self._cue_factory(self._tts, speed)
        self.speaker = Speaker(
            outbox=self.outbox,
            arbiter=self.arbiter,
            tts=self._tts,
            timings=self.timings,
            notify=self._on_speaker_event,
            speed=speed,
            receipts=self.receipts,
        )

        await self._send(proto.session_frame(self.thread_id))
        try:
            self._asr_stream = await self._open_asr()
        except SpeechProviderError as exc:
            print(f"--- [Voice] ASR unavailable ({exc.error_class}) ---", flush=True)
            await self._send(proto.error_frame("fatal", "语音识别服务暂不可用，请改用文字输入"))
            return False
        return True

    async def _open_asr(self) -> AsrStream:
        hotwords = self._hotwords if self._asr.capabilities.hotwords else ()
        return await self._asr.open_stream(sample_rate=proto.UPLINK_SAMPLE_RATE, hotwords=hotwords)

    async def _greet(self) -> None:
        """Opening cue, or — on reconnect — the pending question again."""
        pending = await self._pending_from_checkpoint()
        turn = self._new_turn("system")
        if pending is not None:
            # Reconnect: session → facts → interrupt → the question again. The
            # question is not re-sent as ``text``: it is already in the history.
            self.pending_interrupt = pending
            await self._send_facts()
            await self._send({
                "type": "interrupt",
                "content": pending["question"],
                "kind": pending["kind"],
            })
            await self._speak_plan(plan_interrupt(pending["kind"], pending["question"]), turn)
        else:
            await self._speak_cue("opening", turn, terminal=True)

    async def _pending_from_checkpoint(self) -> dict | None:
        config = {"configurable": {"thread_id": self.thread_id}}
        try:
            snapshot = await self._bridge.get_state(config)
        except Exception as exc:  # pragma: no cover - checkpointer backend dependent
            print(f"--- [Voice] Unable to read thread state: {type(exc).__name__} ---", flush=True)
            return None
        pending = None
        for task in getattr(snapshot, "tasks", ()) or ():
            sub_state = getattr(task, "state", None)
            values = getattr(sub_state, "values", None)
            if isinstance(values, dict) and values.get("collected"):
                self.collected = dict(values["collected"])
                self.missing = list(values.get("missing_fields") or [])
            for item in getattr(task, "interrupts", ()) or ():
                value = getattr(item, "value", item)
                if isinstance(value, dict):
                    pending = {
                        "kind": str(value.get("kind") or "followup"),
                        "question": str(value.get("question") or ""),
                    }
                else:
                    pending = {"kind": "followup", "question": str(value)}
        return pending

    async def _shutdown(self) -> None:
        self.ended = True
        for _, task in self._timers.values():
            task.cancel()
        self._timers.clear()
        if self._run_task is not None:
            await self._cancel_run()  # e.g. the socket dropped mid-turn
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._asr_stream is not None:
            try:
                await self._asr_stream.close()
            except Exception:
                pass
        await self.outbox.close(self.close_code)
        for trace in self.traces:
            if trace.outcome is None:
                trace.finish("superseded")

    # ─── helper tasks (post only) ─────────────────────────────────────────

    async def _receiver(self) -> None:
        while True:
            try:
                raw = await self._transport.receive()
            except Exception:
                raw = None
            if raw is None:
                await self.inbox.put(("disconnected",))
                return
            if isinstance(raw, (bytes, bytearray)):
                await self._on_audio(bytes(raw))
                continue
            try:
                frame = proto.parse_client_frame(raw)
            except proto.ProtocolError:
                await self._send(proto.error_frame("benign", "无法识别的控制帧"))
                continue
            if isinstance(frame, proto.PlaybackFrame):
                if self.speaker is not None:
                    self.speaker.on_playback(
                        frame.type, frame.turn_id, frame.sentence_id, frame.played_ms, self._now()
                    )
                continue
            await self.inbox.put(("frame", frame))

    async def _on_audio(self, data: bytes) -> None:
        try:
            _seq, _offset, pcm = proto.unpack_uplink_audio(data)
        except proto.ProtocolError:
            return
        # Half duplex: while the assistant speaks, the mic feeds nothing.
        if self.half_duplex and self.state == "speaking":
            return
        stream = self._asr_stream
        if stream is None:
            return
        try:
            await stream.send_audio(pcm)
        except SpeechProviderError:
            pass  # the pump sees the failure and reconnects

    async def _asr_pump(self) -> None:
        while True:
            stream = self._asr_stream
            if stream is None:
                return
            try:
                async for event in stream.events():
                    await self.inbox.put(("asr", event))
                return
            except SpeechProviderError as exc:
                if exc.error_class == "fatal" or self._asr_reconnects >= MAX_ASR_RECONNECTS:
                    await self.inbox.put(("asr_failed", exc.error_class))
                    return
                self._asr_reconnects += 1
                try:
                    await stream.close()
                except Exception:
                    pass
                try:
                    self._asr_stream = await self._open_asr()
                except SpeechProviderError as reopen_exc:
                    await self.inbox.put(("asr_failed", reopen_exc.error_class))
                    return

    async def _on_speaker_event(self, kind: str, job: SpeechJob, info: dict) -> None:
        await self.inbox.put(("speaker", kind, job, info))

    def _set_timer(self, name: str, delay: float) -> None:
        self._cancel_timer(name)
        token = next(self._timer_tokens)

        async def fire() -> None:
            await asyncio.sleep(delay)
            await self.inbox.put(("timer", name, token))

        self._timers[name] = (token, asyncio.create_task(fire()))

    def _cancel_timer(self, *names: str) -> None:
        for name in names:
            entry = self._timers.pop(name, None)
            if entry is not None:
                entry[1].cancel()

    # ─── dispatch ─────────────────────────────────────────────────────────

    async def _dispatch(self, item: tuple) -> None:
        kind = item[0]
        if kind == "frame":
            await self._on_frame(item[1])
        elif kind == "asr":
            await self._on_asr(item[1])
        elif kind == "timer":
            name, token = item[1], item[2]
            entry = self._timers.get(name)
            if entry is None or entry[0] != token:
                return
            self._timers.pop(name, None)
            await self._on_timer(name)
        elif kind == "graph_event":
            if item[1] == self._run_token:
                await self._on_graph_event(item[2])
        elif kind == "graph_done":
            if item[1] == self._run_token:
                await self._on_graph_done(item[2])
        elif kind == "speaker":
            await self._on_speaker(item[1], item[2], item[3])
        elif kind == "asr_failed":
            print(f"--- [Voice] ASR stream lost ({item[1]}) ---", flush=True)
            await self._send(proto.error_frame("fatal", "语音识别连接中断，请改用文字输入"))
            await self._end_call("asr_failed")
        elif kind == "disconnected":
            self.ended = True
            self.end_reason = "disconnected"

    # ─── state helpers ────────────────────────────────────────────────────

    async def _set_state(self, value: CallState) -> None:
        if self.state == value:
            return
        self.state = value
        await self._send(proto.state_frame(value))

    async def _settle(self) -> None:
        """Pick the resting state once nothing is being said."""
        if self.state == "emergency" or self.ended:
            return
        if self.speaker is not None and not self.speaker.idle:
            return
        if self._run_task is not None:
            await self._set_state("thinking")
            return
        await self._set_state("listening")
        if not self._idle_prompted and not self._speech_active and not self._current_text():
            self._set_timer("idle_prompt", self.timings.idle_prompt)

    def _note_user_activity(self) -> None:
        """Any sign of the user resets the idle ladder."""
        self._idle_prompted = False
        self._cancel_timer("idle_prompt", "idle_end")

    def _new_turn(self, source: str) -> TurnTrace:
        trace = TurnTrace(turn_id=next(self._turn_ids), source=source)
        self.traces.append(trace)
        return trace

    def _finish_turn(self, trace: TurnTrace | None, outcome: str) -> None:
        if trace is not None and trace.finish(outcome):  # type: ignore[arg-type]
            print(trace.log_line(), flush=True)

    def _ensure_user_turn(self) -> TurnTrace:
        if self._user_turn is None:
            self._user_turn = self._new_turn("vad")
        return self._user_turn

    def _current_text(self) -> str:
        return "".join(self._segments) + self._partial

    def _reset_utterance(self) -> None:
        self._segments = []
        self._confidences = []
        self._partial = ""
        self._speech_active = False
        self._speech_started_at = None

    # ─── speaking ─────────────────────────────────────────────────────────

    async def _speak_cue(
        self,
        cue_id: str,
        trace: TurnTrace | None,
        *,
        terminal: bool,
        interruptible: bool = True,
        speak_mode: str = "cue",
    ) -> SpeechJob | None:
        assert self.cues is not None and self.speaker is not None
        cue = await self.cues.get(cue_id)
        if cue.pcm is None:
            await self._notify_degraded(trace)
            if terminal:
                self._finish_turn(trace, "done")
            return None
        if trace is not None and terminal:
            trace.speak_mode = speak_mode
        job = SpeechJob(
            turn_id=trace.turn_id if trace else 0,
            utterances=[Utterance(cue.text, cue.pcm)],
            trace=trace,
            interruptible=interruptible,
            cue=True,
            terminal=terminal,
            speak_mode=speak_mode,
        )
        return self.speaker.enqueue(job)

    async def _speak_plan(self, plan: SpeechPlan, trace: TurnTrace) -> None:
        trace.speak_mode = plan.speak_mode
        if plan.cue_id is not None:
            await self._speak_cue(plan.cue_id, trace, terminal=True, speak_mode=plan.speak_mode)
            return
        assert self.speaker is not None
        job = SpeechJob(
            turn_id=trace.turn_id,
            utterances=[Utterance(text) for text in plan.sentences],
            trace=trace,
            interruptible=plan.interruptible,
            speak_mode=plan.speak_mode,
        )
        self._last_spoken = job
        self.speaker.enqueue(job)

    async def _stop_speaking(self) -> SpeechJob | None:
        """Bump the generation, drop queued speech, tell the client to flush."""
        assert self.speaker is not None
        current = self.arbiter.current
        self.arbiter.bump()
        self.speaker.clear()
        if current is not None:
            await self._send(proto.tts_stop_frame(current.turn_id))
        return current

    async def _barge_in(self) -> None:
        current = self.arbiter.current
        if current is None or not current.interruptible:
            return
        await self._stop_speaking()
        if current.terminal:
            self._finish_turn(current.trace, "interrupted")
        await self._settle()

    async def _notify_degraded(self, trace: TurnTrace | None) -> None:
        if trace is not None:
            trace.degraded = True
        if not self._degraded_notified:
            self._degraded_notified = True
            await self._send(proto.error_frame("degraded", "语音播报暂不可用，请看屏幕上的内容"))

    async def _on_speaker(self, kind: str, job: SpeechJob, info: dict) -> None:
        trace = job.trace
        if kind == "speech_started":
            self._cancel_timer("idle_prompt")
            if trace is not None and trace.committed_at is not None:
                elapsed = int((self._now() - trace.committed_at) * 1000)
                if trace.first_sound_ms is None:
                    trace.first_sound_ms = elapsed
                if not job.cue and trace.first_content_ms is None:
                    trace.first_content_ms = elapsed
            if self.state != "emergency":
                await self._set_state("speaking")
            return
        # speech_done
        if trace is not None:
            trace.generated_ms += info.get("generated_ms", 0)
            trace.played_ms += info.get("played_ms", 0)
        if info.get("error"):
            await self._notify_degraded(trace)
        if job.terminal and (info.get("completed") or info.get("error")):
            self._finish_turn(trace, "done")
        await self._settle()

    # ─── inputs ───────────────────────────────────────────────────────────

    async def _on_frame(self, frame: BaseModel) -> None:
        if isinstance(frame, proto.ByeFrame):
            await self._end_call("bye")
        elif isinstance(frame, proto.TurnEndFrame):
            self._note_user_activity()
            was_speaking = self.state == "speaking"
            if was_speaking:
                await self._barge_in()  # a tap counts as an interruption
            # A tap that only meant "stop talking" is not a failed recognition.
            await self._commit(frame.source, quiet_if_empty=was_speaking)
        elif isinstance(frame, proto.InputTextFrame):
            text = redact_sensitive_text(frame.text).strip()
            if not text:
                return
            trace = self._new_turn("text")
            await self._send(proto.stt_final_frame(trace.turn_id, text))
            await self._on_user_text(text, trace)
        elif isinstance(frame, proto.UiActionFrame):
            await self._on_ui_action(frame)
        elif isinstance(frame, proto.HelloFrame):
            await self._send(proto.error_frame("benign", "hello 只能发送一次"))

    async def _on_ui_action(self, frame: proto.UiActionFrame) -> None:
        self._note_user_activity()
        if self.state == "speaking":
            await self._barge_in()  # any tap interrupts (never the safety line)
        if frame.kind == "emergency_dismiss":
            if self.state != "emergency":
                return
            self.state = "listening"
            await self._send(proto.state_frame("listening"))
            await self._speak_cue("emergency_resume", self._new_turn("ui"), terminal=True)
            return
        if self.state == "emergency":
            return
        if frame.kind == "confirm":
            if not self.pending_interrupt or self.pending_interrupt.get("kind") != "confirm":
                return
            trace = self._new_turn("ui")
            await self._send(proto.stt_final_frame(trace.turn_id, "对"))
            await self._on_user_text("对", trace)
            return
        # edit_fact: merge on screen now, then feed the correction to the graph.
        field = frame.field or ""
        if field not in _FACT_FIELDS:
            await self._send(proto.error_frame("benign", "未知的症状要点字段"))
            return
        value = frame.value
        if isinstance(value, list):
            value = [redact_sensitive_text(str(item)).strip() for item in value if str(item).strip()]
            spoken_value = "、".join(value)
        else:
            value = redact_sensitive_text(str(value or "")).strip()
            spoken_value = value
        if not spoken_value:
            return
        self.collected[field] = value
        self.missing = [name for name in self.missing if name != field]
        await self._send_facts()
        text = f"更正一下，{_SHORT_FACT_LABELS.get(field, field)}是{spoken_value}"
        trace = self._new_turn("ui")
        await self._send(proto.stt_final_frame(trace.turn_id, text))
        await self._on_user_text(text, trace)

    async def _on_asr(self, event: AsrEvent) -> None:
        # Half duplex: whatever the mic picked up while speaking is echo.
        if self.half_duplex and self.state == "speaking":
            return
        now = self._now()
        if event.kind == "speech_start":
            self._speech_active = True
            if self._speech_started_at is None:
                self._speech_started_at = now
            self._cancel_timer("endpoint")
            self._note_user_activity()
            self._ensure_user_turn()
            return
        if event.kind in ("partial", "final"):
            trace = self._ensure_user_turn()
            if self._speech_started_at is None:
                self._speech_started_at = now
            self._note_user_activity()
            if event.kind == "partial":
                self._partial = event.text
            else:
                if event.text:
                    self._segments.append(event.text)
                if event.confidence is not None:
                    self._confidences.append(event.confidence)
                self._partial = ""
            await self._send(proto.stt_partial_frame(trace.turn_id, self._current_text()))
            if self.state == "speaking":
                await self._maybe_barge_in(now)
            return
        if event.kind == "silence":
            self._speech_active = False
            text = self._current_text()
            caps = self._asr.capabilities
            # Without partials the text only arrives with the flush at commit.
            if (text.strip() or not caps.partials) and caps.endpoint_events and not self.manual_commit:
                # A server VAD already waited ``silence_lag``; don't wait twice.
                wait = endpoint_wait(text, self.timings, elder_mode=self.elder_mode)
                short_ok = (self.pending_interrupt or {}).get("kind") == "confirm" and is_affirmative_answer(text)
                # Without partials there is nothing to judge "unfinished" by.
                if short_ok or not caps.partials:
                    # A bare "对" is short but complete when a read-back is waiting.
                    wait = self.timings.elder_endpoint_min if self.elder_mode else self.timings.endpoint_min
                wait = max(0.0, wait - caps.silence_lag)
                self._ensure_user_turn().endpoint_wait_ms = int(wait * 1000)
                self._set_timer("endpoint", wait)

    async def _maybe_barge_in(self, now: float) -> None:
        if self.half_duplex or self._speech_started_at is None:
            return
        if now - self._speech_started_at < self.timings.barge_in_min_speech:
            return
        text = self._current_text()
        if meaningful_length(text) < 2 or is_backchannel(text):
            return
        if not self.arbiter.can_barge_in(now):
            return
        await self._barge_in()

    async def _commit(self, source: str, *, quiet_if_empty: bool = False) -> None:
        """A turn boundary: collect the utterance and hand it on."""
        self._cancel_timer("endpoint")
        trace = self._ensure_user_turn()
        trace.source = source
        start = self._now()
        stream = self._asr_stream
        if stream is not None:
            try:
                last = await asyncio.wait_for(stream.flush(), self.timings.flush_timeout)
            except (asyncio.TimeoutError, SpeechProviderError):
                last = None
            if last is not None and last.text:
                self._segments.append(last.text)
                self._partial = ""
                if last.confidence is not None:
                    self._confidences.append(last.confidence)
        if self._partial:
            self._segments.append(self._partial)
        text = "".join(self._segments).strip()
        confidence = min(self._confidences) if self._confidences else None
        self._reset_utterance()
        self._user_turn = None
        self._asr_reconnects = 0
        trace.asr_final_ms = int((self._now() - start) * 1000)
        trace.asr_confidence = confidence
        trace.committed_at = self._now()

        if self.state == "emergency":
            self._finish_turn(trace, "superseded")
            return
        low_confidence = (
            self._asr.capabilities.confidence
            and confidence is not None
            and confidence < LOW_CONFIDENCE
        )
        if meaningful_length(text) == 0 and quiet_if_empty:
            self._finish_turn(trace, "superseded")
            await self._settle()
            return
        if meaningful_length(text) == 0 or low_confidence:
            await self._not_heard(trace)
            return
        self._no_hear.reset()
        text = redact_sensitive_text(text)
        # A lone 嗯/好 while the assistant talks is a back-channel, not a turn —
        # unless a read-back is waiting for exactly that kind of "yes".
        if (
            source == "vad"
            and self.state == "speaking"
            and is_backchannel(text)
            and (self.pending_interrupt or {}).get("kind") != "confirm"
        ):
            self._finish_turn(trace, "superseded")
            return
        await self._send(proto.stt_final_frame(trace.turn_id, text))
        await self._on_user_text(text, trace)

    async def _not_heard(self, trace: TurnTrace) -> None:
        """Empty / low-confidence final: never enters the graph."""
        if self._run_task is not None:
            # The user already has an answer coming; ignore the noise quietly.
            self._finish_turn(trace, "superseded")
            return
        step = self._no_hear.next_step()
        if step == "push_to_talk" and not self.manual_commit:
            self.manual_commit = True
            self._cancel_timer("endpoint")
            await self._send(proto.error_frame(
                "degraded", "识别不太顺利，您说完后请点一下“说完了”按钮", action="push_to_talk"
            ))
        await self._speak_cue(step, trace, terminal=True)

    async def _on_user_text(self, text: str, trace: TurnTrace) -> None:
        if trace.committed_at is None:
            trace.committed_at = self._now()
        self._note_user_activity()
        if self.state == "speaking":
            await self._barge_in()

        shortcut = classify(text, age=self._user_age())
        if shortcut.kind == "emergency":
            if self.state == "emergency":
                self._finish_turn(trace, "superseded")
                return
            await self._take_over(trace, shortcut.emergency_flags)
            # Fall through: the graph still gets the utterance so the transcript,
            # the clinic's own gate and the card all agree.
        elif self.state == "emergency":
            self._finish_turn(trace, "superseded")
            return
        elif shortcut.kind == "exit":
            self._finish_turn(trace, "done")
            await self._end_call("exit")
            return
        elif shortcut.kind == "repeat":
            await self._repeat(trace)
            return

        if self._run_task is not None:
            # Committed too early: the running turn is not cancelled; this text
            # becomes the next input as soon as the run returns.
            self._buffered.append((text, trace))
            return
        await self._start_run(text, trace)

    async def _repeat(self, trace: TurnTrace) -> None:
        trace.repeat_count += 1
        last = self._last_spoken
        if last is None:
            await self._speak_cue("not_heard", trace, terminal=True)
            return
        assert self.speaker is not None
        trace.speak_mode = last.speak_mode
        job = SpeechJob(
            turn_id=trace.turn_id,
            utterances=[Utterance(u.text, u.pcm) for u in last.utterances],
            trace=trace,
            interruptible=last.interruptible,
            cue=last.cue,
            speak_mode=last.speak_mode,
        )
        self.speaker.enqueue(job)

    async def _take_over(self, trace: TurnTrace, flags: tuple[str, ...]) -> None:
        """CRITICAL red flag: stop everything, uninterruptible safety line, full screen."""
        current = await self._stop_speaking()
        if current is not None and current.terminal:
            self._finish_turn(current.trace, "interrupted")
        self._cancel_timer("filler", "idle_prompt", "idle_end", "endpoint")
        self.emergency_flags = flags or self.emergency_flags
        await self._set_state("emergency")
        await self._speak_cue("safety", trace, terminal=True, interruptible=False, speak_mode="safety")

    def _user_age(self) -> int | None:
        age = self.user_info.get("age")
        return age if isinstance(age, int) else None

    # ─── graph runs ───────────────────────────────────────────────────────

    async def _start_run(self, text: str, trace: TurnTrace) -> None:
        self._run_token += 1
        token = self._run_token
        self._run_turn = trace
        self._outcome = RunOutcome()
        self._lead = None
        self._lead_spoken = False
        if trace.committed_at is None:
            trace.committed_at = self._now()
        if self.state != "emergency":
            await self._set_state("thinking")
            self._set_timer("filler", self.timings.filler_after)
        # No-progress watchdog (re-armed by every graph event) + a hard cap.
        self._set_timer("graph_timeout", self.timings.graph_stall)
        self._set_timer("graph_deadline", self.timings.graph_max)
        self._run_task = asyncio.create_task(self._run_graph(text, token))

    async def _run_graph(self, text: str, token: int) -> None:
        config = {"configurable": {"thread_id": self.thread_id}}
        state = self._bridge.build_state(text, self.user_info, "voice")
        try:
            graph_input = await self._bridge.resolve_input(config, state, state, text)
            if graph_input is None:
                graph_input = state
            async for event in self._bridge.iter_events(
                graph_input, config, custom_types=VOICE_CUSTOM_TYPES
            ):
                await self.inbox.put(("graph_event", token, event))
            await self.inbox.put(("graph_done", token, None))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"--- [Voice] Graph run failed: {type(exc).__name__} ---", flush=True)
            await self.inbox.put(("graph_done", token, "error"))

    async def _cancel_run(self) -> None:
        """Cancel the graph run and close out the step it left pending."""
        task = self._run_task
        if task is None:
            return
        task.cancel()
        self._run_task = None
        self._run_token += 1  # late events of the cancelled run are ignored
        await asyncio.gather(task, return_exceptions=True)
        self.pending_interrupt = None
        if self._bridge.abandon_run is not None:
            try:
                await self._bridge.abandon_run({"configurable": {"thread_id": self.thread_id}})
            except Exception as exc:  # pragma: no cover - checkpointer dependent
                print(f"--- [Voice] Could not close out the cancelled run: {type(exc).__name__} ---", flush=True)

    async def _send_facts(self) -> None:
        self.facts_version += 1
        await self._send(proto.facts_frame(dict(self.collected), list(self.missing), self.facts_version))

    async def _on_graph_event(self, event: dict) -> None:
        event_type = event.get("type")
        if self._run_task is not None:
            self._set_timer("graph_timeout", self.timings.graph_stall)  # progress
        if event_type in _FORWARDED_EVENTS:
            await self._send(dict(event))
            if event_type == "node_start" and event.get("node") == "conclude":
                self._lead = LeadCutter()
            elif event_type == "text" and self._lead is not None and not self._lead.done:
                await self._maybe_speak_lead(str(event.get("content") or ""))
            if event_type == "card":
                payload = event.get("payload") or {}
                if payload.get("type") == "clinic_recommendation":
                    data = dict(payload.get("data") or {})
                    self.recommendation = data
                    self._outcome.recommendation = data
                    if data.get("urgency") == "emergency" and self.state != "emergency":
                        assert self._run_turn is not None
                        await self._take_over(self._run_turn, ())
            elif event_type == "node_start" and event.get("node") in _HANDOFF_NODES:
                self._outcome.handed_off = True
        elif event_type == "interrupt":
            kind = str(event.get("kind") or "followup")
            question = str(event.get("content") or "")
            self._outcome.interrupt_kind = kind
            self._outcome.interrupt_question = question
            self.pending_interrupt = {"kind": kind, "question": question}
            await self._send({"type": "interrupt", "content": question, "kind": kind})
        elif event_type == "facts":
            self.collected = dict(event.get("collected") or {})
            self.missing = list(event.get("missing") or [])
            await self._send_facts()
        elif event_type == "error":
            self._outcome.error = "graph"
            await self._send(proto.error_frame("transient", "抱歉，处理出了点问题"))
        # "finish" is implied by graph_done.

    async def _maybe_speak_lead(self, chunk: str) -> None:
        """Speak the conclusion's first sentence as soon as it is complete."""
        assert self._lead is not None
        plan = self._lead.feed(chunk)
        if plan is None or plan.speak_mode != "conclusion":
            return  # undecided, or no usable lead → the card's summary later
        if self.state == "emergency" or self._buffered or self._run_turn is None:
            return
        if self._speech_active and self._current_text().strip():
            return  # the user is talking; the screen has it
        self._lead_spoken = True
        await self._speak_plan(plan, self._run_turn)

    async def _on_graph_done(self, error: str | None) -> None:
        self._run_task = None
        self._cancel_timer("filler", "graph_timeout", "graph_deadline")
        trace = self._run_turn
        outcome = self._outcome
        self._run_turn = None
        assert trace is not None
        if outcome.interrupt_kind is None:
            self.pending_interrupt = None

        if self.state == "emergency":
            # Nothing but the safety line is spoken; buffered text still reaches
            # the graph so the record is complete.
            if trace.speak_mode != "safety":
                trace.speak_mode = "skipped"
                self._finish_turn(trace, "done")
            if self._buffered:
                await self._run_buffered()
            return

        if error or outcome.error:
            trace.error_class = "transient"
            self._finish_turn(trace, "error")
            self._buffered.clear()
            await self._speak_cue("slow", self._new_turn("system"), terminal=True)
            return

        user_still_talking = self._speech_active and bool(self._current_text().strip())
        if self._buffered or user_still_talking:
            # The user kept talking after an early endpoint: what the run
            # produced stays on screen; the buffered words answer it instead.
            trace.speak_mode = "skipped"
            self._finish_turn(trace, "superseded")
            if self._buffered:
                await self._run_buffered()
            else:
                await self._settle()
            return

        if self._lead_spoken and outcome.interrupt_kind is None:
            # The conclusion was already spoken from the stream's first sentence.
            await self._settle()
            return
        await self._speak_plan(plan_for_outcome(outcome), trace)
        await self._settle()

    async def _run_buffered(self) -> None:
        texts = [text for text, _ in self._buffered]
        trace = self._buffered[-1][1]
        for _, earlier in self._buffered[:-1]:
            self._finish_turn(earlier, "superseded")
        self._buffered.clear()
        await self._start_run("，".join(texts), trace)

    # ─── timers ───────────────────────────────────────────────────────────

    async def _on_timer(self, name: str) -> None:
        if name == "endpoint":
            has_text = bool(self._current_text().strip()) or not self._asr.capabilities.partials
            if self.state != "emergency" and not self.manual_commit and has_text:
                await self._commit("vad")
        elif name == "filler":
            if (
                self._run_task is not None
                and self.state == "thinking"
                and self.speaker is not None
                and self.speaker.idle
                and not self._current_text()
            ):
                # Only long silent runs (such as conclude) get a prompt that the
                # answer is still coming; short turns stay silent while thinking.
                await self._speak_cue("filler_wait", self._run_turn, terminal=False)
            if self._run_task is not None:
                self._set_timer("filler", self.timings.filler_repeat)
        elif name in ("graph_timeout", "graph_deadline"):
            if self._run_task is None:
                return
            self._cancel_timer("filler", "graph_timeout", "graph_deadline")
            await self._cancel_run()
            trace = self._run_turn
            self._run_turn = None
            if trace is not None:
                trace.error_class = "stalled" if name == "graph_timeout" else "deadline"
                self._finish_turn(trace, "error")
            self._buffered.clear()
            if self.state != "emergency":
                await self._speak_cue("slow", self._new_turn("system"), terminal=True)
                await self._settle()
        elif name == "idle_prompt":
            if self.state == "listening" and self._run_task is None and not self._current_text():
                self._idle_prompted = True
                await self._speak_cue("still_there", self._new_turn("system"), terminal=True)
                self._set_timer("idle_end", self.timings.idle_end)
        elif name == "idle_end":
            if self.state in ("listening", "speaking") and self._run_task is None and not self._current_text():
                await self._end_call("idle")

    # ─── ending ───────────────────────────────────────────────────────────

    def build_summary(self) -> dict:
        return build_clinic_summary(
            user_info=self.user_info,
            collected=self.collected,
            recommendation=self.recommendation,
            started_at=self._started_at,
            ended_at=datetime.now(timezone.utc),
            emergency_flags=self.emergency_flags,
        )

    async def _end_call(self, reason: str) -> None:
        if self.ended:
            return
        self.end_reason = reason
        self.close_code = 1000 if reason in ("bye", "exit", "idle") else 1011
        if self._run_task is not None:
            await self._cancel_run()
            self._finish_turn(self._run_turn, "superseded")
        self._cancel_timer("endpoint", "filler", "graph_timeout", "graph_deadline", "idle_prompt", "idle_end")
        current = await self._stop_speaking()
        if current is not None and current.terminal:
            self._finish_turn(current.trace, "interrupted")
        await self._send(proto.summary_frame(self.build_summary()))
        goodbye = {"exit": "goodbye", "idle": "idle_goodbye"}.get(reason)
        if goodbye is not None:
            job = await self._speak_cue(goodbye, self._new_turn("system"), terminal=True, interruptible=False)
            if job is not None:
                try:
                    await asyncio.wait_for(job.done.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    pass
        self.ended = True


# ─── Summary card ─────────────────────────────────────────────────────────────

SUMMARY_DISCLAIMER = "本小结由预问诊助手根据对话整理，仅供就诊参考，不能代替医生诊断。"


def build_clinic_summary(
    *,
    user_info: dict,
    collected: dict,
    recommendation: dict | None,
    started_at: datetime,
    ended_at: datetime,
    emergency_flags: tuple[str, ...] = (),
) -> dict:
    """
    ``clinic_summary`` card data — deterministic, from ``collected`` and
    ``recommendation`` only (no LLM). Without a recommendation the call ended
    before a conclusion: status ``incomplete`` and only the collected facts.
    """
    facts = []
    for field, label in _FIELD_LABELS.items():
        value = collected.get(field)
        if not value:
            continue
        rendered = "、".join(str(v) for v in value) if isinstance(value, list) else str(value)
        facts.append({"field": field, "label": label, "value": rendered})

    rec = recommendation or {}
    return {
        "status": "completed" if recommendation else "incomplete",
        "consultant": str(user_info.get("name") or "用户"),
        "started_at": started_at.isoformat(timespec="seconds"),
        "ended_at": ended_at.isoformat(timespec="seconds"),
        "duration_seconds": max(0, int((ended_at - started_at).total_seconds())),
        "chief_complaint": str(collected.get("chief_complaint") or ""),
        "facts": facts,
        "departments": list(rec.get("departments") or rec.get("department") or []),
        "urgency": rec.get("urgency"),
        "summary": str(rec.get("summary") or ""),
        "notes": list(rec.get("notes") or []),
        "emergency_flags": list(emergency_flags),
        "disclaimer": SUMMARY_DISCLAIMER,
    }


# ─── Starlette adapter ────────────────────────────────────────────────────────

class StarletteTransport:
    """Adapts a FastAPI/Starlette ``WebSocket`` to the ``Transport`` protocol."""

    def __init__(self, websocket: Any) -> None:
        self._ws = websocket

    async def receive(self) -> str | bytes | None:
        message = await self._ws.receive()
        if message.get("type") == "websocket.disconnect":
            return None
        if message.get("bytes") is not None:
            return message["bytes"]
        return message.get("text")

    async def send_text(self, text: str) -> None:
        await self._ws.send_text(text)

    async def send_bytes(self, data: bytes) -> None:
        await self._ws.send_bytes(data)

    async def close(self, code: int = 1000) -> None:
        await self._ws.close(code=code)


async def serve_voice_call(transport: Transport, **kwargs: Any) -> VoiceCall:
    call = VoiceCall(transport, **kwargs)
    await call.run()
    return call
