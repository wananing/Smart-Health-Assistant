"""
Deterministic event-sequence tests for the voice gateway (voice/gateway.py).

Scripted ASR/TTS (voice.providers.fake) and a scripted graph
(test_voice_fakes.ScriptedBridge); no network, no API key. Assertions are on
the ordered frame sequence the client receives. Cases with a real race
(barge-in vs. late TTS audio) are repeated to report a pass rate.
"""
import asyncio
import unittest

from test_voice_fakes import (
    CallHarness,
    ScriptedBridge,
    TEST_TIMINGS,
    followup,
    hello,
    pending_snapshot,
    recommendation_card,
)
from voice.asr import AsrCapabilities, SpeechProviderError
from voice.cues import CUE_TEXTS
from voice.providers.fake import FakeAsrProvider, FakeTtsProvider
from voice.render import DISCLAIMER, SCREEN_POINTER

QUESTION = "头疼有几天了呢？"
SAFETY = CUE_TEXTS["safety"]


class OpeningAndSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_first_then_the_opening_cue_with_its_audio(self):
        harness = CallHarness(ScriptedBridge())
        await harness.start()
        try:
            frames = harness.transport.frames
            self.assertEqual(frames[0]["type"], "session")
            self.assertTrue(frames[0]["thread_id"])

            sentence = harness.transport.json_frames("tts.sentence")[0]
            self.assertEqual(sentence["text"], CUE_TEXTS["opening"])
            self.assertTrue(sentence["cue"])
            self.assertTrue(sentence["interruptible"])
            self.assertEqual(sentence["sample_rate"], 24000)
            audio = harness.transport.audio_frames()
            self.assertTrue(audio)
            self.assertTrue(all(turn == sentence["turn_id"] for _, turn, _, _ in audio))
            self.assertEqual([seq for _, _, _, seq in audio], list(range(len(audio))))
            self.assertEqual(harness.transport.states()[:2], ["speaking", "listening"])
        finally:
            await harness.stop()

    async def test_hello_must_come_first(self):
        harness = CallHarness(ScriptedBridge())
        harness.transport.client({"type": "bye"})
        await harness.call.run()
        error = harness.transport.json_frames("error")[0]
        self.assertEqual(error["class"], "fatal")
        self.assertTrue(harness.transport.closed)

    async def test_fatal_asr_failure_at_start_is_reported_and_closes(self):
        asr = FakeAsrProvider(open_error=SpeechProviderError("auth", error_class="fatal"))
        harness = CallHarness(ScriptedBridge(), asr=asr)
        harness.transport.client(hello())
        await harness.call.run()
        self.assertEqual(harness.transport.json_frames("error")[0]["class"], "fatal")
        self.assertTrue(harness.transport.closed)


class FollowupTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_followup_is_shown_and_its_question_spoken(self):
        bridge = ScriptedBridge([
            [{"type": "node_start", "node": "clinic_node", "content": "进入预问诊模块"}, *followup(QUESTION)],
        ])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            await harness.say("我头疼")
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
            await harness.wait_state("listening")

            self.assertEqual(bridge.inputs, ["我头疼"])
            final = harness.transport.json_frames("stt.final")[0]
            self.assertEqual(final["text"], "我头疼")
            interrupt = harness.transport.json_frames("interrupt")[0]
            self.assertEqual(interrupt, {"type": "interrupt", "content": QUESTION, "kind": "followup"})
            # SSE-shaped events pass through unchanged.
            self.assertIn(
                {"type": "node_start", "node": "clinic_node", "content": "进入预问诊模块"},
                harness.transport.frames,
            )
            self.assertIn("thinking", harness.transport.states())
            trace = next(t for t in harness.call.traces if t.source == "vad")
            self.assertEqual(trace.speak_mode, "question")
            self.assertEqual(trace.outcome, "done")
            self.assertIsNotNone(trace.first_content_ms)
        finally:
            await harness.stop()

    async def test_asr_final_is_redacted_before_entering_the_graph(self):
        bridge = ScriptedBridge([followup(QUESTION)])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            await harness.say("我手机号13812345678，头疼")
            await harness.transport.wait_for(lambda: bridge.inputs)
            self.assertNotIn("13812345678", bridge.inputs[0])
            self.assertNotIn("13812345678", harness.transport.json_frames("stt.final")[0]["text"])
        finally:
            await harness.stop()


