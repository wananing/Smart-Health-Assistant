"""
火山引擎 (Volcengine) openspeech v3: streaming ASR (sauc bigmodel) and
bidirectional TTS. Verified live with an ``X-Api-Key`` (new console) key;
framing lives in ``volc_protocol.py``.

ASR — what the live service does (measured, see ``test_voice_live.py``):

* ``…/sauc/bigmodel_async`` (default) and ``…/sauc/bigmodel``: interim
  results about every 300 ms. With ``result_type=single`` each response
  carries only the utterance in progress; with ``end_window_size`` the server
  marks it ``definite`` once that much silence followed it — a server-side
  endpoint. No confidence score is returned.
* ``…/sauc/bigmodel_nostream``: no interim text at all; the transcript comes
  only after the last audio packet, and a lone one-character answer ("对")
  came back empty in every live try ("对的" was fine) — use it only if the
  streaming endpoints are unavailable. The adapter then runs a small energy
  endpointer (``EnergyEndpointer``) to produce ``speech_start`` / ``silence``,
  and every committed turn ends the session (``flush``) to get its text.
* The server drops a session after 8 s without audio (error 45000081), so a
  keepalive sends 200 ms of silence when the gateway sends nothing (muted
  mic, half duplex while speaking).
* Every committed turn ends the current ASR session (``flush`` sends the
  last packet and waits for the final); the next audio opens a new one. That
  bounds session length and gives each turn a clean transcript.

TTS: one session per sentence over a pooled connection, ``format=pcm`` at
the announced rate, ``speech_rate`` for elder mode. A generator closed early
(barge-in) closes its connection, so the vendor stops producing audio and
nothing stale can be forwarded.

Errors map onto the gateway's classes: HTTP 401/403/429 at the handshake and
request/config error codes → ``fatal``; dropped connections, timeouts and
server-busy codes → ``transient`` (the gateway reconnects within its budget).
Keys, audio and transcripts are never logged.
"""
from __future__ import annotations

import array
import asyncio
import math
import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from voice.asr import AsrCapabilities, AsrEvent, SpeechProviderError
from voice.providers import volc_protocol as vp
from voice.tts import TtsCapabilities

MAX_FRAME_BYTES = 10 * 1024 * 1024
OPEN_TIMEOUT = 10.0
RECV_TIMEOUT = 10.0

# Codes that are worth a retry; everything else is a request/config problem.
_TRANSIENT_CODES = {45000081, 55000031}


def classify_error_code(code: int | None) -> str:
    if code is None:
        return "transient"
    if code in _TRANSIENT_CODES:
        return "transient"
    # 550xxxxx are server-side; 55000000 is also what a resource/voice mismatch
    # returns, which retrying cannot fix.
    if code // 1_000_000 == 55 and code != 55_000_000:
        return "transient"
    return "fatal"


def classify_http_status(status: int | None) -> str:
    return "fatal" if status in (400, 401, 403, 429) else "transient"


