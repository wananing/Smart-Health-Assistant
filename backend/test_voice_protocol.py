"""Deterministic tests for the /api/voice wire protocol (voice/protocol.py)."""
import struct
import unittest

from voice import protocol as proto


class ControlFrameTests(unittest.TestCase):
    def test_hello_parses_caps_and_defaults(self):
        frame = proto.parse_client_frame(
            '{"type":"hello","thread_id":"t1","user_info":{"name":"甲"},'
            '"caps":{"aec":true,"sample_rate":16000,"playback_receipts":true}}'
        )
        self.assertIsInstance(frame, proto.HelloFrame)
        self.assertTrue(frame.caps.aec)
        self.assertTrue(frame.caps.playback_receipts)
        bare = proto.parse_client_frame({"type": "hello"})
        self.assertFalse(bare.caps.aec)
        self.assertEqual(bare.caps.sample_rate, 16000)

    def test_every_uplink_type_is_recognised(self):
        samples = [
            ({"type": "turn.end", "source": "button"}, proto.TurnEndFrame),
            ({"type": "input.text", "text": "头疼"}, proto.InputTextFrame),
            ({"type": "ui.action", "kind": "confirm"}, proto.UiActionFrame),
            ({"type": "ui.action", "kind": "edit_fact", "field": "duration", "value": "五天"}, proto.UiActionFrame),
            ({"type": "ui.action", "kind": "emergency_dismiss"}, proto.UiActionFrame),
            ({"type": "playback.started", "turn_id": 1, "sentence_id": 2}, proto.PlaybackFrame),
            ({"type": "playback.ended", "turn_id": 1, "sentence_id": 2, "played_ms": 900}, proto.PlaybackFrame),
            ({"type": "playback.interrupted", "turn_id": 1, "sentence_id": 2, "played_ms": 300}, proto.PlaybackFrame),
            ({"type": "bye"}, proto.ByeFrame),
        ]
        for raw, cls in samples:
            with self.subTest(frame=raw["type"]):
                self.assertIsInstance(proto.parse_client_frame(raw), cls)

    def test_bad_frames_raise_without_echoing_the_payload(self):
        for raw in ('{"type":"nope"}', '{"type":"turn.end","source":"mind"}', "not json",
                    '{"type":"ui.action","kind":"call_120"}', '{"type":"playback.ended","turn_id":"x"}'):
            with self.subTest(raw=raw):
                with self.assertRaises(proto.ProtocolError) as ctx:
                    proto.parse_client_frame(raw)
                self.assertNotIn("mind", str(ctx.exception))

    def test_downlink_frames_have_the_pinned_shapes(self):
        self.assertEqual(proto.state_frame("thinking"), {"type": "state", "value": "thinking"})
        self.assertEqual(proto.tts_stop_frame(3), {"type": "tts.stop", "turn_id": 3})
        self.assertEqual(
            proto.facts_frame({"a": 1}, ["severity"], 4),
            {"type": "facts", "collected": {"a": 1}, "missing": ["severity"], "version": 4},
        )
        self.assertEqual(
            proto.error_frame("degraded", "看屏幕"),
            {"type": "error", "class": "degraded", "content": "看屏幕"},
        )
        self.assertEqual(
            proto.summary_frame({"status": "incomplete"}),
            {"type": "summary", "payload": {"type": "clinic_summary", "data": {"status": "incomplete"}}},
        )
        sentence = proto.tts_sentence_frame(1, 2, "好的。", interruptible=True, sample_rate=24000, cue=True)
        self.assertEqual(
            set(sentence), {"type", "turn_id", "sentence_id", "text", "interruptible", "sample_rate", "cue"}
        )


class BinaryFrameTests(unittest.TestCase):
    def test_uplink_header_is_two_little_endian_u32(self):
        pcm = b"\x01\x00" * proto.UPLINK_FRAME_SAMPLES
        data = proto.pack_uplink_audio(7, 640, pcm)
        self.assertEqual(data[:8], struct.pack("<II", 7, 640))
        self.assertEqual(proto.unpack_uplink_audio(data), (7, 640, pcm))

    def test_downlink_header_is_three_little_endian_u32(self):
        data = proto.pack_downlink_audio(1, 2, 3, b"\x00\x00")
        self.assertEqual(data[:12], struct.pack("<III", 1, 2, 3))
        self.assertEqual(proto.unpack_downlink_audio(data), (1, 2, 3, b"\x00\x00"))

    def test_malformed_uplink_audio_is_rejected(self):
        for data in (b"\x00" * 4, proto.pack_uplink_audio(1, 0, b"\x00"),
                     proto.pack_uplink_audio(1, 0, b"\x00" * (proto.MAX_UPLINK_PCM_BYTES + 2))):
            with self.assertRaises(proto.ProtocolError):
                proto.unpack_uplink_audio(data)


if __name__ == "__main__":
    unittest.main()
