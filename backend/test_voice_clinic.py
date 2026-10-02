"""
Deterministic tests for the clinic-subgraph and main.py changes made for the
voice channel, plus one end-to-end call through the real master graph.

- emergency gate on every resumed answer (text channel too)
- channel=voice read-back confirmation, anchored yes, correction loop cap
- dict interrupt values; /api/chat SSE unchanged
- /api/voice Origin check and provider configuration errors

Every LLM factory is patched; nothing touches the network.
"""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agents import clinic
from agents.clinic import (
    INTERVIEW_SYSTEM_PROMPT,
    MAX_CONFIRMATIONS,
    SymptomFacts,
    TriageRecommendation,
    build_readback,
    check_sufficiency,
    is_affirmative_answer,
    route_after_sufficiency,
)
from agents.graph import build_graph
from test_clinic_graph import _FakeKnowledgeBase, _FakeLLM, _FakeReactAgent, _exploding_llm
from test_voice_fakes import CallHarness, hello

with patch("dotenv.load_dotenv"):
    import main

COMPLETE = SymptomFacts(chief_complaint="咳嗽", duration="三天", severity="中等")
RECOMMENDATION = TriageRecommendation(
    department=["呼吸内科"], urgency="soon", summary="建议尽快到呼吸内科就诊。", notes=["多喝温水"]
)


def _patches(facts_queue, *, followup_text="咳嗽多久了呢？", triage_text="建议您到呼吸内科就诊。"):
    fake_llm = _FakeLLM(facts_queue, RECOMMENDATION, followup_text)
    return [
        patch("agents.clinic.get_chat_llm", return_value=fake_llm),
        patch("agents.clinic.get_agent_tools", return_value=[]),
        patch("agents.clinic.get_knowledge_base", return_value=_FakeKnowledgeBase()),
        patch("agents.clinic.create_react_agent", return_value=_FakeReactAgent(triage_text)),
        patch("agents.router.get_chat_llm", side_effect=_exploding_llm),
    ]


class _Patched:
    def __init__(self, patches):
        self._patches = patches

    def __enter__(self):
        for item in self._patches:
            item.start()
        return self

    def __exit__(self, *exc):
        for item in reversed(self._patches):
            item.stop()


def _state(text: str, channel: str | None = None) -> dict:
    state = {
        "messages": [HumanMessage(content=text)],
        "user_info": {},
        "next_agent": "",
        "active_agent": "clinic_agent",
        "handoff_count": 0,
    }
    if channel is not None:
        state["channel"] = channel
    return state


def _interrupt_values(result) -> list:
    return [item.value for item in result.get("__interrupt__", ())]


class AffirmativeAndReadbackTests(unittest.TestCase):
    def test_affirmative_answers_are_anchored(self):
        for text in ("对", "对的。", "嗯", "是的，没错", "对，继续", "没问题！"):
            with self.subTest(text=text):
                self.assertTrue(is_affirmative_answer(text))
        for text in ("对，但是是五天", "不对", "不是三天", "对面楼的医院", "", "嗯…其实是胃疼"):
            with self.subTest(text=text):
                self.assertFalse(is_affirmative_answer(text))

    def test_readback_is_a_template_over_the_collected_facts(self):
        text = build_readback(
            {"chief_complaint": "头疼", "duration": "三天", "severity": "严重", "associated_symptoms": ["恶心"]}
        )
        self.assertEqual(text, "我确认一下：头疼，持续三天，比较严重，还伴有恶心，对吗？")

    def test_extraction_prompt_lets_later_corrections_win(self):
        self.assertIn("更正", INTERVIEW_SYSTEM_PROMPT)


class SufficiencyRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_channel_goes_straight_to_conclude_and_emits_no_facts(self):
        emitted: list[dict] = []
        state = {"collected": COMPLETE.model_dump(), "followup_count": 0}
        with patch("agents.clinic._emit", side_effect=emitted.append):
            update = await check_sufficiency(state)
        self.assertEqual(route_after_sufficiency({**state, **update}), "conclude")
        self.assertEqual(emitted, [])

    async def test_voice_channel_confirms_first_and_emits_facts(self):
        emitted: list[dict] = []
        state = {"collected": COMPLETE.model_dump(), "followup_count": 0, "channel": "voice"}
        with patch("agents.clinic._emit", side_effect=emitted.append):
            update = await check_sufficiency(state)
        self.assertEqual(route_after_sufficiency({**state, **update}), "confirm_facts")
        self.assertEqual(emitted[0]["type"], "facts")
        self.assertEqual(emitted[0]["missing"], [])

    def test_confirmation_budget_and_yes_skip_the_read_back(self):
        base = {"collected": COMPLETE.model_dump(), "is_sufficient": True, "channel": "voice"}
        self.assertEqual(route_after_sufficiency({**base, "facts_confirmed": True}), "conclude")
        self.assertEqual(route_after_sufficiency({**base, "confirm_count": MAX_CONFIRMATIONS}), "conclude")


class ClinicGraphVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_red_flag_in_a_followup_answer_hits_the_gate_on_the_text_channel(self):
        app = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "gate-on-answer"}}
        with _Patched(_patches([SymptomFacts(chief_complaint="头疼")])):
            first = await app.ainvoke(_state("我头疼"), config=config)
            self.assertEqual(
                _interrupt_values(first), [{"kind": "followup", "question": "咳嗽多久了呢？"}]
            )
            with patch("agents.clinic.create_react_agent", side_effect=AssertionError("no conclude")):
                second = await app.ainvoke(Command(resume="现在胸口剧痛，喘不过气"), config=config)

        texts = [m.content for m in second["messages"]]
        self.assertNotIn("__interrupt__", second)
        self.assertIn("咳嗽多久了呢？", texts)          # the follow-up Q&A reached the history
        self.assertIn("现在胸口剧痛，喘不过气", texts)
        self.assertIn("120", texts[-1])

    async def test_text_channel_never_reads_back(self):
        app = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "text-no-confirm"}}
        with _Patched(_patches([COMPLETE])):
            result = await app.ainvoke(_state("我咳嗽三天了，中等"), config=config)
        self.assertNotIn("__interrupt__", result)
        self.assertEqual(result["messages"][-1].content, "建议您到呼吸内科就诊。")

    async def test_voice_read_back_then_yes_concludes(self):
        app = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "voice-yes"}}
        with _Patched(_patches([COMPLETE])):
            first = await app.ainvoke(_state("我咳嗽三天了，中等", "voice"), config=config)
            (value,) = _interrupt_values(first)
            self.assertEqual(value["kind"], "confirm")
            self.assertEqual(value["question"], "我确认一下：咳嗽，持续三天，中等程度，对吗？")
            self.assertEqual(value["facts"]["duration"], "三天")
            second = await app.ainvoke(Command(resume="对"), config=config)
        self.assertNotIn("__interrupt__", second)
        self.assertEqual(second["messages"][-1].content, "建议您到呼吸内科就诊。")

    async def test_correction_loop_is_capped_at_two_read_backs(self):
        app = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "voice-cap"}}
        facts = [
            COMPLETE,
            SymptomFacts(chief_complaint="咳嗽", duration="五天", severity="中等"),
            SymptomFacts(chief_complaint="咳嗽", duration="一周", severity="中等"),
        ]
        with _Patched(_patches(facts)):
            first = await app.ainvoke(_state("我咳嗽三天了，中等", "voice"), config=config)
            second = await app.ainvoke(Command(resume="不对，是五天"), config=config)
            (value,) = _interrupt_values(second)
            self.assertEqual(value["kind"], "confirm")
            self.assertIn("五天", value["question"])
            third = await app.ainvoke(Command(resume="还是不对，是一周"), config=config)

        self.assertEqual(_interrupt_values(first)[0]["kind"], "confirm")
        self.assertNotIn("__interrupt__", third, "a third read-back must not happen")
        self.assertEqual(facts, [], "each correction is re-extracted")
        self.assertEqual(third["messages"][-1].content, "建议您到呼吸内科就诊。")


