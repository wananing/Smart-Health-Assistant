"""
Wire protocol of the ``/api/voice`` WebSocket.

Control frames are JSON text messages with a ``type`` field; audio travels as
binary messages. Events shared with the SSE chat stream (``text``, ``card``,
``node_start``, ``node_end``, ``tool_start``, ``tool_end``, ``interrupt``)
keep exactly the SSE shape, so the frontend can reuse its chat handlers;
``interrupt`` additionally carries ``kind`` (``followup`` / ``confirm``).

Binary layouts (all little-endian):

    uplink   <u32 seq><u32 sample_offset><PCM16 mono 16 kHz, 20 ms = 320 samples>
    downlink <u32 turn_id><u32 sentence_id><u32 seq><PCM16 mono>

``sample_offset`` counts the samples sent before this frame. The downlink
sample rate is announced by the preceding ``tts.sentence`` frame. After
``tts.stop{turn_id}`` no further audio for that turn is ever sent.

The transport lives behind this module so a later move to WebRTC does not
touch the turn logic or the arbiter.
"""
from __future__ import annotations

import struct
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

UPLINK_SAMPLE_RATE = 16_000
UPLINK_FRAME_SAMPLES = 320  # 20 ms at 16 kHz
DEFAULT_TTS_SAMPLE_RATE = 24_000

UPLINK_HEADER = struct.Struct("<II")
DOWNLINK_HEADER = struct.Struct("<III")

# One uplink frame is nominally 640 bytes of PCM; tolerate up to one second.
MAX_UPLINK_PCM_BYTES = UPLINK_SAMPLE_RATE * 2

TurnSource = Literal["vad", "button", "text", "ui"]
StateValue = Literal["listening", "thinking", "speaking", "emergency"]
ErrorClass = Literal["fatal", "transient", "degraded", "benign"]


class ProtocolError(ValueError):
    """A client frame that does not follow this protocol."""


# ─── Uplink (client → server) ─────────────────────────────────────────────────

class _Frame(BaseModel):
    # Unknown extra keys are ignored so the client can add fields safely.
    model_config = ConfigDict(extra="ignore")


class ClientCaps(_Frame):
    aec: bool = False
    sample_rate: int = UPLINK_SAMPLE_RATE
    playback_receipts: bool = False


class HelloFrame(_Frame):
    type: Literal["hello"]
    thread_id: str | None = None
    user_info: dict[str, Any] = Field(default_factory=dict)
    caps: ClientCaps = Field(default_factory=ClientCaps)


class TurnEndFrame(_Frame):
    type: Literal["turn.end"]
    source: TurnSource = "button"


class InputTextFrame(_Frame):
    type: Literal["input.text"]
    text: str


class UiActionFrame(_Frame):
    type: Literal["ui.action"]
    kind: Literal["confirm", "edit_fact", "emergency_dismiss"]
    field: str | None = None
    value: Any = None


class PlaybackFrame(_Frame):
    type: Literal["playback.started", "playback.ended", "playback.interrupted"]
    turn_id: int
    sentence_id: int
    played_ms: int = 0


class ByeFrame(_Frame):
    type: Literal["bye"]


ClientFrame = Annotated[
    Union[HelloFrame, TurnEndFrame, InputTextFrame, UiActionFrame, PlaybackFrame, ByeFrame],
    Field(discriminator="type"),
]
_CLIENT_FRAME = TypeAdapter(ClientFrame)


def parse_client_frame(raw: str | bytes | dict) -> BaseModel:
    """Validate one JSON control frame. Raises ``ProtocolError`` on bad input."""
    try:
        if isinstance(raw, dict):
            return _CLIENT_FRAME.validate_python(raw)
        return _CLIENT_FRAME.validate_json(raw)
    except ValidationError as exc:
        # Never echo the payload itself: it may contain what the user typed.
        raise ProtocolError(f"invalid control frame ({exc.error_count()} error(s))") from exc


