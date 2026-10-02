"""
Deterministic tests for the graph-run lifecycle of a voice call.

- A transient socket drop does not cancel the run: it finishes in the
  background (bounded), its result lands in the checkpoint and a reconnect
  picks it up.
- A run cancelled by the watchdog keeps the interview: the turn's Q&A reaches
  the parent history, so the next turn continues it.
- Committed user speech is never dropped: buffered turns run next even when
  the current run stalls or fails.

Real master graph + fake models where it matters; no network.
"""
import asyncio
import unittest
from dataclasses import replace
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from agents import clinic
from agents.clinic import SymptomFacts
from agents.graph import build_graph
from test_clinic_graph import _FakeKnowledgeBase, _FakeReactAgent, _exploding_llm
from test_voice_clinic import COMPLETE, RECOMMENDATION, _HangingThenAnsweringAgent, _patches, _Patched, main
from test_voice_fakes import TEST_TIMINGS, CallHarness, ScriptedBridge, followup, hello
from voice.cues import CUE_TEXTS

QUESTION = "头疼多久了呢？"


class _InterviewModel:
    """Structured-output fake: replays ``steps``; an asyncio.Event step waits on it first."""

    def __init__(self, steps, followup_text=QUESTION):
        self.steps = list(steps)
        self.calls = 0
        self.followup_text = followup_text

    def with_structured_output(self, schema):
        model = self

        class _Runnable:
            async def ainvoke(self, _messages):
                if schema is not clinic.InterviewStep:
                    return RECOMMENDATION
                model.calls += 1
                step = model.steps.pop(0) if model.steps else COMPLETE
                if isinstance(step, tuple):
                    gate, step = step
                    await gate.wait()
                missing = clinic._missing_fields(step.model_dump())
                return clinic.InterviewStep(facts=step, next_question=model.followup_text if missing else "")

        return _Runnable()

    async def ainvoke(self, _messages):
        return AIMessage(content=self.followup_text)


def _graph_patches(model, agent=None):
    return [
        patch("agents.clinic.get_chat_llm", return_value=model),
        patch("agents.clinic.get_agent_tools", return_value=[]),
        patch("agents.clinic.get_knowledge_base", return_value=_FakeKnowledgeBase()),
        patch("agents.clinic.create_react_agent", return_value=agent or _FakeReactAgent("建议您到神经内科就诊。")),
        patch("agents.router.get_chat_llm", side_effect=_exploding_llm),
        patch.object(main, "resolve_model_settings"),
    ]


async def _history(app, thread_id):
    snapshot = await app.aget_state({"configurable": {"thread_id": thread_id}})
    return [m.content for m in snapshot.values.get("messages", [])], snapshot