class VoiceLeadTests(unittest.IsolatedAsyncioTestCase):
    async def _conclude(self, channel: str, answer: str):
        prompts: list[str] = []

        def capture(_model, *, tools, prompt):
            prompts.append(prompt.content)
            return _FakeReactAgent(answer)

        state = {
            "messages": [HumanMessage(content="我咳嗽三天了，中等")],
            "user_info": {},
            "collected": COMPLETE.model_dump(),
            "channel": channel,
            "turn_messages": [],
        }
        emitted: list[dict] = []
        patches = _patches([])
        patches[3] = patch("agents.clinic.create_react_agent", side_effect=capture)
        with _Patched(patches), patch("agents.clinic._emit", side_effect=emitted.append):
            update = await clinic.conclude(state)
        return prompts[0], update, emitted

    async def test_voice_asks_for_a_spoken_lead_and_the_card_reuses_it(self):
        lead = "建议您尽快去呼吸内科看看。"
        prompt, update, emitted = await self._conclude("voice", f"{lead}\n## 分诊建议\n正文……")
        self.assertIn(clinic.VOICE_LEAD_INSTRUCTION.strip()[:10], prompt)
        self.assertEqual(update["recommendation"]["summary"], lead)
        self.assertEqual(emitted[-1]["payload"]["data"]["summary"], lead)

    async def test_text_channel_is_unchanged(self):
        prompt, update, _ = await self._conclude("text", "建议您尽快去呼吸内科看看。\n正文……")
        self.assertNotIn("语音通道", prompt)
        self.assertEqual(update["recommendation"]["summary"], RECOMMENDATION.summary)

    async def test_no_lead_keeps_the_summariser_summary(self):
        _, update, _ = await self._conclude("voice", "## 分诊建议\n正文……")
        self.assertEqual(update["recommendation"]["summary"], RECOMMENDATION.summary)

    def test_extract_spoken_lead(self):
        self.assertEqual(clinic.extract_spoken_lead("建议去神经内科。\n正文"), "建议去神经内科。")
        self.assertEqual(clinic.extract_spoken_lead("建议去神经内科\n正文"), "建议去神经内科")
        self.assertEqual(clinic.extract_spoken_lead("## 标题\n正文"), "")
        self.assertEqual(clinic.extract_spoken_lead("没有结尾" * 30), "")


class MainStreamSplitTests(unittest.IsolatedAsyncioTestCase):
    class _Interrupt:
        def __init__(self, value):
            self.value = value
            self.id = "i-1"

    def _graph(self, events):
        class _Graph:
            async def astream_events(self, *_args, **_kwargs):
                for event in events:
                    yield event

        return _Graph()

    def _events(self, value):
        return [
            {"event": "on_chain_stream", "name": "LangGraph",
             "data": {"chunk": ((), "custom", {"type": "facts", "collected": {}, "missing": []})}},
            {"event": "on_chain_stream", "name": "LangGraph",
             "data": {"chunk": ((), "updates", {"__interrupt__": (self._Interrupt(value),)})}},
        ]

    async def test_sse_bytes_are_identical_for_string_and_dict_interrupts(self):
        outputs = []
        for value in ("持续多久了？", {"kind": "followup", "question": "持续多久了？"}):
            with patch.object(main, "get_master_app", return_value=self._graph(self._events(value))):
                outputs.append([chunk async for chunk in main._stream_agent_events({}, {})])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(
            outputs[0],
            [
                'data: {"type": "text", "content": "持续多久了？"}\n\n',
                'data: {"type": "interrupt", "content": "持续多久了？"}\n\n',
                'data: {"type": "finish"}\n\n',
            ],
        )

    async def test_the_event_generator_carries_kind_and_optional_custom_types(self):
        value = {"kind": "confirm", "question": "对吗？"}
        with patch.object(main, "get_master_app", return_value=self._graph(self._events(value))):
            events = [e async for e in main._iter_agent_events({}, {}, custom_types={"card", "text", "facts"})]
        self.assertEqual([e["type"] for e in events], ["facts", "text", "interrupt", "finish"])
        self.assertEqual(events[2], {"type": "interrupt", "content": "对吗？", "kind": "confirm"})

    def test_initial_state_defaults_to_the_text_channel(self):
        state = main._build_initial_state([main.ChatMessage(role="user", content="你好")], None, "advisor_agent")
        self.assertEqual(state["channel"], "text")
        voice = main._build_voice_state("头疼", {"name": "测试", "elder_mode": True}, "voice")
        self.assertEqual((voice["channel"], voice["active_agent"]), ("voice", "clinic_agent"))
        self.assertTrue(voice["user_info"]["elder_mode"])


class VoiceCallThroughTheRealGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_followup_read_back_and_confirm_button_reach_a_spoken_conclusion(self):
        app = build_graph(checkpointer=MemorySaver())
        facts = [SymptomFacts(chief_complaint="咳嗽"), COMPLETE]
        with _Patched(_patches(facts)), patch.object(main, "_master_app", app), patch.object(
            main, "resolve_model_settings"
        ):
            harness = CallHarness(main._voice_bridge())
            await harness.start(hello(thread_id="voice-e2e"))
            t = harness.transport
            try:
                t.client({"type": "input.text", "text": "我最近有点咳嗽"})
                await t.wait_for(lambda: "咳嗽多久了呢？" in t.spoken_texts())
                await harness.wait_state("listening")

                t.client({"type": "input.text", "text": "三天了，中等程度"})
                readback = "我确认一下：咳嗽，持续三天，中等程度，对吗？"
                await t.wait_for(lambda: readback in t.spoken_texts())
                self.assertEqual(t.json_frames("interrupt")[-1]["kind"], "confirm")
                self.assertTrue(t.json_frames("facts"))
                await harness.wait_state("listening")

                t.client({"type": "ui.action", "kind": "confirm"})
                # Voice: the card's summary is the answer's spoken first line.
                await t.wait_for(lambda: "建议您到呼吸内科就诊。" in t.spoken_texts())
                card = next(f for f in t.json_frames("card") if f["payload"]["type"] == "clinic_recommendation")
                self.assertEqual(card["payload"]["data"]["departments"], ["呼吸内科"])
            finally:
                await harness.stop()

            data = t.json_frames("summary")[0]["payload"]["data"]
            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["departments"], ["呼吸内科"])
            self.assertEqual(data["chief_complaint"], "咳嗽")

            # The same thread continues over text afterwards.
            snapshot = await app.aget_state({"configurable": {"thread_id": "voice-e2e"}})
            texts = [m.content for m in snapshot.values["messages"]]
            self.assertIn("我最近有点咳嗽", texts)
            self.assertIn(readback, texts)


class _HangingThenAnsweringAgent:
    """A ReAct agent whose first conclude hangs forever (a stuck model call)."""

    def __init__(self, answer: str):
        self.calls = 0
        self._answer = answer

    async def ainvoke(self, payload):
        from langchain_core.messages import AIMessage

        self.calls += 1
        if self.calls == 1:
            await asyncio.Event().wait()
        return {"messages": [*payload["messages"], AIMessage(content=self._answer)]}


class StalledConcludeTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_stalled_conclude_is_cancelled_and_the_thread_takes_the_next_turn(self):
        from dataclasses import replace

        from test_voice_fakes import TEST_TIMINGS
        from voice.cues import CUE_TEXTS

        app = build_graph(checkpointer=MemorySaver())
        agent = _HangingThenAnsweringAgent("建议您到呼吸内科就诊。")
        facts = [COMPLETE, COMPLETE]
        patches = _patches(facts)
        patches[3] = patch("agents.clinic.create_react_agent", return_value=agent)
        with _Patched(patches), patch.object(main, "_master_app", app), patch.object(
            main, "resolve_model_settings"
        ):
            harness = CallHarness(main._voice_bridge(), timings=replace(TEST_TIMINGS, graph_stall=0.4))
            await harness.start(hello(thread_id="voice-stall"))
            t = harness.transport
            try:
                t.client({"type": "input.text", "text": "我咳嗽三天了，中等"})
                await t.wait_for(lambda: any(f.get("kind") == "confirm" for f in t.json_frames("interrupt")))
                await harness.wait_state("listening")
                t.client({"type": "ui.action", "kind": "confirm"})
                await t.wait_for(lambda: CUE_TEXTS["slow"] in t.spoken_texts())
                self.assertEqual(agent.calls, 1)
                await harness.wait_state("listening")

                # Same thread, next turn: a normal new turn (the cut-off step
                # was closed out), so the new words are heard and read back.
                t.client({"type": "input.text", "text": "还是咳嗽，三天了，中等"})
                await t.wait_for(
                    lambda: sum(1 for f in t.json_frames("interrupt") if f.get("kind") == "confirm") == 2
                )
                self.assertEqual(t.json_frames("error"), [])
                await harness.wait_state("listening")
                t.client({"type": "ui.action", "kind": "confirm"})
                # Voice: the card's summary is the answer's spoken first line.
                await t.wait_for(lambda: "建议您到呼吸内科就诊。" in t.spoken_texts())
                self.assertEqual(agent.calls, 2)
            finally:
                await harness.stop()

            snapshot = await app.aget_state({"configurable": {"thread_id": "voice-stall"}})
            texts = [m.content for m in snapshot.values["messages"]]
            self.assertIn("还是咳嗽，三天了，中等", texts)
            self.assertEqual(texts[-1], "建议您到呼吸内科就诊。")
            self.assertEqual(snapshot.next, ())


class VoiceEvalCaseTests(unittest.IsolatedAsyncioTestCase):
    def test_dataset_carries_voice_cases(self):
        from pathlib import Path

        from evals import load_cases

        cases = {case.id: case for case in load_cases(Path("evals/cases.jsonl"))}
        voice = [case for case in cases.values() if case.channel == "voice"]
        self.assertEqual(len(voice), 2)
        red_flag = cases["voice-clinic-red-flag-mid-followup"]
        self.assertEqual(red_flag.expected_output_contains, "120")
        self.assertEqual(len(red_flag.followups), 1)
        self.assertEqual(cases["route-clinic-fever"].channel, "text")

    def test_bad_channel_is_rejected_and_output_check_scores(self):
        from evals import EvalCase, EvalRun, evaluate_run

        with self.assertRaisesRegex(ValueError, "channel"):
            EvalCase.from_mapping({"id": "x", "input": "a", "expected_agent": "b", "channel": "phone"})
        case = EvalCase.from_mapping(
            {"id": "x", "input": "a", "expected_agent": "clinic_agent", "expected_output_contains": "120"}
        )
        run = EvalRun(case_id="x", actual_agent="clinic_agent", actual_output="请拨打120", tools_called=())
        self.assertTrue(evaluate_run(case, run).passed)
        self.assertFalse(evaluate_run(case, EvalRun("x", "clinic_agent", "多喝水", ())).passed)

    async def test_runner_resumes_interrupts_with_followups_on_the_voice_channel(self):
        from evals import EvalCase
        from evals import run as eval_run

        seen: list = []

        class _Graph:
            async def ainvoke(self, graph_input, config=None):
                seen.append(graph_input)
                return {"messages": [], "__interrupt__": ["pending"]} if len(seen) == 1 else {"messages": []}

        case = EvalCase.from_mapping({
            "id": "v", "input": "头晕", "expected_agent": "clinic_agent",
            "chat_mode": "clinic", "channel": "voice", "followups": ["胸口剧痛"],
        })
        with patch("agents.graph.master_app", _Graph()):
            await eval_run._execute_case(case)
        self.assertEqual(seen[0]["channel"], "voice")
        self.assertIsInstance(seen[1], Command)
        self.assertEqual(seen[1].resume, "胸口剧痛")


class VoiceEndpointTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(main.app)

    def test_foreign_origin_is_rejected_at_the_handshake(self):
        from starlette.websockets import WebSocketDisconnect

        for headers in ({"origin": "http://evil.example"}, {}):
            with self.subTest(headers=headers), self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect("/api/voice", headers=headers):
                    pass

    def test_missing_speech_configuration_is_a_fatal_error_frame(self):
        with patch.dict(os.environ, {"ASR_PROVIDER": "", "TTS_PROVIDER": ""}), patch.object(
            main, "_speech_providers", None
        ):
            with self.client.websocket_connect(
                "/api/voice", headers={"origin": "http://localhost:5173"}
            ) as ws:
                frame = json.loads(ws.receive_text())
        self.assertEqual(frame["type"], "error")
        self.assertEqual(frame["class"], "fatal")
        self.assertIn("ASR_PROVIDER", frame["content"])

    def test_an_unimplemented_provider_is_a_fatal_error_frame(self):
        env = {"ASR_PROVIDER": "dashscope", "TTS_PROVIDER": "fake", "DASHSCOPE_API_KEY": "k"}
        with patch.dict(os.environ, env), patch.object(main, "_speech_providers", None):
            with self.client.websocket_connect(
                "/api/voice", headers={"origin": "http://localhost:5173"}
            ) as ws:
                frame = json.loads(ws.receive_text())
        self.assertEqual(frame["class"], "fatal")
        self.assertIn("not implemented", frame["content"])

    def test_fake_providers_open_a_session_and_bye_returns_a_summary(self):
        app = build_graph(checkpointer=MemorySaver())
        env = {"ASR_PROVIDER": "fake", "TTS_PROVIDER": "fake"}
        with patch.dict(os.environ, env), patch.object(main, "_speech_providers", None), patch.object(
            main, "_master_app", app
        ), patch.object(main, "resolve_model_settings"):
            with self.client.websocket_connect(
                "/api/voice", headers={"origin": "http://localhost:5174"}
            ) as ws:
                ws.send_text(json.dumps(hello()))
                first = json.loads(ws.receive_text())
                ws.send_text(json.dumps({"type": "bye"}))
                frames = []
                while True:
                    message = ws.receive()
                    if message.get("type") == "websocket.close":
                        break
                    if message.get("text"):
                        frames.append(json.loads(message["text"]))
        self.assertEqual(first["type"], "session")
        self.assertIn("summary", [f["type"] for f in frames])

    def test_bye_in_emergency_over_the_real_endpoint_sends_summary_then_closes_1000(self):
        app = build_graph(checkpointer=MemorySaver())
        env = {"ASR_PROVIDER": "fake", "TTS_PROVIDER": "fake"}
        with patch.dict(os.environ, env), patch.object(main, "_speech_providers", None), patch.object(
            main, "_master_app", app
        ), patch.object(main, "resolve_model_settings"), patch(
            "agents.router.get_chat_llm", side_effect=_exploding_llm
        ), patch("agents.clinic.get_chat_llm", side_effect=_exploding_llm):
            with self.client.websocket_connect(
                "/api/voice", headers={"origin": "http://localhost:5173"}
            ) as ws:
                ws.send_text(json.dumps(hello()))
                ws.send_text(json.dumps({"type": "input.text", "text": "我突然剧烈胸痛，一直冒大汗"}))
                frames = []
                while True:
                    message = ws.receive()
                    if message.get("type") == "websocket.close":
                        close_code = message.get("code")
                        break
                    if message.get("text"):
                        frame = json.loads(message["text"])
                        frames.append(frame)
                        if frame == {"type": "state", "value": "emergency"}:
                            ws.send_text(json.dumps({"type": "bye"}))
        types = [f["type"] for f in frames]
        self.assertEqual(close_code, 1000)
        self.assertEqual(types[-1], "summary")
        data = frames[-1]["payload"]["data"]
        self.assertTrue(data["emergency_flags"])


if __name__ == "__main__":
    unittest.main()
