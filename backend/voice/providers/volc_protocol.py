"""
Binary framing of Volcengine (火山引擎) openspeech v3 WebSockets — pure, no I/O.

Both the streaming ASR (``/api/v3/sauc/*``) and the bidirectional TTS
(``/api/v3/tts/bidirection``) share a 4-byte header::

    byte 0  version (4 bits, =1) | header size in 4-byte words (4 bits, =1)
    byte 1  message type (4 bits) | message-type-specific flags (4 bits)
    byte 2  serialization (4 bits: 0 raw, 1 JSON) | compression (4 bits: 0 none, 1 gzip)
    byte 3  reserved (0)

All integers after the header are big-endian. What follows depends on the
flags and the message type:

    flags & 0b0001  int32 sequence            (ASR; negative on the last packet)
    flags & 0b0010  "last packet" marker      (ASR)
    flags & 0b0100  int32 event number        (TTS), then for session-scoped
                    events a u32 length + session id, and for connection-level
                    server events a u32 length + connect id
    type 0b1111     u32 error code (instead of a sequence)
    always          u32 payload size + payload (gzip'd when compression=1)

Derived from the vendor's demo clients and verified against the live service
(see ``test_voice_live.py``); ``test_voice_volc_protocol.py`` pins the bytes.
"""
from __future__ import annotations

import gzip
import json
import struct
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 0b0001
HEADER_WORDS = 0b0001

# Message types
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_CLIENT = 0b0010
FULL_SERVER_RESPONSE = 0b1001
AUDIO_ONLY_SERVER = 0b1011
FRONTEND_RESULT_SERVER = 0b1100
ERROR_RESPONSE = 0b1111

# Flags
FLAG_NO_SEQUENCE = 0b0000
FLAG_POSITIVE_SEQUENCE = 0b0001
FLAG_LAST_NO_SEQUENCE = 0b0010
FLAG_NEGATIVE_SEQUENCE = 0b0011
FLAG_WITH_EVENT = 0b0100

SERIAL_RAW = 0b0000
SERIAL_JSON = 0b0001
COMPRESS_NONE = 0b0000
COMPRESS_GZIP = 0b0001

# TTS events (bidirectional protocol)
EVENT_START_CONNECTION = 1
EVENT_FINISH_CONNECTION = 2
EVENT_CONNECTION_STARTED = 50
EVENT_CONNECTION_FAILED = 51
EVENT_CONNECTION_FINISHED = 52
EVENT_START_SESSION = 100
EVENT_CANCEL_SESSION = 101
EVENT_FINISH_SESSION = 102
EVENT_SESSION_STARTED = 150
EVENT_SESSION_CANCELED = 151
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_USAGE_RESPONSE = 154
EVENT_TASK_REQUEST = 200
EVENT_TTS_SENTENCE_START = 350
EVENT_TTS_SENTENCE_END = 351
EVENT_TTS_RESPONSE = 352

# Events that carry no session id (connection scope).
_CONNECTION_EVENTS = {
    EVENT_START_CONNECTION,
    EVENT_FINISH_CONNECTION,
    EVENT_CONNECTION_STARTED,
    EVENT_CONNECTION_FAILED,
    EVENT_CONNECTION_FINISHED,
}
# Server connection events that carry a connect id instead.
_CONNECT_ID_EVENTS = {EVENT_CONNECTION_STARTED, EVENT_CONNECTION_FAILED, EVENT_CONNECTION_FINISHED}


class VolcFrameError(ValueError):
    """A frame that cannot be decoded."""


@dataclass
class VolcFrame:
    msg_type: int
    flags: int = FLAG_NO_SEQUENCE
    serialization: int = SERIAL_JSON
    compression: int = COMPRESS_NONE
    sequence: int | None = None
    is_last: bool = False
    event: int | None = None
    session_id: str = ""
    connect_id: str = ""
    error_code: int | None = None
    payload: bytes = b""

    def json(self) -> Any:
        """Decode a JSON payload (None when empty or not JSON)."""
        if not self.payload or self.serialization != SERIAL_JSON:
            return None
        try:
            return json.loads(self.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None


def _header(msg_type: int, flags: int, serialization: int, compression: int) -> bytes:
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | HEADER_WORDS,
            (msg_type << 4) | flags,
            (serialization << 4) | compression,
            0,
        ]
    )