class BargeInTests(unittest.IsolatedAsyncioTestCase):
    async def _barge_in_once(self) -> None:
        bridge = ScriptedBridge([followup(QUESTION), followup("还有别的不舒服吗？")])
        # 8 chars × 30 ms = 240 ms of audio → several 40 ms chunks per sentence.
        tts = FakeTtsProvider(ms_per_char=30.0)
        harness = CallHarness(bridge, tts=tts)
        await harness.start()
        try:
            # Stall the question's synthesis after its first chunk.
            tts.gate = asyncio.Event()
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
            await harness.wait_state("speaking")
            question_turn = harness.transport.json_frames("tts.sentence")[-1]["turn_id"]

            harness.stream.push("speech_start")
            harness.stream.push("partial", "其实是肚子疼")
            await harness.transport.wait_for(lambda: harness.transport.json_frames("tts.stop"))

            # Late audio from the TTS vendor arrives after the stop …
            tts.gate.set()
            await asyncio.sleep(0.05)
            stop_index = next(
                i for i, f in enumerate(harness.transport.frames)
                if isinstance(f, dict) and f.get("type") == "tts.stop"
            )
            self.assertEqual(harness.transport.frames[stop_index]["turn_id"], question_turn)
            late = [
                index for index, turn, _, _ in harness.transport.audio_frames()
                if turn == question_turn and index > stop_index
            ]
            self.assertEqual(late, [], "audio of an interrupted turn leaked after tts.stop")
            self.assertGreater(harness.call.outbox.dropped_audio, 0, "no late audio was produced")

            trace = next(t for t in harness.call.traces if t.turn_id == question_turn)
            self.assertEqual(trace.outcome, "interrupted")

            # … and the interrupting words are the answer: resume the graph.
            harness.stream.push("silence")
            await harness.transport.wait_for(lambda: len(bridge.inputs) == 2)
            self.assertEqual(bridge.inputs[1], "其实是肚子疼")
            self.assertEqual(bridge.graph_inputs[1].resume, "其实是肚子疼")
        finally:
            await harness.stop()

    async def test_barge_in_drops_stale_generation_audio(self):
        runs, passed = 20, 0
        for attempt in range(runs):
            with self.subTest(attempt=attempt):
                await self._barge_in_once()
                passed += 1
        self.assertEqual(passed, runs, f"barge-in pass rate {passed}/{runs}")

    async def test_backchannel_does_not_interrupt(self):
        bridge = ScriptedBridge([followup(QUESTION)])
        tts = FakeTtsProvider(ms_per_char=2.0)
        harness = CallHarness(bridge, tts=tts)
        await harness.start()
        try:
            tts.gate = asyncio.Event()
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.wait_state("speaking")
            harness.stream.push("speech_start")
            harness.stream.push("partial", "嗯嗯")
            await asyncio.sleep(0.05)
            self.assertEqual(harness.transport.json_frames("tts.stop"), [])
            tts.gate.set()
        finally:
            await harness.stop()

    async def test_protection_window_blocks_an_early_barge_in(self):
        from dataclasses import replace

        bridge = ScriptedBridge([followup(QUESTION)])
        tts = FakeTtsProvider(ms_per_char=2.0)
        harness = CallHarness(bridge, tts=tts, timings=replace(TEST_TIMINGS, protect_window=5.0))
        await harness.start()
        try:
            tts.gate = asyncio.Event()
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.wait_state("speaking")
            harness.stream.push("speech_start")
            harness.stream.push("partial", "其实是肚子疼")
            await asyncio.sleep(0.05)
            self.assertEqual(harness.transport.json_frames("tts.stop"), [])
            tts.gate.set()
        finally:
            await harness.stop()

    async def test_half_duplex_ignores_the_mic_while_speaking(self):
        bridge = ScriptedBridge([followup(QUESTION)])
        tts = FakeTtsProvider(ms_per_char=2.0)
        harness = CallHarness(bridge, tts=tts)
        await harness.start(hello(aec=False))
        try:
            tts.gate = asyncio.Event()
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.wait_state("speaking")
            harness.stream.push("speech_start")
            harness.stream.push("partial", "这是回声不是用户")
            await asyncio.sleep(0.05)
            self.assertEqual(harness.transport.json_frames("tts.stop"), [])
            self.assertEqual(harness.transport.json_frames("stt.partial"), [])
            # A tap on "说完了" still interrupts, without a "没听清".
            harness.transport.client({"type": "turn.end", "source": "button"})
            await harness.transport.wait_for(lambda: harness.transport.json_frames("tts.stop"))
            await asyncio.sleep(0.02)
            self.assertNotIn(CUE_TEXTS["not_heard"], harness.transport.spoken_texts())
            tts.gate.set()
        finally:
            await harness.stop()


class EarlyEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_words_after_an_early_endpoint_are_buffered_and_the_followup_skipped(self):
        hold = asyncio.Event()
        bridge = ScriptedBridge([
            [hold, *followup(QUESTION)],
            followup("还有别的不舒服吗？"),
        ])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            await harness.say("我头疼")
            await harness.transport.wait_for(lambda: bridge.inputs == ["我头疼"])
            await harness.wait_state("thinking")

            # The user was not finished: the run is NOT cancelled; the new
            # words wait for it.
            await harness.say("三天了，挺严重的")
            await harness.transport.wait_for(
                lambda: any(f["text"] == "三天了，挺严重的" for f in harness.transport.json_frames("stt.final"))
            )
            self.assertEqual(bridge.inputs, ["我头疼"])

            hold.set()
            await harness.transport.wait_for(lambda: len(bridge.inputs) == 2)
            self.assertEqual(bridge.inputs[1], "三天了，挺严重的")
            self.assertEqual(bridge.graph_inputs[1].resume, "三天了，挺严重的")
            # The first run's question went on screen but was never spoken.
            self.assertIn(QUESTION, [f["content"] for f in harness.transport.json_frames("interrupt")])
            await harness.transport.wait_for(
                lambda: "还有别的不舒服吗？" in harness.transport.spoken_texts()
            )
            self.assertNotIn(QUESTION, harness.transport.spoken_texts())
            first = next(t for t in harness.call.traces if t.source == "vad")
            self.assertEqual((first.speak_mode, first.outcome), ("skipped", "superseded"))
        finally:
            await harness.stop()

    async def test_unfinished_sounding_partials_wait_longer(self):
        from voice.turns import endpoint_wait

        self.assertEqual(endpoint_wait("我头疼然后", TEST_TIMINGS, elder_mode=False), TEST_TIMINGS.endpoint_max)
        self.assertEqual(endpoint_wait("我头疼三天了", TEST_TIMINGS, elder_mode=False), TEST_TIMINGS.endpoint_min)
        self.assertEqual(endpoint_wait("头", TEST_TIMINGS, elder_mode=True), TEST_TIMINGS.elder_endpoint_max)


class EmergencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_red_flag_in_a_followup_answer_takes_over_before_the_graph_returns(self):
        hold = asyncio.Event()
        bridge = ScriptedBridge([
            followup(QUESTION),
            [hold, {"type": "text", "content": "紧急警报"}, recommendation_card("请立即拨打120", "emergency")],
        ])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            await harness.say("我头疼")
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
            await harness.wait_state("listening")

            await harness.say("现在胸口剧痛，喘不过气")
            # Take-over happens while the graph is still held.
            await harness.transport.wait_for(lambda: "emergency" in harness.transport.states())
            await harness.transport.wait_for(lambda: SAFETY in harness.transport.spoken_texts())
            self.assertFalse(hold.is_set())
            safety = next(f for f in harness.transport.json_frames("tts.sentence") if f["text"] == SAFETY)
            self.assertFalse(safety["interruptible"])
            # The answer still reaches the graph (as the resume value).
            self.assertEqual(bridge.graph_inputs[1].resume, "现在胸口剧痛，喘不过气")

            hold.set()
            await harness.transport.wait_for(lambda: harness.transport.json_frames("card"))
            await asyncio.sleep(0.05)
            # No second safety line, no follow-up while in emergency.
            self.assertEqual(harness.transport.spoken_texts().count(SAFETY), 1)
            self.assertEqual(harness.call.state, "emergency")
        finally:
            await harness.stop()

    async def test_the_safety_line_cannot_be_interrupted_and_voice_cannot_dismiss(self):
        bridge = ScriptedBridge([[recommendation_card("请立即拨打120", "emergency")], followup(QUESTION)])
        tts = FakeTtsProvider(ms_per_char=40.0)  # ~2 s of safety audio
        harness = CallHarness(bridge, tts=tts)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我突然剧烈胸痛，一直冒大汗"})
            await harness.transport.wait_for(lambda: SAFETY in harness.transport.spoken_texts())
            await asyncio.sleep(0.02)

            harness.stream.push("speech_start")
            harness.stream.push("partial", "我没事了你别说了")
            harness.transport.client({"type": "turn.end", "source": "button"})
            harness.transport.client({"type": "input.text", "text": "我没事，继续问诊"})
            await asyncio.sleep(0.1)
            self.assertEqual(harness.transport.json_frames("tts.stop"), [])
            self.assertEqual(harness.call.state, "emergency")
            self.assertEqual(len(bridge.inputs), 1, "voice/text must not leave emergency mode")

            harness.transport.client({"type": "ui.action", "kind": "emergency_dismiss"})
            await harness.transport.wait_for(lambda: harness.call.state != "emergency")
            self.assertEqual(harness.transport.states()[-1], "listening")
        finally:
            await harness.stop()

    async def _bye_in_emergency(self, *, while_safety_plays: bool) -> None:
        hold = asyncio.Event()  # the graph never answers before the hang-up
        bridge = ScriptedBridge([[hold, recommendation_card("请立即拨打120", "emergency")]])
        tts = FakeTtsProvider(ms_per_char=80.0 if while_safety_plays else 1.0)
        harness = CallHarness(bridge, tts=tts)
        await harness.start()
        t = harness.transport
        t.client({"type": "input.text", "text": "我突然剧烈胸痛，一直冒大汗"})
        await t.wait_for(lambda: SAFETY in t.spoken_texts())
        await harness.transport.wait_for(lambda: harness.call.state == "emergency")
        if while_safety_plays:
            self.assertIsNotNone(harness.call.arbiter.current, "safety line should still be playing")
            self.assertFalse(harness.call.arbiter.current.interruptible)
        else:
            await t.wait_for(lambda: harness.call.arbiter.current is None)

        t.client({"type": "bye"})
        await asyncio.wait_for(harness.task, 3.0)

        self.assertTrue(t.closed)
        self.assertEqual(t.close_code, 1000)
        summaries = t.json_frames("summary")
        self.assertEqual(len(summaries), 1)
        # The summary is the last JSON frame before the close.
        self.assertIs(t.json_frames()[-1], summaries[0])
        data = summaries[0]["payload"]["data"]
        self.assertEqual(data["status"], "incomplete")
        self.assertTrue(data["emergency_flags"])
        self.assertIn("疑似急性心梗", data["emergency_flags"])

    async def test_bye_in_emergency_sends_the_summary_before_closing(self):
        await self._bye_in_emergency(while_safety_plays=False)

    async def test_bye_during_the_safety_prompt_still_sends_the_summary(self):
        await self._bye_in_emergency(while_safety_plays=True)

    async def test_an_emergency_conclusion_also_takes_over(self):
        bridge = ScriptedBridge([[recommendation_card("建议立即急诊", "emergency")]])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我头晕得厉害"})
            await harness.transport.wait_for(lambda: SAFETY in harness.transport.spoken_texts())
            self.assertEqual(harness.call.state, "emergency")
        finally:
            await harness.stop()


class ConclusionSpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_summary_is_spoken_with_pointer_and_disclaimer(self):
        bridge = ScriptedBridge([[
            {"type": "text", "content": "## 分诊建议\n建议您到呼吸内科就诊…"},
            recommendation_card("建议尽快到呼吸内科就诊。"),
        ]])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我咳嗽三天了，中等"})
            await harness.transport.wait_for(lambda: DISCLAIMER in harness.transport.spoken_texts())
            spoken = harness.transport.spoken_texts()
            self.assertIn("建议尽快到呼吸内科就诊。", spoken)
            self.assertIn(SCREEN_POINTER, spoken)
            # The streamed body is on screen only.
            self.assertNotIn("建议您到呼吸内科就诊…", "".join(spoken))
        finally:
            await harness.stop()

    def _conclude_run(self, lead: str, hold: asyncio.Event, summary: str = "建议尽快到神经内科就诊。"):
        return [[
            {"type": "node_start", "node": "conclude", "content": "正在生成分诊建议…"},
            *({"type": "text", "content": piece} for piece in (lead[:4], lead[4:], "\n## 分诊建议\n", "建议您……")),
            hold,  # the structured summary call is still running
            {"type": "node_end", "node": "conclude"},
            recommendation_card(summary),
        ]]

    async def test_the_lead_sentence_is_spoken_before_the_card(self):
        hold = asyncio.Event()
        lead = "建议您今天去神经内科看看。"
        bridge = ScriptedBridge(self._conclude_run(lead, hold, summary=lead))
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "头疼三天了，很严重"})
            await harness.transport.wait_for(lambda: lead in harness.transport.spoken_texts())
            self.assertEqual(harness.transport.json_frames("card"), [], "spoken while the card is still pending")
            hold.set()
            await harness.transport.wait_for(lambda: harness.transport.json_frames("card"))
            await harness.wait_state("listening")
            spoken = harness.transport.spoken_texts()
            self.assertEqual(spoken.count(lead), 1, "not spoken again after the card")
            self.assertIn(DISCLAIMER, spoken)
            self.assertNotIn("建议您……", "".join(spoken))  # the body stays on screen
            trace = next(t for t in harness.call.traces if t.source == "text")
            self.assertEqual((trace.speak_mode, trace.outcome), ("conclusion", "done"))
        finally:
            await harness.stop()

    async def test_a_lead_failing_the_check_falls_back_to_the_card_summary(self):
        hold = asyncio.Event()
        bridge = ScriptedBridge(self._conclude_run("您得了偏头痛，要去神经内科。", hold))
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "头疼三天了，很严重"})
            await harness.transport.wait_for(
                lambda: "偏头痛" in "".join(f.get("content", "") for f in harness.transport.json_frames("text"))
            )
            await asyncio.sleep(0.05)
            self.assertFalse(any("偏头痛" in t for t in harness.transport.spoken_texts()))
            hold.set()
            await harness.transport.wait_for(lambda: "建议尽快到神经内科就诊。" in harness.transport.spoken_texts())
            card_index = next(i for i, f in enumerate(harness.transport.frames)
                              if isinstance(f, dict) and f.get("type") == "card")
            spoken_index = next(i for i, f in enumerate(harness.transport.frames)
                                if isinstance(f, dict) and f.get("text") == "建议尽快到神经内科就诊。")
            self.assertLess(card_index, spoken_index)
        finally:
            await harness.stop()

    async def test_a_conclusion_failing_the_pre_speech_check_is_screen_only(self):
        bridge = ScriptedBridge([[recommendation_card("您得了肺炎，需要住院治疗。")]])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我咳嗽三天了"})
            await harness.transport.wait_for(
                lambda: CUE_TEXTS["see_screen"] in harness.transport.spoken_texts()
            )
            self.assertFalse(any("肺炎" in text for text in harness.transport.spoken_texts()))
            # … but it is still on screen.
            card = harness.transport.json_frames("card")[0]
            self.assertIn("肺炎", card["payload"]["data"]["summary"])
            trace = next(t for t in harness.call.traces if t.source == "text")
            self.assertEqual(trace.speak_mode, "see_screen")
        finally:
            await harness.stop()

    async def test_a_handoff_is_answered_on_screen_with_one_spoken_line(self):
        bridge = ScriptedBridge([[
            {"type": "node_start", "node": "insurance_node", "content": "进入医保咨询模块"},
            {"type": "text", "content": "您的医保余额是…"},
        ]])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我医保还有多少钱"})
            await harness.transport.wait_for(lambda: CUE_TEXTS["handoff"] in harness.transport.spoken_texts())
        finally:
            await harness.stop()


class ConfirmAndFactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_facts_are_versioned_and_confirm_button_resumes_with_yes(self):
        readback = "我确认一下：头疼，持续三天，比较严重，对吗？"
        bridge = ScriptedBridge([
            [
                {"type": "facts", "collected": {"chief_complaint": "头疼", "duration": "三天", "severity": "严重"}, "missing": []},
                *followup(readback, kind="confirm"),
            ],
            [recommendation_card("建议到神经内科就诊。")],
        ])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "头疼三天了，很严重"})
            await harness.transport.wait_for(lambda: readback in harness.transport.spoken_texts())
            facts = harness.transport.json_frames("facts")[0]
            self.assertEqual(facts["version"], 1)
            self.assertEqual(facts["missing"], [])
            self.assertEqual(harness.transport.json_frames("interrupt")[0]["kind"], "confirm")

            harness.transport.client({"type": "ui.action", "kind": "confirm"})
            await harness.transport.wait_for(lambda: len(bridge.inputs) == 2)
            self.assertEqual(bridge.graph_inputs[1].resume, "对")
        finally:
            await harness.stop()

    async def test_editing_a_fact_updates_the_panel_and_feeds_a_correction(self):
        bridge = ScriptedBridge([
            [
                {"type": "facts", "collected": {"chief_complaint": "头疼", "duration": "三天"}, "missing": ["severity"]},
                *followup("我确认一下：头疼，持续三天，对吗？", kind="confirm"),
            ],
            followup("我确认一下：头疼，持续五天，对吗？", kind="confirm"),
        ])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "头疼三天"})
            await harness.transport.wait_for(lambda: harness.transport.json_frames("interrupt"))
            harness.transport.client({"type": "ui.action", "kind": "edit_fact", "field": "duration", "value": "五天"})
            await harness.transport.wait_for(lambda: len(bridge.inputs) == 2)
            facts = harness.transport.json_frames("facts")
            self.assertEqual(facts[-1]["collected"]["duration"], "五天")
            self.assertGreater(facts[-1]["version"], facts[0]["version"])
            self.assertIn("五天", bridge.inputs[1])
            self.assertIn("持续时间", bridge.inputs[1])
        finally:
            await harness.stop()


class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_re_speaks_the_pending_question(self):
        snapshot = pending_snapshot(
            {"kind": "followup", "question": "咳嗽有几天了？"},
            collected={"chief_complaint": "咳嗽"},
        )
        bridge = ScriptedBridge(snapshot=snapshot)
        harness = CallHarness(bridge)
        await harness.start(hello(thread_id="thread-reconnect"))
        try:
            self.assertEqual(harness.transport.frames[0], {"type": "session", "thread_id": "thread-reconnect"})
            self.assertEqual(harness.transport.spoken_texts()[0], "咳嗽有几天了？")
            self.assertNotIn(CUE_TEXTS["opening"], harness.transport.spoken_texts())
            interrupt = harness.transport.json_frames("interrupt")[0]
            self.assertEqual(interrupt["kind"], "followup")
            self.assertEqual(harness.transport.json_frames("facts")[0]["collected"], {"chief_complaint": "咳嗽"})
            # The next answer resumes the same thread.
            bridge.pending = True
            harness.transport.client({"type": "input.text", "text": "三天了"})
            await harness.transport.wait_for(lambda: bridge.inputs)
            self.assertEqual(bridge.graph_inputs[0].resume, "三天了")
        finally:
            await harness.stop()


class CloseCodeTests(unittest.IsolatedAsyncioTestCase):
    """1000 means "call over" to the client; anything else is a drop to reconnect from."""

    async def test_deliberate_ends_close_with_1000_after_the_summary(self):
        for ending in ({"type": "bye"}, {"type": "input.text", "text": "结束问诊"}):
            with self.subTest(ending=ending["type"]):
                harness = CallHarness(ScriptedBridge())
                await harness.start()
                harness.transport.client(ending)
                await asyncio.wait_for(harness.task, 3.0)
                self.assertEqual(harness.transport.close_code, 1000)
                self.assertTrue(harness.transport.json_frames("summary"))

    async def test_failures_do_not_close_with_1000(self):
        harness = CallHarness(ScriptedBridge())
        await harness.start()
        harness.stream.fail("fatal")
        await asyncio.wait_for(harness.task, 3.0)
        self.assertEqual(harness.transport.json_frames("error")[-1]["class"], "fatal")
        self.assertNotEqual(harness.transport.close_code, 1000)

        bad = CallHarness(ScriptedBridge())
        bad.transport.client({"type": "input.text", "text": "hi"})
        await bad.call.run()
        self.assertNotEqual(bad.transport.close_code, 1000)

    async def test_transient_asr_drops_reconnect_silently(self):
        harness = CallHarness(ScriptedBridge([followup(QUESTION)]))
        await harness.start()
        try:
            harness.stream.fail("transient")
            await harness.transport.wait_for(lambda: len(harness.asr.streams) == 2)
            await harness.say("我头疼")
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
            self.assertEqual(harness.transport.json_frames("error"), [])
        finally:
            await harness.stop()