def auth_headers(settings: Any) -> dict[str, str]:
    headers = {
        "X-Api-Resource-Id": settings.resource_id,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    if settings.api_key:
        headers["X-Api-Key"] = settings.api_key
    else:
        headers["X-Api-App-Key"] = settings.app_id
        headers["X-Api-Access-Key"] = settings.access_token
    return headers


Connect = Callable[..., Awaitable[Any]]


async def _connect(connect: Connect, url: str, headers: dict[str, str], what: str):
    try:
        return await asyncio.wait_for(
            connect(url, additional_headers=headers, max_size=MAX_FRAME_BYTES),
            OPEN_TIMEOUT,
        )
    except InvalidStatus as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise SpeechProviderError(
            f"{what} handshake rejected (HTTP {status})", error_class=classify_http_status(status)
        ) from exc
    except (OSError, asyncio.TimeoutError, WebSocketException) as exc:
        raise SpeechProviderError(f"{what} connection failed ({type(exc).__name__})") from exc


# ─── ASR ──────────────────────────────────────────────────────────────────────

class EnergyEndpointer:
    """
    Minimal RMS endpointer for the no-partials endpoint: ``speech_start`` after
    ``start_ms`` of voiced audio, ``silence`` after ``silence_ms`` unvoiced.
    """

    def __init__(self, *, sample_rate: int = 16_000, threshold: float = 500.0,
                 start_ms: int = 60, silence_ms: int = 600) -> None:
        self._rate = sample_rate
        self._threshold = threshold
        self._start_ms = start_ms
        self._silence_ms = silence_ms
        self._voiced_ms = 0.0
        self._unvoiced_ms = 0.0
        self.in_speech = False

    @staticmethod
    def rms(pcm: bytes) -> float:
        samples = array.array("h")
        samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
        if not samples:
            return 0.0
        return math.sqrt(sum(s * s for s in samples) / len(samples))

    def feed(self, pcm: bytes) -> list[AsrEvent]:
        duration = len(pcm) / 2 / self._rate * 1000
        voiced = self.rms(pcm) >= self._threshold
        events: list[AsrEvent] = []
        if voiced:
            self._voiced_ms += duration
            self._unvoiced_ms = 0.0
            if not self.in_speech and self._voiced_ms >= self._start_ms:
                self.in_speech = True
                events.append(AsrEvent("speech_start"))
        else:
            self._voiced_ms = 0.0
            if self.in_speech:
                self._unvoiced_ms += duration
                if self._unvoiced_ms >= self._silence_ms:
                    self.in_speech = False
                    self._unvoiced_ms = 0.0
                    events.append(AsrEvent("silence"))
        return events


_CLOSED = object()


class VolcAsrStream:
    PACKET_BYTES = 3_200          # 100 ms of 16 kHz PCM16 (vendor recommends 100–200 ms)
    KEEPALIVE_AFTER = 2.0         # seconds without audio before sending silence
    FLUSH_TIMEOUT = 1.2           # inside the gateway's own flush budget

    def __init__(self, provider: "VolcAsrProvider", *, sample_rate: int) -> None:
        self._provider = provider
        self._settings = provider.settings
        self._sample_rate = sample_rate
        self._queue: asyncio.Queue = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._ws: Any = None
        self._reader: asyncio.Task | None = None
        self._keepalive: asyncio.Task | None = None
        self._seq = 1
        self._packets = 0
        self._buffer = bytearray()
        self._last_sent = 0.0
        self._delivered: set[Any] = set()
        self._utterance_open = False
        self._flush_future: asyncio.Future | None = None
        self._flush_text: list[str] = []
        self._closed = False
        self._vad = EnergyEndpointer(sample_rate=sample_rate) if provider.mode == "nostream" else None

    # --- session lifecycle ------------------------------------------------
    def _request(self) -> dict:
        request: dict[str, Any] = {
            "model_name": self._settings.model or "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "show_utterances": True,
        }
        if self._provider.mode == "stream":
            request["result_type"] = "single"
            request["end_window_size"] = self._settings.end_window_ms
        return {
            "user": {"uid": "bigh-voice"},
            "audio": {"format": "pcm", "codec": "raw", "rate": self._sample_rate, "bits": 16, "channel": 1},
            "request": request,
        }

    async def _open_session(self) -> None:
        headers = auth_headers(self._settings)
        headers["X-Api-Request-Id"] = str(uuid.uuid4())
        ws = await _connect(self._provider.connect, self._settings.endpoint, headers, "ASR")
        try:
            await ws.send(vp.encode_asr_full_request(self._request(), 1))
        except ConnectionClosed as exc:
            raise SpeechProviderError("ASR connection closed during setup") from exc
        self._ws = ws
        self._seq = 2
        self._packets = 0
        self._delivered = set()
        self._utterance_open = False
        self._last_sent = time.monotonic()
        self._reader = asyncio.create_task(self._read(ws))

    async def open(self) -> None:
        await self._open_session()
        self._keepalive = asyncio.create_task(self._keep_alive())

    async def _drop_session(self) -> None:
        ws, self._ws = self._ws, None
        reader, self._reader = self._reader, None
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    # --- sending ------------------------------------------------------------
    async def _send_packet(self, pcm: bytes, *, last: bool = False) -> None:
        if self._ws is None:
            await self._open_session()
        try:
            await self._ws.send(vp.encode_asr_audio(pcm, self._seq, last=last))
        except ConnectionClosed as exc:
            await self._drop_session()
            raise SpeechProviderError("ASR connection closed") from exc
        self._seq += 1
        self._packets += 1
        self._last_sent = time.monotonic()

    async def send_audio(self, pcm: bytes) -> None:
        if self._closed:
            return
        if self._vad is not None:
            for event in self._vad.feed(pcm):
                self._queue.put_nowait(event)
        self._buffer.extend(pcm)
        if self._flush_future is not None:
            return  # the session is ending; this audio opens the next one
        async with self._lock:
            while len(self._buffer) >= self.PACKET_BYTES:
                chunk = bytes(self._buffer[: self.PACKET_BYTES])
                del self._buffer[: self.PACKET_BYTES]
                await self._send_packet(chunk)

    async def _keep_alive(self) -> None:
        silence = b"\x00\x00" * (self._sample_rate // 5)  # 200 ms
        while not self._closed:
            await asyncio.sleep(0.5)
            if self._ws is None or self._flush_future is not None:
                continue
            if time.monotonic() - self._last_sent < self.KEEPALIVE_AFTER:
                continue
            try:
                async with self._lock:
                    if self._ws is not None and self._flush_future is None:
                        await self._send_packet(silence)
            except SpeechProviderError:
                pass  # the reader reports the drop

    async def flush(self) -> AsrEvent | None:
        """End the current session and return whatever it had not delivered yet."""
        async with self._lock:
            if self._ws is None or (self._packets == 0 and not self._buffer):
                return None
            if self._provider.mode == "stream" and self._delivered and not self._utterance_open:
                # Everything said so far was already delivered as definite
                # finals (the usual server-endpointed commit): end the session
                # without waiting for the server. Without a delivered final
                # we cannot tell "nothing said" from "partial not here yet".
                self._buffer.clear()
                await self._drop_session()
                return None
            loop = asyncio.get_running_loop()
            self._flush_future = loop.create_future()
            self._flush_text = []
            tail = bytes(self._buffer) or b"\x00\x00" * (self._sample_rate // 50)
            self._buffer.clear()
            future = self._flush_future
            try:
                await self._send_packet(tail, last=True)
            except SpeechProviderError:
                self._flush_future = None
                return None
        try:
            text = await asyncio.wait_for(future, self.FLUSH_TIMEOUT)
        except (asyncio.TimeoutError, SpeechProviderError):
            text = ""
        finally:
            self._flush_future = None
            await self._drop_session()
            if self._vad is not None:
                self._vad = EnergyEndpointer(sample_rate=self._sample_rate)
        return AsrEvent("final", text) if text else None

    # --- receiving ----------------------------------------------------------
    def _resolve_flush(self, error: SpeechProviderError | None = None) -> None:
        future = self._flush_future
        if future is None or future.done():
            return
        if error is not None and not self._flush_text:
            future.set_exception(error)
        else:
            future.set_result("".join(self._flush_text))

    def _handle_result(self, payload: Any, *, last: bool) -> None:
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return
        utterances = result.get("utterances") or []
        flushing = self._flush_future is not None
        if not utterances and last and result.get("text"):
            # nostream answers with a bare text on the last packet.
            utterances = [{"text": result["text"], "definite": True, "end_time": "last"}]
        for utterance in utterances:
            text = str(utterance.get("text") or "")
            if utterance.get("definite"):
                key = (utterance.get("start_time"), utterance.get("end_time"))
                if key in self._delivered or not text:
                    continue
                self._delivered.add(key)
                self._utterance_open = False
                if flushing:
                    self._flush_text.append(text)
                else:
                    self._queue.put_nowait(AsrEvent("final", text))
                    self._queue.put_nowait(AsrEvent("silence"))
            elif text and not flushing:
                if not self._utterance_open:
                    self._utterance_open = True
                    self._queue.put_nowait(AsrEvent("speech_start"))
                self._queue.put_nowait(AsrEvent("partial", text))
        if last and flushing and self._utterance_open and not self._flush_text:
            # Ended before the server marked it definite: keep the last hypothesis.
            text = str(result.get("text") or "")
            if text:
                self._flush_text.append(text)

    async def _read(self, ws: Any) -> None:
        try:
            async for message in ws:
                if not isinstance(message, (bytes, bytearray)):
                    continue
                try:
                    frame = vp.decode_frame(bytes(message))
                except vp.VolcFrameError:
                    continue
                if frame.msg_type == vp.ERROR_RESPONSE:
                    error = SpeechProviderError(
                        f"ASR error {frame.error_code}", error_class=classify_error_code(frame.error_code)
                    )
                    if self._flush_future is not None:
                        self._resolve_flush(error)
                    else:
                        self._queue.put_nowait(error)
                    return
                if frame.msg_type == vp.FULL_SERVER_RESPONSE:
                    self._handle_result(frame.json(), last=frame.is_last)
                if frame.is_last:
                    self._resolve_flush()
                    return
        except ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        if self._flush_future is not None:
            self._resolve_flush(SpeechProviderError("ASR connection closed"))
        elif not self._closed and self._ws is ws:
            self._ws = None
            self._queue.put_nowait(SpeechProviderError("ASR connection closed"))

    async def events(self) -> AsyncIterator[AsrEvent]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def close(self) -> None:
        self._closed = True
        if self._keepalive is not None:
            self._keepalive.cancel()
        await self._drop_session()
        self._queue.put_nowait(_CLOSED)


class VolcAsrProvider:
    name = "volcengine"

    def __init__(self, settings: Any, *, connect: Connect | None = None) -> None:
        self.settings = settings
        self.connect = connect or websockets.connect
        self.mode = "nostream" if "nostream" in settings.endpoint else "stream"
        if self.mode == "stream":
            self.capabilities = AsrCapabilities(
                partials=True,
                endpoint_events=True,
                hotwords=False,
                confidence=False,
                silence_lag=settings.end_window_ms / 1000,
            )
        else:
            self.capabilities = AsrCapabilities(
                partials=False, endpoint_events=True, hotwords=False, confidence=False, silence_lag=0.6
            )

    async def open_stream(self, *, sample_rate: int, hotwords: tuple[str, ...] = ()) -> VolcAsrStream:
        stream = VolcAsrStream(self, sample_rate=sample_rate)
        await stream.open()
        return stream


# ─── TTS ──────────────────────────────────────────────────────────────────────

def speech_rate_for(speed: float) -> int:
    """Map a speed factor onto the vendor's ``speech_rate`` (-50…100, 0 = normal).

    Measured: -15 makes a sentence ~1.2× longer, i.e. ≈0.85× speed.
    """
    return max(-50, min(100, round((speed - 1.0) * 100)))


class VolcTtsProvider:
    name = "volcengine"
    MAX_IDLE = 4

    def __init__(self, settings: Any, *, connect: Connect | None = None) -> None:
        self.settings = settings
        self.connect = connect or websockets.connect
        self.capabilities = TtsCapabilities(
            speed_control=True, sentence_duration=False, sample_rate=settings.sample_rate
        )
        self._idle: list[Any] = []

    async def _recv(self, ws: Any) -> vp.VolcFrame:
        try:
            message = await asyncio.wait_for(ws.recv(), RECV_TIMEOUT)
        except asyncio.TimeoutError as exc:
            raise SpeechProviderError("TTS response timeout") from exc
        except ConnectionClosed as exc:
            raise SpeechProviderError("TTS connection closed") from exc
        if not isinstance(message, (bytes, bytearray)):
            raise SpeechProviderError("TTS sent a non-binary frame")
        frame = vp.decode_frame(bytes(message))
        if frame.msg_type == vp.ERROR_RESPONSE:
            raise SpeechProviderError(
                f"TTS error {frame.error_code}", error_class=classify_error_code(frame.error_code)
            )
        if frame.event in (vp.EVENT_CONNECTION_FAILED, vp.EVENT_SESSION_FAILED):
            raise SpeechProviderError(f"TTS event {frame.event}", error_class="fatal")
        return frame

    async def _new_connection(self) -> Any:
        ws = await _connect(self.connect, self.settings.endpoint, auth_headers(self.settings), "TTS")
        try:
            await ws.send(vp.encode_tts_event(vp.EVENT_START_CONNECTION))
            frame = await self._recv(ws)
        except (SpeechProviderError, ConnectionClosed):
            await ws.close()
            raise
        if frame.event != vp.EVENT_CONNECTION_STARTED:
            await ws.close()
            raise SpeechProviderError(f"TTS unexpected event {frame.event}")
        return ws

    def _release(self, ws: Any) -> None:
        if len(self._idle) < self.MAX_IDLE:
            self._idle.append(ws)
        else:
            asyncio.ensure_future(ws.close())

    def _request(self, event: int, text: str | None, speed: float) -> dict:
        params: dict[str, Any] = {
            "speaker": self.settings.voice,
            "audio_params": {
                "format": "pcm",
                "sample_rate": self.capabilities.sample_rate,
                "speech_rate": speech_rate_for(speed),
            },
        }
        if text is not None:
            params["text"] = text
        return {"user": {"uid": "bigh-voice"}, "namespace": "BidirectionalTTS", "event": event, "req_params": params}

    async def _start_session(self, ws: Any, speed: float) -> str:
        session_id = str(uuid.uuid4())
        await ws.send(vp.encode_tts_event(vp.EVENT_START_SESSION, self._request(vp.EVENT_START_SESSION, None, speed), session_id))
        frame = await self._recv(ws)
        if frame.event != vp.EVENT_SESSION_STARTED:
            raise SpeechProviderError(f"TTS unexpected event {frame.event}")
        return session_id

    async def synthesize(self, text: str, *, speed: float = 1.0) -> AsyncIterator[bytes]:
        ws = self._idle.pop() if self._idle else await self._new_connection()
        clean = False
        try:
            try:
                session_id = await self._start_session(ws, speed)
            except (SpeechProviderError, ConnectionClosed):
                # A pooled connection may have gone stale; retry once on a fresh one.
                await ws.close()
                ws = await self._new_connection()
                session_id = await self._start_session(ws, speed)
            try:
                await ws.send(vp.encode_tts_event(
                    vp.EVENT_TASK_REQUEST, self._request(vp.EVENT_TASK_REQUEST, text, speed), session_id
                ))
                await ws.send(vp.encode_tts_event(vp.EVENT_FINISH_SESSION, None, session_id))
            except ConnectionClosed as exc:
                raise SpeechProviderError("TTS connection closed") from exc
            while True:
                frame = await self._recv(ws)
                if frame.msg_type == vp.AUDIO_ONLY_SERVER:
                    if frame.payload:
                        yield frame.payload
                elif frame.event == vp.EVENT_SESSION_FINISHED:
                    clean = True
                    return
        finally:
            if clean:
                self._release(ws)
            else:
                # Barge-in or failure: drop the connection so the vendor stops
                # producing audio for this sentence.
                try:
                    await ws.close()
                except Exception:
                    pass

    async def aclose(self) -> None:
        idle, self._idle = self._idle, []
        for ws in idle:
            try:
                await ws.close()
            except Exception:
                pass


def create_volcengine_asr(settings: Any) -> VolcAsrProvider:
    return VolcAsrProvider(settings)


def create_volcengine_tts(settings: Any) -> VolcTtsProvider:
    return VolcTtsProvider(settings)