# ─── ASR (sauc) client frames ────────────────────────────────────────────────

def encode_asr_full_request(request: dict, sequence: int = 1) -> bytes:
    """Opening frame: gzip'd JSON config with a positive sequence."""
    body = gzip.compress(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    return (
        _header(FULL_CLIENT_REQUEST, FLAG_POSITIVE_SEQUENCE, SERIAL_JSON, COMPRESS_GZIP)
        + struct.pack(">iI", sequence, len(body))
        + body
    )


def encode_asr_audio(pcm: bytes, sequence: int, *, last: bool = False) -> bytes:
    """Audio frame; the last one has the negative-sequence flag and ``-sequence``."""
    body = gzip.compress(pcm)
    flags = FLAG_NEGATIVE_SEQUENCE if last else FLAG_POSITIVE_SEQUENCE
    seq = -abs(sequence) if last else sequence
    return (
        _header(AUDIO_ONLY_CLIENT, flags, SERIAL_JSON, COMPRESS_GZIP)
        + struct.pack(">iI", seq, len(body))
        + body
    )


# ─── TTS (bidirection) client frames ─────────────────────────────────────────

def encode_tts_event(event: int, payload: dict | bytes | None = None, session_id: str = "") -> bytes:
    """A FullClientRequest with an event number (and a session id when session-scoped)."""
    if payload is None:
        body = b"{}"
    elif isinstance(payload, bytes):
        body = payload
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    out = _header(FULL_CLIENT_REQUEST, FLAG_WITH_EVENT, SERIAL_JSON, COMPRESS_NONE)
    out += struct.pack(">i", event)
    if event not in _CONNECTION_EVENTS:
        sid = session_id.encode("utf-8")
        out += struct.pack(">I", len(sid)) + sid
    out += struct.pack(">I", len(body)) + body
    return out


# ─── Decoding (both services) ────────────────────────────────────────────────

class _Reader:
    def __init__(self, data: bytes, offset: int) -> None:
        self._data = data
        self.offset = offset

    def take(self, size: int) -> bytes:
        if self.offset + size > len(self._data):
            raise VolcFrameError("truncated frame")
        chunk = self._data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def i32(self) -> int:
        return struct.unpack(">i", self.take(4))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def sized(self) -> bytes:
        return self.take(self.u32())

    @property
    def remaining(self) -> int:
        return len(self._data) - self.offset


def decode_frame(data: bytes) -> VolcFrame:
    """Decode any server (or client) frame; gzip payloads are inflated."""
    if len(data) < 4:
        raise VolcFrameError("frame shorter than its header")
    header_bytes = (data[0] & 0x0F) * 4
    if header_bytes < 4 or header_bytes > len(data):
        raise VolcFrameError("bad header size")
    frame = VolcFrame(
        msg_type=data[1] >> 4,
        flags=data[1] & 0x0F,
        serialization=data[2] >> 4,
        compression=data[2] & 0x0F,
    )
    reader = _Reader(data, header_bytes)

    if frame.msg_type == ERROR_RESPONSE:
        frame.error_code = reader.u32()
    elif frame.flags & FLAG_POSITIVE_SEQUENCE:
        frame.sequence = reader.i32()
    frame.is_last = bool(frame.flags & FLAG_LAST_NO_SEQUENCE)

    if frame.flags & FLAG_WITH_EVENT:
        frame.event = reader.i32()
        if frame.event not in _CONNECTION_EVENTS:
            frame.session_id = reader.sized().decode("utf-8", "replace")
        elif frame.event in _CONNECT_ID_EVENTS and reader.remaining >= 8:
            frame.connect_id = reader.sized().decode("utf-8", "replace")

    if reader.remaining >= 4:
        payload = reader.sized()
    elif reader.remaining:
        raise VolcFrameError("truncated payload size")
    else:
        payload = b""
    if payload and frame.compression == COMPRESS_GZIP:
        try:
            payload = gzip.decompress(payload)
        except OSError as exc:
            raise VolcFrameError("bad gzip payload") from exc
    frame.payload = payload
    return frame