class TapInterruptTests(unittest.IsolatedAsyncioTestCase):
    async def test_any_ui_action_tap_sends_tts_stop(self):
        bridge = ScriptedBridge([followup(QUESTION)])
        tts = FakeTtsProvider(ms_per_char=30.0)
        harness = CallHarness(bridge, tts=tts)
        await harness.start()
        try:
            tts.gate = asyncio.Event()
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.wait_state("speaking")
            # Not a pending confirm, so nothing reaches the graph — but it still interrupts.
            harness.transport.client({"type": "ui.action", "kind": "confirm"})
            await harness.transport.wait_for(lambda: harness.transport.json_frames("tts.stop"))
            self.assertEqual(bridge.inputs, ["我头疼"])
            tts.gate.set()
        finally:
            await harness.stop()


class ShortcutAndEndingTests(unittest.IsolatedAsyncioTestCase):
    async def test_exit_phrase_ends_the_call_without_the_graph(self):
        bridge = ScriptedBridge()
        harness = CallHarness(bridge)
        await harness.start()
        harness.transport.client({"type": "input.text", "text": "退出"})
        await asyncio.wait_for(harness.task, 3.0)
        self.assertEqual(bridge.inputs, [])
        summary = harness.transport.json_frames("summary")[0]
        self.assertEqual(summary["payload"]["type"], "clinic_summary")
        self.assertEqual(summary["payload"]["data"]["status"], "incomplete")
        self.assertIn(CUE_TEXTS["goodbye"], harness.transport.spoken_texts())
        self.assertTrue(harness.transport.closed)

    async def test_repeat_request_replays_the_last_sentence_locally(self):
        bridge = ScriptedBridge([followup(QUESTION)])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
            await harness.wait_state("listening")
            await harness.say("没听清，再说一遍")
            await harness.say("再说一遍")
            await harness.transport.wait_for(lambda: harness.transport.spoken_texts().count(QUESTION) == 2)
            self.assertEqual(bridge.inputs, ["我头疼"])
        finally:
            await harness.stop()

    async def test_bye_sends_a_summary_built_from_the_collected_facts(self):
        bridge = ScriptedBridge([[
            {"type": "facts", "collected": {"chief_complaint": "咳嗽", "duration": "三天"}, "missing": ["severity"]},
            *followup("咳得厉害吗？"),
        ]])
        harness = CallHarness(bridge)
        await harness.start()
        harness.transport.client({"type": "input.text", "text": "咳嗽三天"})
        await harness.transport.wait_for(lambda: harness.transport.json_frames("interrupt"))
        harness.transport.client({"type": "bye"})
        await asyncio.wait_for(harness.task, 3.0)
        data = harness.transport.json_frames("summary")[0]["payload"]["data"]
        self.assertEqual(data["status"], "incomplete")
        self.assertEqual(data["consultant"], "测试用户")
        self.assertEqual(data["chief_complaint"], "咳嗽")
        self.assertEqual([f["field"] for f in data["facts"]], ["chief_complaint", "duration"])
        self.assertTrue(harness.transport.closed)


class NoHearLadderTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_turns_escalate_to_push_to_talk(self):
        harness = CallHarness(ScriptedBridge())
        await harness.start()
        try:
            for expected in ("not_heard", "not_heard_button", "push_to_talk"):
                harness.transport.client({"type": "turn.end", "source": "button"})
                await harness.transport.wait_for(
                    lambda: CUE_TEXTS[expected] in harness.transport.spoken_texts()
                )
                await harness.wait_state("listening")
            error = [e for e in harness.transport.json_frames("error") if e.get("action") == "push_to_talk"]
            self.assertEqual(error[0]["class"], "degraded")
        finally:
            await harness.stop()

    async def test_after_the_third_miss_only_the_button_commits_a_turn(self):
        bridge = ScriptedBridge([followup(QUESTION)])
        harness = CallHarness(bridge)
        await harness.start()
        try:
            for expected in ("not_heard", "not_heard_button", "push_to_talk"):
                harness.transport.client({"type": "turn.end", "source": "button"})
                await harness.transport.wait_for(
                    lambda: CUE_TEXTS[expected] in harness.transport.spoken_texts()
                )
                await harness.wait_state("listening")
            self.assertTrue(harness.call.manual_commit)
            error = next(e for e in harness.transport.json_frames("error") if e.get("action") == "push_to_talk")
            self.assertIn("说完了", error["content"])
            self.assertNotIn("按住", error["content"] + CUE_TEXTS["push_to_talk"])

            # Silence no longer ends the turn; captions keep flowing.
            await harness.say("我头疼三天了")
            await harness.transport.wait_for(
                lambda: any(f["text"] == "我头疼三天了" for f in harness.transport.json_frames("stt.partial"))
            )
            await asyncio.sleep(TEST_TIMINGS.endpoint_max * 4)
            self.assertEqual(bridge.inputs, [])
            self.assertEqual(harness.transport.json_frames("stt.final"), [])

            # 说完了 commits it.
            harness.transport.client({"type": "turn.end", "source": "button"})
            await harness.transport.wait_for(lambda: bridge.inputs == ["我头疼三天了"])
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
            # Still manual for the rest of the call, and typed input still works.
            await harness.wait_state("listening")
            await harness.say("还有点恶心")
            await asyncio.sleep(TEST_TIMINGS.endpoint_max * 4)
            self.assertEqual(len(bridge.inputs), 1)
            harness.transport.client({"type": "input.text", "text": "还有点恶心"})
            await harness.transport.wait_for(lambda: len(bridge.inputs) == 2)
        finally:
            await harness.stop()

    async def test_low_confidence_finals_never_reach_the_graph(self):
        bridge = ScriptedBridge()
        harness = CallHarness(bridge)
        await harness.start()
        try:
            harness.stream.push("speech_start")
            harness.stream.push("final", "头疼", confidence=0.2)
            harness.stream.push("silence")
            await harness.transport.wait_for(lambda: CUE_TEXTS["not_heard"] in harness.transport.spoken_texts())
            self.assertEqual(bridge.inputs, [])
        finally:
            await harness.stop()

    async def test_elder_mode_starts_with_the_button_hint(self):
        harness = CallHarness(ScriptedBridge())
        await harness.start(hello(elder_mode=True))
        try:
            harness.transport.client({"type": "turn.end", "source": "button"})
            await harness.transport.wait_for(
                lambda: CUE_TEXTS["not_heard_button"] in harness.transport.spoken_texts()
            )
        finally:
            await harness.stop()


