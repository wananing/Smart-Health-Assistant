"""
Shared deterministic doubles for the voice test-suite.

`FakeTransport` stands in for the WebSocket and records every outgoing frame
in order (JSON frames as dicts, audio as bytes). `ScriptedBridge` stands in
for the master graph: each graph run replays one scripted list of SSE-shaped
event dicts; an `asyncio.Event` inside a script pauses the run there until a
test sets it. Nothing here touches the network.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from langgraph.types import Command

from voice.cues import CueCache
from voice.gateway import GraphBridge, VoiceCall
from voice.protocol import DOWNLINK_HEADER, unpack_downlink_audio
from voice.providers.fake import FakeAsrProvider, FakeTtsProvider
from voice.turns import VoiceTimings

# Fast, deterministic timings: watchdogs that a test does not exercise are
# pushed far away; barge-in has no minimum speech or protection window.
TEST_TIMINGS = VoiceTimings(
    endpoint_min=0.02,
    endpoint_max=0.05,
    elder_endpoint_min=0.03,
    elder_endpoint_max=0.06,
    idle_prompt=60.0,
    idle_end=60.0,
    filler_after=60.0,
    graph_stall=5.0,
    graph_max=30.0,
    barge_in_min_speech=0.0,
    protect_window=0.0,
    hello_timeout=1.0,
    flush_timeout=0.2,
    playback_grace=0.05,
    audio_lead=10.0,
)


class FakeTransport:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue = asyncio.Queue()
        self.frames: list[Any] = []
        self.closed = False
        self.close_code: int | None = None

    # --- Transport -------------------------------------------------------
    async def receive(self):
        return await self.incoming.get()

    async def send_text(self, text: str) -> None:
        self.frames.append(json.loads(text))

    async def send_bytes(self, data: bytes) -> None:
        self.frames.append(bytes(data))

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code
        self.incoming.put_nowait(None)

    # --- test helpers ----------------------------------------------------
    def client(self, frame: dict) -> None:
        self.incoming.put_nowait(json.dumps(frame, ensure_ascii=False))

    def json_frames(self, frame_type: str | None = None) -> list[dict]:
        return [
            f for f in self.frames
            if isinstance(f, dict) and (frame_type is None or f.get("type") == frame_type)
        ]

    def audio_frames(self) -> list[tuple[int, int, int, int]]:
        """(index in frames, turn_id, sentence_id, seq) for every audio frame."""
        out = []
        for index, frame in enumerate(self.frames):
            if isinstance(frame, bytes) and len(frame) >= DOWNLINK_HEADER.size:
                turn_id, sentence_id, seq, _ = unpack_downlink_audio(frame)
                out.append((index, turn_id, sentence_id, seq))
        return out

    def spoken_texts(self) -> list[str]:
        return [f["text"] for f in self.json_frames("tts.sentence")]

    def states(self) -> list[str]:
        return [f["value"] for f in self.json_frames("state")]

    async def wait_for(self, predicate: Callable[[], Any], timeout: float = 3.0) -> Any:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            result = predicate()
            if result:
                return result
            await asyncio.sleep(0.002)
        raise AssertionError(f"condition not met; frames={[f for f in self.frames if isinstance(f, dict)]}")


class _Task:
    def __init__(self, interrupts=(), state=None):
        self.interrupts = interrupts
        self.state = state


class _Interrupt:
    def __init__(self, value):
        self.value = value
        self.id = "int-1"


class _Snapshot:
    def __init__(self, values=None, tasks=()):
        self.values = values or {}
        self.tasks = tasks


def pending_snapshot(value: Any, collected: dict | None = None) -> _Snapshot:
    """A checkpoint whose clinic subgraph is suspended on ``value``."""
    sub_state = _Snapshot(values={"collected": collected or {}, "missing_fields": []})
    return _Snapshot(values={"messages": ["old"]}, tasks=(_Task((_Interrupt(value),), sub_state),))


class ScriptedBridge:
    """A graph double: one scripted event list per run."""

    def __init__(self, runs: list[list[Any]] | None = None, *, snapshot: Any = None) -> None:
        self.runs = list(runs or [])
        self.inputs: list[str] = []
        self.graph_inputs: list[Any] = []
        self.snapshot = snapshot or _Snapshot()
        self.pending = False

    def bridge(self) -> GraphBridge:
        return GraphBridge(
            resolve_input=self._resolve,
            iter_events=self._iter,
            build_state=lambda text, user_info, channel: {
                "text": text, "user_info": user_info, "channel": channel,
            },
            get_state=self._get_state,
            check_config=None,
        )

    async def _get_state(self, _config):
        return self.snapshot

    async def _resolve(self, _config, turn_state, _full_state, text):
        self.inputs.append(text)
        resolved = Command(resume=text) if self.pending else turn_state
        self.graph_inputs.append(resolved)
        return resolved

    async def _iter(self, graph_input, config, *, custom_types=None):
        index = len(self.graph_inputs) - 1
        script = self.runs[index] if index < len(self.runs) else []
        self.pending = False
        for item in script:
            if isinstance(item, asyncio.Event):
                await item.wait()
                continue
            if isinstance(item, (int, float)):
                await asyncio.sleep(item)  # a slow step
                continue
            if item.get("type") == "interrupt":
                self.pending = True
            yield item
        yield {"type": "finish"}


def followup(question: str, kind: str = "followup") -> list[dict]:
    """The two events main._iter_agent_events yields for one interrupt."""
    return [
        {"type": "text", "content": question},
        {"type": "interrupt", "content": question, "kind": kind},
    ]


def recommendation_card(summary: str, urgency: str = "soon") -> dict:
    return {
        "type": "card",
        "payload": {
            "type": "clinic_recommendation",
            "data": {
                "summary": summary,
                "departments": ["呼吸内科"],
                "severity": "medium",
                "urgency": urgency,
                "notes": ["多喝温水"],
            },
        },
    }


def hello(*, aec: bool = True, receipts: bool = False, thread_id: str | None = None, **user_info) -> dict:
    frame = {
        "type": "hello",
        "user_info": {"name": "测试用户", **user_info},
        "caps": {"aec": aec, "sample_rate": 16000, "playback_receipts": receipts},
    }
    if thread_id:
        frame["thread_id"] = thread_id
    return frame


class CallHarness:
    """Runs one VoiceCall in the background against fakes."""

    def __init__(
        self,
        bridge: ScriptedBridge | GraphBridge,
        *,
        timings: VoiceTimings = TEST_TIMINGS,
        asr: FakeAsrProvider | None = None,
        tts: FakeTtsProvider | None = None,
    ) -> None:
        self.transport = FakeTransport()
        self.asr = asr or FakeAsrProvider()
        self.tts = tts or FakeTtsProvider(ms_per_char=2.0)
        graph_bridge = bridge.bridge() if isinstance(bridge, ScriptedBridge) else bridge
        self.call = VoiceCall(
            self.transport,
            bridge=graph_bridge,
            asr=self.asr,
            tts=self.tts,
            timings=timings,
            cue_factory=lambda provider, speed: CueCache(provider, speed=speed),
        )
        self.task: asyncio.Task | None = None

    async def start(self, hello_frame: dict | None = None, *, wait_listening: bool = True) -> None:
        self.transport.client(hello_frame or hello())
        self.task = asyncio.create_task(self.call.run())
        if wait_listening:
            await self.transport.wait_for(lambda: self.transport.json_frames("tts.sentence"))
            await self.wait_state("listening")

    async def wait_state(self, value: str) -> None:
        await self.transport.wait_for(lambda: self.call.state == value and self.transport.states()[-1:] == [value])

    @property
    def stream(self):
        return self.asr.streams[-1]

    async def say(self, text: str) -> None:
        """Speak one utterance and fall silent (server endpointing commits it)."""
        self.stream.push("speech_start")
        self.stream.push("partial", text)
        self.stream.push("silence")

    async def stop(self) -> None:
        if self.task is None:
            return
        if not self.task.done():
            self.transport.client({"type": "bye"})
            try:
                await asyncio.wait_for(self.task, 3.0)
            except asyncio.TimeoutError:
                self.task.cancel()
        self.task = None