async def _pending_question(app, thread_id, timeout=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        snapshot = await app.aget_state({"configurable": {"thread_id": thread_id}})
        for task in snapshot.tasks:
            for item in task.interrupts:
                return item.value
        await asyncio.sleep(0.02)
    return None


class SocketDropTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_dropped_socket_lets_the_run_finish_and_the_reconnect_resumes_it(self):
        app = build_graph(checkpointer=MemorySaver())
        gate = asyncio.Event()
        model = _InterviewModel([(gate, SymptomFacts(chief_complaint="头疼"))])
        with _Patched(_graph_patches(model)), patch.object(main, "_master_app", app):
            bridge = main._voice_bridge()
            abandoned = []
            real_abandon = bridge.abandon_run

            async def spy(config):
                abandoned.append(config)
                await real_abandon(config)

            bridge.abandon_run = spy
            first = CallHarness(bridge)
            await first.start(hello(thread_id="voice-drop"))
            first.transport.client({"type": "input.text", "text": "我头疼"})
            await first.wait_state("thinking")
            first.transport.incoming.put_nowait(None)  # the socket drops mid-run
            await asyncio.wait_for(first.task, 3.0)
            self.assertEqual(abandoned, [], "a transient drop must not abandon the run")

            gate.set()  # the model answers after the client is gone
            value = await _pending_question(app, "voice-drop")
            self.assertEqual(value, {"kind": "followup", "question": QUESTION})

            second = CallHarness(main._voice_bridge())
            await second.start(hello(thread_id="voice-drop"))
            try:
                self.assertEqual(second.transport.spoken_texts()[0], QUESTION)
                self.assertNotIn(CUE_TEXTS["opening"], second.transport.spoken_texts())
            finally:
                await second.stop()

    async def test_a_detached_run_that_never_ends_is_bounded(self):
        bridge = ScriptedBridge([[asyncio.Event()]])  # hangs forever
        harness = CallHarness(bridge, timings=replace(TEST_TIMINGS, graph_stall=10.0, graph_max=0.4))
        await harness.start(hello(thread_id="voice-hang"))
        harness.transport.client({"type": "input.text", "text": "我头疼"})
        await harness.wait_state("thinking")
        harness.transport.incoming.put_nowait(None)
        await asyncio.wait_for(harness.task, 3.0)
        await asyncio.sleep(0.05)
        self.assertEqual(bridge.abandoned, [], "still running in the background")
        await asyncio.sleep(0.6)  # past graph_max
        self.assertEqual(len(bridge.abandoned), 1, "cut off and closed out at the hard cap")
        from voice import runs

        self.assertNotIn("voice-hang", runs.DETACHED_RUNS)

    async def test_a_reconnect_waits_for_the_detached_run_of_its_thread(self):
        hold = asyncio.Event()
        bridge = ScriptedBridge([[hold, *followup(QUESTION)]])
        first = CallHarness(bridge)
        await first.start(hello(thread_id="voice-wait"))
        first.transport.client({"type": "input.text", "text": "我头疼"})
        await first.wait_state("thinking")
        first.transport.incoming.put_nowait(None)
        await asyncio.wait_for(first.task, 3.0)

        second = CallHarness(bridge)
        await second.start(hello(thread_id="voice-wait"), wait_listening=False)
        try:
            await asyncio.sleep(0.1)
            self.assertEqual(second.transport.spoken_texts(), [], "no greeting while the old run still writes")
            from test_voice_fakes import pending_snapshot

            bridge.snapshot = pending_snapshot({"kind": "followup", "question": QUESTION})
            hold.set()
            await second.transport.wait_for(lambda: QUESTION in second.transport.spoken_texts())
        finally:
            await second.stop()


class StallKeepsTheInterviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_hung_resume_keeps_the_question_and_the_answer(self):
        app = build_graph(checkpointer=MemorySaver())
        model = _InterviewModel([
            SymptomFacts(chief_complaint="头疼"),
            (asyncio.Event(), COMPLETE),  # the resumed step never returns
            SymptomFacts(chief_complaint="头疼", duration="三天", severity="严重"),
        ])
        with _Patched(_graph_patches(model)), patch.object(main, "_master_app", app):
            harness = CallHarness(main._voice_bridge(), timings=replace(TEST_TIMINGS, graph_stall=0.4))
            await harness.start(hello(thread_id="voice-hung-resume"))
            t = harness.transport
            try:
                t.client({"type": "input.text", "text": "我头疼"})
                await t.wait_for(lambda: QUESTION in t.spoken_texts())
                await harness.wait_state("listening")
                t.client({"type": "input.text", "text": "三天了，比较严重"})
                await t.wait_for(lambda: CUE_TEXTS["slow"] in t.spoken_texts())

                texts, snapshot = await _history(app, "voice-hung-resume")
                self.assertIn(QUESTION, texts, "the follow-up question reached the history")
                self.assertIn("三天了，比较严重", texts, "so did the answer")
                self.assertEqual(snapshot.next, ())

                await harness.wait_state("listening")
                t.client({"type": "input.text", "text": "对，就是这样"})
                await t.wait_for(lambda: any(f.get("kind") == "confirm" for f in t.json_frames("interrupt")))
            finally:
                await harness.stop()

    async def test_a_hung_conclude_keeps_the_read_back(self):
        app = build_graph(checkpointer=MemorySaver())
        model = _InterviewModel([COMPLETE, COMPLETE])
        agent = _HangingThenAnsweringAgent("建议您到呼吸内科就诊。")
        with _Patched(_graph_patches(model, agent)), patch.object(main, "_master_app", app):
            harness = CallHarness(main._voice_bridge(), timings=replace(TEST_TIMINGS, graph_stall=0.4))
            await harness.start(hello(thread_id="voice-hung-conclude"))
            t = harness.transport
            try:
                t.client({"type": "input.text", "text": "我咳嗽三天了，中等"})
                await t.wait_for(lambda: any(f.get("kind") == "confirm" for f in t.json_frames("interrupt")))
                readback = t.json_frames("interrupt")[-1]["content"]
                await harness.wait_state("listening")
                t.client({"type": "ui.action", "kind": "confirm"})
                await t.wait_for(lambda: CUE_TEXTS["slow"] in t.spoken_texts())
                texts, snapshot = await _history(app, "voice-hung-conclude")
                self.assertIn(readback, texts)
                self.assertIn("对", texts)
                self.assertEqual(snapshot.next, ())
            finally:
                await harness.stop()


class BufferedSpeechIsNeverDroppedTests(unittest.IsolatedAsyncioTestCase):
    async def _buffer_behind(self, script, timings):
        bridge = ScriptedBridge([script, followup(QUESTION)])
        harness = CallHarness(bridge, timings=timings)
        await harness.start()
        t = harness.transport
        t.client({"type": "input.text", "text": "我头疼"})
        await harness.wait_state("thinking")
        t.client({"type": "input.text", "text": "三天了"})  # committed while the run is busy
        await t.wait_for(lambda: any(f.get("text") == "三天了" for f in t.json_frames("stt.final")))
        return bridge, harness

    async def test_a_stall_feeds_the_buffered_turn_next(self):
        bridge, harness = await self._buffer_behind([asyncio.Event()], replace(TEST_TIMINGS, graph_stall=0.3))
        try:
            await harness.transport.wait_for(lambda: bridge.inputs == ["我头疼", "三天了"])
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
        finally:
            await harness.stop()

    async def test_an_error_feeds_the_buffered_turn_next(self):
        hold = asyncio.Event()
        bridge, harness = await self._buffer_behind([hold, RuntimeError("model down")], TEST_TIMINGS)
        try:
            hold.set()
            await harness.transport.wait_for(lambda: bridge.inputs == ["我头疼", "三天了"])
            await harness.transport.wait_for(lambda: QUESTION in harness.transport.spoken_texts())
        finally:
            await harness.stop()


class ChannelIsPerRequestTests(unittest.IsolatedAsyncioTestCase):
    """The channel comes from the request (config), never from the checkpoint."""

    def _capturing_agent(self, prompts):
        def capture(_model, *, tools, prompt):
            prompts.append(prompt.content)
            return _FakeReactAgent("建议您到呼吸内科就诊。\n正文……")

        return capture

    async def _sse(self, text, thread_id):
        request = main.ChatRequest(
            messages=[main.ChatMessage(role="user", content=text)], chat_mode="clinic", thread_id=thread_id
        )
        response = await main.chat(request)
        import json

        return [json.loads(chunk[6:]) async for chunk in response.body_iterator]

    async def test_text_chat_resuming_a_voice_read_back_continues_in_text(self):
        from test_voice_clinic import _state

        for reply in ("对", "不对，是五天"):
            with self.subTest(reply=reply):
                app = build_graph(checkpointer=MemorySaver())
                model = _InterviewModel([COMPLETE, SymptomFacts(chief_complaint="咳嗽", duration="五天", severity="中等")])
                prompts: list[str] = []
                patches = _graph_patches(model)
                patches[3] = patch("agents.clinic.create_react_agent", side_effect=self._capturing_agent(prompts))
                thread = f"hangup-on-confirm-{len(reply)}"
                with _Patched(patches), patch.object(main, "_master_app", app):
                    # A voice call ends on a pending read-back …
                    first = await app.ainvoke(
                        _state("我咳嗽三天了，中等", "voice"),
                        {"configurable": {"thread_id": thread, "channel": "voice"}},
                    )
                    self.assertEqual(first["__interrupt__"][0].value["kind"], "confirm")
                    # … and the user replies in the text chat.
                    events = await self._sse(reply, thread)
                types = [e["type"] for e in events]
                self.assertNotIn("interrupt", types, "no second voice read-back in text")
                self.assertEqual(len(prompts), 1, "concluded")
                self.assertNotIn("语音通道", prompts[0], "no voice lead instruction in text")
                self.assertTrue(any(e["type"] == "card" for e in events))

    async def test_a_voice_call_resuming_a_text_follow_up_reads_back(self):
        from test_voice_clinic import _state

        app = build_graph(checkpointer=MemorySaver())
        model = _InterviewModel([SymptomFacts(chief_complaint="头疼"), COMPLETE])
        with _Patched(_graph_patches(model)), patch.object(main, "_master_app", app):
            # The interview started in the text chat and is waiting for an answer …
            first = await app.ainvoke(
                _state("我头疼"), {"configurable": {"thread_id": "text-then-voice", "channel": "text"}}
            )
            self.assertEqual(first["__interrupt__"][0].value["kind"], "followup")
            # … and the answer comes in a voice call on the same thread.
            harness = CallHarness(main._voice_bridge())
            await harness.start(hello(thread_id="text-then-voice"))
            t = harness.transport
            try:
                t.client({"type": "input.text", "text": "三天了，比较严重"})
                await t.wait_for(lambda: any(f.get("kind") == "confirm" for f in t.json_frames("interrupt")))
            finally:
                await harness.stop()


if __name__ == "__main__":
    unittest.main()