class WatchdogAndDegradationTests(unittest.IsolatedAsyncioTestCase):
    async def test_filler_while_thinking_and_timeout_apology(self):
        from dataclasses import replace

        hold = asyncio.Event()
        bridge = ScriptedBridge([[hold, *followup(QUESTION)]])
        timings = replace(TEST_TIMINGS, filler_after=0.02, graph_stall=0.3)
        harness = CallHarness(bridge, timings=timings)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.transport.wait_for(lambda: CUE_TEXTS["filler_wait"] in harness.transport.spoken_texts())
            await harness.transport.wait_for(lambda: CUE_TEXTS["slow"] in harness.transport.spoken_texts())
            trace = next(t for t in harness.call.traces if t.source == "text")
            self.assertEqual((trace.outcome, trace.error_class), ("error", "stalled"))
            hold.set()
            await asyncio.sleep(0.05)
            self.assertNotIn(QUESTION, harness.transport.spoken_texts())
        finally:
            await harness.stop()

    async def test_a_slow_but_progressing_run_is_not_cancelled(self):
        from dataclasses import replace

        progress = []
        for _ in range(8):
            progress += [0.08, {"type": "text", "content": "…"}]
        bridge = ScriptedBridge([[*progress, *followup(QUESTION)]])
        harness = CallHarness(bridge, timings=replace(TEST_TIMINGS, graph_stall=0.3))
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
            trace = next(t for t in harness.call.traces if t.source == "text")
            await harness.transport.wait_for(lambda: trace.outcome is not None)
            self.assertEqual(trace.outcome, "done")
            self.assertNotIn(CUE_TEXTS["slow"], harness.transport.spoken_texts())
        finally:
            await harness.stop()

    async def test_the_hard_cap_stops_a_run_that_never_ends(self):
        from dataclasses import replace

        endless = []
        for _ in range(100):
            endless += [0.05, {"type": "text", "content": "…"}]
        bridge = ScriptedBridge([endless])
        harness = CallHarness(bridge, timings=replace(TEST_TIMINGS, graph_stall=0.3, graph_max=0.5))
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.transport.wait_for(lambda: CUE_TEXTS["slow"] in harness.transport.spoken_texts())
            trace = next(t for t in harness.call.traces if t.source == "text")
            self.assertEqual((trace.outcome, trace.error_class), ("error", "deadline"))
        finally:
            await harness.stop()

    async def test_fillers_repeat_during_a_long_quiet_run(self):
        from dataclasses import replace

        progress = []
        for _ in range(10):
            progress += [0.05, {"type": "text", "content": "…"}]
        bridge = ScriptedBridge([[*progress, recommendation_card("建议尽快到神经内科就诊。")]])
        timings = replace(TEST_TIMINGS, filler_after=0.02, filler_repeat=0.15)
        harness = CallHarness(bridge, timings=timings)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "头疼三天了，很严重"})
            await harness.transport.wait_for(lambda: DISCLAIMER in harness.transport.spoken_texts())
            spoken = harness.transport.spoken_texts()
            # No quick acknowledgement any more; the long-wait prompt repeats.
            self.assertNotIn("好的。", spoken)
            self.assertGreaterEqual(spoken.count(CUE_TEXTS["filler_wait"]), 2)
        finally:
            await harness.stop()

    async def test_after_a_stall_the_same_call_takes_the_next_turn(self):
        from dataclasses import replace

        bridge = ScriptedBridge([[asyncio.Event()], followup(QUESTION)])
        harness = CallHarness(bridge, timings=replace(TEST_TIMINGS, graph_stall=0.2))
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.transport.wait_for(lambda: CUE_TEXTS["slow"] in harness.transport.spoken_texts())
            await harness.wait_state("listening")
            harness.transport.client({"type": "input.text", "text": "我头疼三天了"})
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
            self.assertEqual(bridge.inputs, ["我头疼", "我头疼三天了"])
            self.assertEqual(harness.call.thread_id, harness.transport.frames[0]["thread_id"])
        finally:
            await harness.stop()

    async def test_idle_prompt_then_polite_hang_up(self):
        from dataclasses import replace

        timings = replace(TEST_TIMINGS, idle_prompt=0.05, idle_end=0.1)
        harness = CallHarness(ScriptedBridge(), timings=timings)
        await harness.start()
        await asyncio.wait_for(harness.task, 3.0)
        spoken = harness.transport.spoken_texts()
        self.assertEqual(spoken.count(CUE_TEXTS["still_there"]), 1)
        self.assertIn(CUE_TEXTS["idle_goodbye"], spoken)
        self.assertTrue(harness.transport.json_frames("summary"))

    async def test_tts_outage_degrades_to_screen_only(self):
        bridge = ScriptedBridge([followup(QUESTION)])
        tts = FakeTtsProvider(fail=True)
        harness = CallHarness(bridge, tts=tts)
        await harness.start(wait_listening=False)
        try:
            await harness.transport.wait_for(lambda: harness.transport.json_frames("error"))
            self.assertEqual(harness.transport.json_frames("error")[0]["class"], "degraded")
            harness.transport.client({"type": "input.text", "text": "我头疼"})
            await harness.transport.wait_for(lambda: harness.transport.json_frames("interrupt"))
            self.assertEqual(harness.transport.audio_frames(), [])
        finally:
            await harness.stop()

    async def test_a_server_vad_lag_is_not_waited_twice(self):
        from dataclasses import replace

        asr = FakeAsrProvider(AsrCapabilities(partials=True, endpoint_events=True, silence_lag=10.0))
        bridge = ScriptedBridge([followup(QUESTION)])
        harness = CallHarness(bridge, asr=asr, timings=replace(TEST_TIMINGS, endpoint_min=5.0, endpoint_max=8.0))
        await harness.start()
        try:
            await harness.say("我头疼三天了")
            await harness.transport.wait_for(lambda: bridge.inputs, timeout=1.0)
        finally:
            await harness.stop()

    async def test_a_bare_yes_to_a_read_back_gets_the_short_wait(self):
        from dataclasses import replace

        readback = "我确认一下：头疼，持续三天，对吗？"
        bridge = ScriptedBridge([followup(readback, kind="confirm"), [recommendation_card("建议到神经内科就诊。")]])
        timings = replace(TEST_TIMINGS, endpoint_min=0.02, endpoint_max=5.0)
        harness = CallHarness(bridge, timings=timings)
        await harness.start()
        try:
            harness.transport.client({"type": "input.text", "text": "头疼三天"})
            await harness.transport.wait_for(lambda: readback in harness.transport.spoken_texts())
            await harness.wait_state("listening")
            await harness.say("对")  # 1 char: would normally get the 5 s "unfinished" wait
            await harness.transport.wait_for(lambda: len(bridge.inputs) == 2, timeout=1.0)
            self.assertEqual(bridge.inputs[1], "对")
        finally:
            await harness.stop()

    async def test_an_asr_without_partials_commits_on_silence_with_the_flushed_text(self):
        asr = FakeAsrProvider(AsrCapabilities(partials=False, endpoint_events=True))
        bridge = ScriptedBridge([followup(QUESTION)])
        harness = CallHarness(bridge, asr=asr)
        await harness.start()
        try:
            harness.stream.flush_text = "我头疼三天了"
            harness.stream.push("speech_start")
            harness.stream.push("silence")
            await harness.transport.wait_for(lambda: bridge.inputs == ["我头疼三天了"])
            self.assertEqual(harness.transport.json_frames("stt.final")[0]["text"], "我头疼三天了")
            trace = next(t for t in harness.call.traces if t.source == "vad")
            # No partial text to judge "unfinished" by: the short wait applies.
            self.assertEqual(trace.endpoint_wait_ms, int(TEST_TIMINGS.endpoint_min * 1000))
        finally:
            await harness.stop()

    async def test_asr_without_endpoint_events_relies_on_the_button(self):
        asr = FakeAsrProvider(AsrCapabilities(partials=True, endpoint_events=False))
        bridge = ScriptedBridge([followup(QUESTION)])
        harness = CallHarness(bridge, asr=asr)
        await harness.start()
        try:
            await harness.say("我头疼")
            await asyncio.sleep(0.1)
            self.assertEqual(bridge.inputs, [])
            harness.transport.client({"type": "turn.end", "source": "button"})
            await harness.transport.wait_for(lambda: bridge.inputs == ["我头疼"])
        finally:
            await harness.stop()


class PrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_nothing_the_user_said_is_printed(self):
        import contextlib
        import io

        bridge = ScriptedBridge([followup(QUESTION)])
        harness = CallHarness(bridge)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            await harness.start()
            await harness.say("我头疼得厉害")
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
            await harness.stop()
        self.assertNotIn("头疼", buffer.getvalue())
        self.assertIn("[Voice] turn=", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