def unpack_uplink_audio(data: bytes) -> tuple[int, int, bytes]:
    """Split an uplink binary frame into ``(seq, sample_offset, pcm)``."""
    if len(data) < UPLINK_HEADER.size:
        raise ProtocolError("audio frame shorter than its header")
    pcm = data[UPLINK_HEADER.size:]
    if len(pcm) % 2:
        raise ProtocolError("PCM16 payload must have an even byte length")
    if len(pcm) > MAX_UPLINK_PCM_BYTES:
        raise ProtocolError("audio frame too large")
    seq, sample_offset = UPLINK_HEADER.unpack_from(data)
    return seq, sample_offset, pcm


def pack_uplink_audio(seq: int, sample_offset: int, pcm: bytes) -> bytes:
    """Client-side layout; used by tests and tooling."""
    return UPLINK_HEADER.pack(seq, sample_offset) + pcm


def pack_downlink_audio(turn_id: int, sentence_id: int, seq: int, pcm: bytes) -> bytes:
    return DOWNLINK_HEADER.pack(turn_id, sentence_id, seq) + pcm


def unpack_downlink_audio(data: bytes) -> tuple[int, int, int, bytes]:
    turn_id, sentence_id, seq = DOWNLINK_HEADER.unpack_from(data)
    return turn_id, sentence_id, seq, data[DOWNLINK_HEADER.size:]


# ─── Downlink (server → client) ───────────────────────────────────────────────

def session_frame(thread_id: str) -> dict:
    return {"type": "session", "thread_id": thread_id}


def state_frame(value: StateValue) -> dict:
    return {"type": "state", "value": value}


def stt_partial_frame(turn_id: int, text: str) -> dict:
    return {"type": "stt.partial", "turn_id": turn_id, "text": text}


def stt_final_frame(turn_id: int, text: str) -> dict:
    return {"type": "stt.final", "turn_id": turn_id, "text": text}


def facts_frame(collected: dict, missing: list[str], version: int) -> dict:
    return {"type": "facts", "collected": collected, "missing": missing, "version": version}


def tts_sentence_frame(
    turn_id: int,
    sentence_id: int,
    text: str,
    *,
    interruptible: bool,
    sample_rate: int,
    cue: bool,
) -> dict:
    # ``cue`` marks prompts that never enter the conversation history
    # (opening, fillers, "您还在吗"…); an addition to the pinned fields.
    return {
        "type": "tts.sentence",
        "turn_id": turn_id,
        "sentence_id": sentence_id,
        "text": text,
        "interruptible": interruptible,
        "sample_rate": sample_rate,
        "cue": cue,
    }


def tts_stop_frame(turn_id: int) -> dict:
    return {"type": "tts.stop", "turn_id": turn_id}


def error_frame(error_class: ErrorClass, content: str, **extra: Any) -> dict:
    return {"type": "error", "class": error_class, "content": content, **extra}


def summary_frame(data: dict) -> dict:
    return {"type": "summary", "payload": {"type": "clinic_summary", "data": data}}


__all__ = [
    "ByeFrame",
    "ClientCaps",
    "DEFAULT_TTS_SAMPLE_RATE",
    "DOWNLINK_HEADER",
    "HelloFrame",
    "InputTextFrame",
    "PlaybackFrame",
    "ProtocolError",
    "TurnEndFrame",
    "UPLINK_FRAME_SAMPLES",
    "UPLINK_HEADER",
    "UPLINK_SAMPLE_RATE",
    "UiActionFrame",
    "error_frame",
    "facts_frame",
    "pack_downlink_audio",
    "pack_uplink_audio",
    "parse_client_frame",
    "session_frame",
    "state_frame",
    "stt_final_frame",
    "stt_partial_frame",
    "summary_frame",
    "tts_sentence_frame",
    "tts_stop_frame",
    "unpack_downlink_audio",
    "unpack_uplink_audio",
]
