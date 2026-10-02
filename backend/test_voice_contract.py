"""
The shared /api/voice wire contract (contracts/voice-frames.json).

Every gateway test also checks each frame it sees against the contract
(FakeTransport + CallHarness.stop()); these tests pin the contract itself and
the checker, and keep the backend's frame models and builders in step with it.
The frontend side runs the same checks in mock_voice_server.cjs.
"""
import typing
import unittest

from voice import protocol as proto
from voice.contract import contract_violations, load_contract


class ContractCheckerTests(unittest.TestCase):
    def test_a_conforming_frame_has_no_violations(self):
        self.assertEqual(contract_violations({"type": "tts.stop", "turn_id": 3}, "downlink"), [])

    def test_each_kind_of_violation_is_reported(self):
        cases = {
            "unknown type": {"type": "tts.pause", "turn_id": 3},
            "extra field": {"type": "tts.stop", "turn_id": 3, "reason": "x"},
            "missing field": {"type": "tts.stop"},
            "wrong type": {"type": "tts.stop", "turn_id": "3"},
            "bool is not an integer": {"type": "tts.stop", "turn_id": True},
            "value outside the enum": {"type": "state", "value": "sleeping"},
        }
        for name, frame in cases.items():
            with self.subTest(name):
                self.assertNotEqual(contract_violations(frame, "downlink"), [])

    def test_optional_fields_may_be_absent_but_not_mistyped(self):
        self.assertEqual(contract_violations({"type": "error", "class": "fatal", "content": "x"}, "downlink"), [])
        self.assertNotEqual(
            contract_violations({"type": "error", "class": "fatal", "content": "x", "action": 1}, "downlink"), []
        )


class UplinkContractTests(unittest.TestCase):
    def test_uplink_types_match_the_backend_frame_models(self):
        backend_types = set()
        for model in typing.get_args(typing.get_args(proto.ClientFrame)[0]):
            backend_types.update(typing.get_args(model.model_fields["type"].annotation))
        self.assertEqual(set(load_contract()["uplink"]), backend_types)

    def test_every_uplink_example_conforms_and_parses_in_the_backend(self):
        for frame_type, spec in load_contract()["uplink"].items():
            with self.subTest(frame_type):
                example = spec["example"]
                self.assertEqual(example["type"], frame_type)
                self.assertEqual(contract_violations(example, "uplink"), [])
                proto.parse_client_frame(example)

    def test_the_list_value_of_an_edit_is_allowed(self):
        # associated_symptoms is edited as a list of strings.
        frame = {"type": "ui.action", "kind": "edit_fact", "field": "associated_symptoms", "value": ["恶心", "畏光"]}
        self.assertEqual(contract_violations(frame, "uplink"), [])
        proto.parse_client_frame(frame)


class DownlinkBuilderTests(unittest.TestCase):
    def test_every_frame_builder_conforms(self):
        frames = [
            proto.session_frame("t-1"),
            proto.state_frame("listening"),
            proto.stt_partial_frame(2, "我头"),
            proto.stt_final_frame(2, "我头疼"),
            proto.facts_frame({"chief_complaint": "头疼"}, ["duration"], 1),
            proto.tts_sentence_frame(2, 3, "头疼多久了？", interruptible=True, sample_rate=24000, cue=False),
            proto.tts_stop_frame(2),
            proto.error_frame("degraded", "已切换为手动模式", action="push_to_talk"),
            proto.summary_frame({"status": "completed"}),
        ]
        for frame in frames:
            with self.subTest(frame["type"]):
                self.assertEqual(contract_violations(frame, "downlink"), [])


if __name__ == "__main__":
    unittest.main()
