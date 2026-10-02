"""
Deterministic tests for the Volcengine framing (voice/providers/volc_protocol.py)
and the adapters built on it (voice/providers/volcengine.py).

Frames are hand-built byte by byte in the layout observed on the live service;
the adapters run against a scripted in-memory socket. No network, no key.
"""
import asyncio
import gzip
import json
import struct
import unittest
from types import SimpleNamespace

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedOK, InvalidStatus
from websockets.http11 import Response

from voice.asr import SpeechProviderError
from voice.providers import volc_protocol as vp
from voice.providers.volcengine import (
    EnergyEndpointer,
    VolcAsrProvider,
    VolcTtsProvider,
    classify_error_code,
    classify_http_status,
    speech_rate_for,
)


def _gz_json(obj) -> bytes:
    return gzip.compress(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def asr_server_frame(result: dict, seq: int, *, last: bool = False) -> bytes:
    """A FullServerResponse as the sauc endpoints send it (gzip JSON, sequence)."""
    body = _gz_json({"audio_info": {"duration": 100}, "result": result})
    flags = 0b0011 if last else 0b0001
    return bytes([0x11, 0x90 | flags, 0x11, 0x00]) + struct.pack(">iI", -seq if last else seq, len(body)) + body


def error_frame(code: int, message: str) -> bytes:
    body = json.dumps({"error": message}).encode()
    return bytes([0x11, 0xF0, 0x10, 0x00]) + struct.pack(">II", code, len(body)) + body


def tts_event_frame(event: int, payload: bytes = b"{}", session_id: str = "", connect_id: str = "",
                    msg_type: int = vp.FULL_SERVER_RESPONSE, serialization: int = 1) -> bytes:
    out = bytes([0x11, (msg_type << 4) | 0b0100, serialization << 4, 0x00]) + struct.pack(">i", event)
    if event in (vp.EVENT_CONNECTION_STARTED, vp.EVENT_CONNECTION_FINISHED):
        if connect_id:
            out += struct.pack(">I", len(connect_id)) + connect_id.encode()
    else:
        out += struct.pack(">I", len(session_id)) + session_id.encode()
    return out + struct.pack(">I", len(payload)) + payload


class FramingTests(unittest.TestCase):
    def test_asr_full_request_layout(self):
        frame = vp.encode_asr_full_request({"request": {"model_name": "bigmodel"}}, 1)
        self.assertEqual(frame[:4], bytes([0x11, 0x11, 0x11, 0x00]))
        seq, size = struct.unpack(">iI", frame[4:12])
        self.assertEqual((seq, size), (1, len(frame) - 12))
        self.assertEqual(json.loads(gzip.decompress(frame[12:])), {"request": {"model_name": "bigmodel"}})

    def test_asr_audio_layout_and_last_packet(self):
        pcm = b"\x01\x02" * 1600
        frame = vp.encode_asr_audio(pcm, 7)
        self.assertEqual(frame[:4], bytes([0x11, 0x21, 0x11, 0x00]))
        self.assertEqual(struct.unpack(">i", frame[4:8])[0], 7)
        self.assertEqual(gzip.decompress(frame[12:]), pcm)
        last = vp.encode_asr_audio(pcm, 8, last=True)
        self.assertEqual(last[1], 0x23)
        self.assertEqual(struct.unpack(">i", last[4:8])[0], -8)

    def test_decode_asr_partial_and_last(self):
        partial = vp.decode_frame(asr_server_frame({"text": "我头疼", "utterances": [{"text": "我头疼", "definite": False}]}, 3))
        self.assertEqual((partial.msg_type, partial.sequence, partial.is_last), (vp.FULL_SERVER_RESPONSE, 3, False))
        self.assertEqual(partial.json()["result"]["text"], "我头疼")
        last = vp.decode_frame(asr_server_frame({"text": "我头疼。"}, 9, last=True))
        self.assertTrue(last.is_last)
        self.assertEqual(last.sequence, -9)

    def test_decode_error_frame(self):
        frame = vp.decode_frame(error_frame(45000081, "waiting next packet timeout"))
        self.assertEqual((frame.msg_type, frame.error_code), (vp.ERROR_RESPONSE, 45000081))
        self.assertIn("timeout", frame.json()["error"])

    def test_tts_client_events(self):
        start = vp.encode_tts_event(vp.EVENT_START_CONNECTION)
        self.assertEqual(start, bytes([0x11, 0x14, 0x10, 0x00]) + struct.pack(">iI", 1, 2) + b"{}")
        session = vp.encode_tts_event(vp.EVENT_START_SESSION, {"a": 1}, "sid-1")
        self.assertEqual(struct.unpack(">i", session[4:8])[0], 100)
        self.assertEqual(struct.unpack(">I", session[8:12])[0], 5)
        self.assertEqual(session[12:17], b"sid-1")
        self.assertEqual(json.loads(session[21:]), {"a": 1})

    def test_decode_tts_server_events_and_audio(self):
        started = vp.decode_frame(tts_event_frame(vp.EVENT_CONNECTION_STARTED, connect_id="c-1"))
        self.assertEqual((started.event, started.connect_id, started.payload), (50, "c-1", b"{}"))
        bare = vp.decode_frame(tts_event_frame(vp.EVENT_CONNECTION_STARTED))
        self.assertEqual((bare.event, bare.payload), (50, b"{}"))
        audio = vp.decode_frame(tts_event_frame(
            vp.EVENT_TTS_RESPONSE, b"\x00\x01" * 10, "sid", msg_type=vp.AUDIO_ONLY_SERVER, serialization=0
        ))
        self.assertEqual((audio.msg_type, audio.event, audio.session_id), (vp.AUDIO_ONLY_SERVER, 352, "sid"))
        self.assertEqual(audio.payload, b"\x00\x01" * 10)
        self.assertIsNone(audio.json())

    def test_truncated_frames_raise(self):
        for data in (b"\x11", asr_server_frame({"text": "x"}, 1)[:10]):
            with self.assertRaises(vp.VolcFrameError):
                vp.decode_frame(data)

    def test_error_classes_and_speech_rate(self):
        self.assertEqual(classify_error_code(45000081), "transient")
        self.assertEqual(classify_error_code(55000031), "transient")
        self.assertEqual(classify_error_code(45000001), "fatal")
        self.assertEqual(classify_error_code(55000000), "fatal")  # resource/voice mismatch
        self.assertEqual(classify_http_status(401), "fatal")
        self.assertEqual(classify_http_status(503), "transient")
        self.assertEqual(speech_rate_for(0.85), -15)
        self.assertEqual(speech_rate_for(1.0), 0)
        self.assertEqual(speech_rate_for(0.1), -50)

    def test_energy_endpointer(self):
        vad = EnergyEndpointer(start_ms=40, silence_ms=100)
        loud = struct.pack("<h", 3000) * 320
        quiet = b"\x00\x00" * 320
        kinds = [e.kind for chunk in [loud, loud, loud, quiet, quiet, quiet, quiet, quiet, quiet] for e in vad.feed(chunk)]
        self.assertEqual(kinds, ["speech_start", "silence"])


class FakeSocket:
    """Scripted server: ``on_send(frame)`` may push replies onto the socket."""

    def __init__(self, on_send=None):
        self.sent: list[bytes] = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self._on_send = on_send

    async def send(self, data):
        if self.closed:
            raise ConnectionClosedOK(None, None)
        self.sent.append(data)
        if self._on_send:
            self._on_send(self, vp.decode_frame(data))

    def push(self, data):
        self.inbox.put_nowait(data)

    async def recv(self):
        item = await self.inbox.get()
        if item is None:
            raise ConnectionClosedOK(None, None)
        return item

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except ConnectionClosedOK:
            raise StopAsyncIteration

    async def close(self):
        self.closed = True
        self.inbox.put_nowait(None)


def _settings(**overrides):
    base = dict(
        api_key="k", app_id="", access_token="", resource_id="r", voice="v", sample_rate=24000,
        model="bigmodel", end_window_ms=600,
        endpoint="wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


async def _drain(stream, count, timeout=1.0):
    events = []
    agen = stream.events()
    for _ in range(count):
        events.append(await asyncio.wait_for(anext(agen), timeout))
    return events


class VolcAsrAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def _open(self, sockets, **settings):
        headers_seen = []

        async def connect(url, additional_headers=None, max_size=None):
            headers_seen.append(dict(additional_headers))
            return sockets.pop(0)

        provider = VolcAsrProvider(_settings(**settings), connect=connect)
        stream = await provider.open_stream(sample_rate=16000)
        return provider, stream, headers_seen

    async def test_partials_definite_finals_and_dedupe(self):
        ws = FakeSocket()
        _, stream, headers = await self._open([ws])
        self.assertEqual(headers[0]["X-Api-Key"], "k")
        request = json.loads(gzip.decompress(ws.sent[0][12:]))
        self.assertEqual(request["request"]["result_type"], "single")
        self.assertEqual(request["request"]["end_window_size"], 600)

        ws.push(asr_server_frame({"text": "我", "utterances": [{"text": "我", "definite": False, "end_time": 500}]}, 1))
        ws.push(asr_server_frame({"text": "我头疼", "utterances": [{"text": "我头疼", "definite": False, "end_time": 900}]}, 2))
        definite = {"text": "我头疼。", "utterances": [{"text": "我头疼。", "definite": True, "end_time": 1200}]}
        ws.push(asr_server_frame(definite, 3))
        ws.push(asr_server_frame(definite, 4))  # repeated definite is delivered once
        events = await _drain(stream, 5)
        self.assertEqual(
            [(e.kind, e.text) for e in events],
            [("speech_start", ""), ("partial", "我"), ("partial", "我头疼"), ("final", "我头疼。"), ("silence", "")],
        )
        # Nothing open → flush ends the session at once, without a server round trip.
        await stream.send_audio(b"\x00\x00" * 1600)
        self.assertIsNone(await stream.flush())
        self.assertTrue(ws.closed)
        await stream.close()

    async def test_flush_mid_utterance_sends_the_last_packet_and_returns_the_final(self):
        def server(sock, frame):
            if frame.msg_type == vp.AUDIO_ONLY_CLIENT and frame.is_last:
                sock.push(asr_server_frame(
                    {"text": "头疼三天了。", "utterances": [{"text": "头疼三天了。", "definite": True, "end_time": 900}]},
                    5, last=True,
                ))

        first, second = FakeSocket(server), FakeSocket(server)
        _, stream, _ = await self._open([first, second])
        await stream.send_audio(b"\x01\x00" * 1600)  # one 100 ms packet
        first.push(asr_server_frame({"text": "头疼三天", "utterances": [{"text": "头疼三天", "definite": False, "end_time": 800}]}, 1))
        await _drain(stream, 2)
        final = await stream.flush()
        self.assertEqual((final.kind, final.text), ("final", "头疼三天了。"))
        last = vp.decode_frame(first.sent[-1])
        self.assertTrue(last.is_last)
        self.assertLess(last.sequence, 0)
        self.assertTrue(first.closed)
        # The next audio opens a fresh session.
        await stream.send_audio(b"\x00\x00" * 1600)
        self.assertEqual(len(second.sent), 2)  # full request + one audio packet
        await stream.close()

    async def test_server_errors_are_classified(self):
        ws = FakeSocket()
        _, stream, _ = await self._open([ws])
        ws.push(error_frame(45000001, "bad request"))
        with self.assertRaises(SpeechProviderError) as ctx:
            await _drain(stream, 1)
        self.assertEqual(ctx.exception.error_class, "fatal")
        await stream.close()

    async def test_dropped_connection_is_transient(self):
        ws = FakeSocket()
        _, stream, _ = await self._open([ws])
        ws.push(None)
        with self.assertRaises(SpeechProviderError) as ctx:
            await _drain(stream, 1)
        self.assertEqual(ctx.exception.error_class, "transient")
        await stream.close()

    async def test_rejected_key_is_fatal(self):
        async def connect(*_args, **_kwargs):
            raise InvalidStatus(Response(401, "Unauthorized", Headers(), b'{"error":"Invalid X-Api-Key"}'))

        provider = VolcAsrProvider(_settings(), connect=connect)
        with self.assertRaises(SpeechProviderError) as ctx:
            await provider.open_stream(sample_rate=16000)
        self.assertEqual(ctx.exception.error_class, "fatal")
        self.assertNotIn("k", str(ctx.exception).split("HTTP")[0].replace("handshake", ""))

    async def test_nostream_uses_the_energy_endpointer(self):
        ws = FakeSocket()
        provider, stream, _ = await self._open([ws], endpoint="wss://x/api/v3/sauc/bigmodel_nostream")
        self.assertFalse(provider.capabilities.partials)
        request = json.loads(gzip.decompress(ws.sent[0][12:]))
        self.assertNotIn("result_type", request["request"])
        loud = struct.pack("<h", 3000) * 320
        for _ in range(5):
            await stream.send_audio(loud)
        for _ in range(40):
            await stream.send_audio(b"\x00\x00" * 320)
        events = await _drain(stream, 2)
        self.assertEqual([e.kind for e in events], ["speech_start", "silence"])
        await stream.close()


class VolcTtsAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _server(self, *, audio_chunks=3, fail_session=False):
        def server(sock, frame):
            if frame.event == vp.EVENT_START_CONNECTION:
                sock.push(tts_event_frame(vp.EVENT_CONNECTION_STARTED))
            elif frame.event == vp.EVENT_START_SESSION:
                if fail_session:
                    sock.push(error_frame(55000000, "resource ID is mismatched with speaker related resource"))
                else:
                    sock.push(tts_event_frame(vp.EVENT_SESSION_STARTED, session_id=frame.session_id))
            elif frame.event == vp.EVENT_FINISH_SESSION:
                for _ in range(audio_chunks):
                    sock.push(tts_event_frame(vp.EVENT_TTS_RESPONSE, b"\x00\x00" * 240, frame.session_id,
                                              msg_type=vp.AUDIO_ONLY_SERVER, serialization=0))
                sock.push(tts_event_frame(vp.EVENT_SESSION_FINISHED, session_id=frame.session_id))
        return server

    def _provider(self, sockets):
        async def connect(url, additional_headers=None, max_size=None):
            return sockets.pop(0)

        return VolcTtsProvider(_settings(endpoint="wss://x/api/v3/tts/bidirection"), connect=connect)

    async def test_a_sentence_streams_pcm_and_the_connection_is_reused(self):
        ws = FakeSocket(self._server())
        provider = self._provider([ws])
        chunks = [c async for c in provider.synthesize("您好。", speed=0.85)]
        self.assertEqual(len(chunks), 3)
        session = json.loads(vp.decode_frame(ws.sent[1]).payload)
        self.assertEqual(session["req_params"]["audio_params"], {"format": "pcm", "sample_rate": 24000, "speech_rate": -15})
        task = json.loads(vp.decode_frame(ws.sent[2]).payload)
        self.assertEqual(task["req_params"]["text"], "您好。")
        # Second sentence: same socket, no new StartConnection.
        again = [c async for c in provider.synthesize("请说。")]
        self.assertEqual(len(again), 3)
        self.assertEqual(sum(1 for f in ws.sent if vp.decode_frame(f).event == vp.EVENT_START_CONNECTION), 1)
        self.assertFalse(ws.closed)

    async def test_closing_early_drops_the_connection(self):
        ws = FakeSocket(self._server(audio_chunks=10))
        provider = self._provider([ws])
        gen = provider.synthesize("很长的一句话。")
        await anext(gen)
        await gen.aclose()  # barge-in
        self.assertTrue(ws.closed)
        self.assertEqual(provider._idle, [])

    async def test_session_errors_raise_with_a_class(self):
        ws = FakeSocket(self._server(fail_session=True))
        provider = self._provider([ws, FakeSocket(self._server(fail_session=True))])
        with self.assertRaises(SpeechProviderError) as ctx:
            async for _ in provider.synthesize("您好。"):
                pass
        self.assertEqual(ctx.exception.error_class, "fatal")


if __name__ == "__main__":
    unittest.main()
