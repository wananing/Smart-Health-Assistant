"""Deterministic tests for the clinic subgraph and the thread_id / resume path.

Every LLM factory is patched, so the suite never touches the network.
"""
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END
from langgraph.types import Command

from agents import clinic
from agents.clinic import (
    MAX_FOLLOWUPS,
    SymptomFacts,
    TriageRecommendation,
    check_sufficiency,
    emergency_gate,
    route_after_gate,
    route_after_sufficiency,
)
from agents.graph import build_graph

CRITICAL_TEXT = "我突然剧烈胸痛，还一直冒大汗"
MILD_TEXT = "我最近有点咳嗽"


def _exploding_llm(*args, **kwargs):
    raise AssertionError("the emergency gate must not call an LLM")


class _FakeStructuredRunnable:
    """Stands in for `llm.with_structured_output(schema)`."""

    def __init__(self, schema, facts_queue: list[SymptomFacts], recommendation):
        self._schema = schema
        self._facts_queue = facts_queue
        self._recommendation = recommendation

    async def ainvoke(self, _messages):
        if self._schema is SymptomFacts:
            return self._facts_queue.pop(0) if self._facts_queue else SymptomFacts()
        return self._recommendation


class _FakeLLM:
    def __init__(self, facts_queue, recommendation, followup_text):
        self._facts_queue = facts_queue
        self._recommendation = recommendation
        self._followup_text = followup_text

    def with_structured_output(self, schema):
        return _FakeStructuredRunnable(schema, self._facts_queue, self._recommendation)

    async def ainvoke(self, _messages):
        return AIMessage(content=self._followup_text)


class _FakeReactAgent:
    def __init__(self, answer: str):
        self._answer = answer

    async def ainvoke(self, payload):
        return {"messages": [*payload["messages"], AIMessage(content=self._answer)]}


class _FakeKnowledgeBase:
    async def amulti_query_retrieve(self, _queries, k=4):
        return []

    def format_context(self, _docs):
        return ""


class EmergencyGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_critical_phrase_short_circuits_without_any_llm_call(self):
        state = {
            "messages": [HumanMessage(content=CRITICAL_TEXT)],
            "user_info": {"name": "张三", "age": 62},
        }

        with patch("agents.clinic.get_chat_llm", side_effect=_exploding_llm):
            update = await emergency_gate(state)

        self.assertEqual(update["emergency_level"], "CRITICAL")
        self.assertEqual(route_after_gate({**state, **update}), END)

        answer = update["messages"][0]
        self.assertIsInstance(answer, AIMessage)
        self.assertIn("120", answer.content)
        self.assertEqual(update["recommendation"]["urgency"], "emergency")
        self.assertEqual(update["recommendation"]["department"], ["急诊科"])

    async def test_mild_symptom_continues_into_the_interview(self):
        state = {"messages": [HumanMessage(content=MILD_TEXT)], "user_info": {}}

        with patch("agents.clinic.get_chat_llm", side_effect=_exploding_llm):
            update = await emergency_gate(state)

        self.assertNotEqual(update["emergency_level"], "CRITICAL")
        self.assertNotIn("messages", update)
        self.assertEqual(route_after_gate({**state, **update}), "extract_symptoms")

    async def test_critical_gate_streams_text_and_card_events(self):
        emitted: list[dict] = []
        state = {"messages": [HumanMessage(content=CRITICAL_TEXT)], "user_info": {}}

        with patch("agents.clinic.get_chat_llm", side_effect=_exploding_llm), patch(
            "agents.clinic._emit", side_effect=emitted.append
        ):
            await emergency_gate(state)

        self.assertEqual([item["type"] for item in emitted], ["text", "card"])
        card = emitted[1]["payload"]
        self.assertEqual(card["type"], "clinic_recommendation")
        self.assertEqual(card["data"]["severity"], "high")


class CheckSufficiencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_required_fields_routes_to_followup(self):
        state = {"collected": {"chief_complaint": "咳嗽"}, "followup_count": 0}

        update = await check_sufficiency(state)

        self.assertFalse(update["is_sufficient"])
        self.assertEqual(update["missing_fields"], ["duration", "severity"])
        self.assertEqual(route_after_sufficiency({**state, **update}), "ask_followup")

    async def test_complete_facts_route_to_conclude(self):
        state = {
            "collected": {"chief_complaint": "咳嗽", "duration": "三天", "severity": "中等"},
            "followup_count": 0,
        }

        update = await check_sufficiency(state)

        self.assertTrue(update["is_sufficient"])
        self.assertEqual(update["missing_fields"], [])
        self.assertEqual(route_after_sufficiency({**state, **update}), "conclude")

    async def test_exhausted_followups_force_a_conclusion(self):
        state = {"collected": {}, "followup_count": MAX_FOLLOWUPS}

        update = await check_sufficiency(state)

        self.assertTrue(update["is_sufficient"])
        self.assertEqual(update["missing_fields"], list(clinic.REQUIRED_FIELDS))
        self.assertEqual(route_after_sufficiency({**state, **update}), "conclude")


class ClinicSubgraphFlowTests(unittest.IsolatedAsyncioTestCase):
    """Drives the compiled master graph end to end with fake models."""

    def _patches(self, facts_queue, recommendation, followup_text, triage_text):
        fake_llm = _FakeLLM(facts_queue, recommendation, followup_text)
        return (
            patch("agents.clinic.get_chat_llm", return_value=fake_llm),
            patch("agents.clinic.get_agent_tools", return_value=[]),
            patch("agents.clinic.get_knowledge_base", return_value=_FakeKnowledgeBase()),
            patch(
                "agents.clinic.create_react_agent",
                return_value=_FakeReactAgent(triage_text),
            ),
        )

    async def test_critical_path_never_reaches_the_interview(self):
        app = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "critical-thread"}}
        state = {
            "messages": [HumanMessage(content=CRITICAL_TEXT)],
            "user_info": {"age": 62},
            "next_agent": "",
            "active_agent": "clinic_agent",
        }

        with patch("agents.clinic.get_chat_llm", side_effect=_exploding_llm), patch(
            "agents.router.get_chat_llm", side_effect=_exploding_llm
        ):
            result = await app.ainvoke(state, config=config)

        self.assertEqual(len(result["messages"]), 2)
        self.assertIn("120", result["messages"][-1].content)

    async def test_followup_interrupts_then_resumes_into_a_recommendation(self):
        app = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "followup-thread"}}
        facts_queue = [
            SymptomFacts(chief_complaint="咳嗽"),
            SymptomFacts(chief_complaint="咳嗽", duration="三天", severity="中等"),
        ]
        recommendation = TriageRecommendation(
            department=["呼吸内科"],
            urgency="soon",
            summary="建议尽快到呼吸内科就诊。",
            notes=["多喝温水", "记录体温变化"],
        )
        llm_patch, tools_patch, kb_patch, react_patch = self._patches(
            facts_queue, recommendation, "咳嗽多久了呢？", "建议您到呼吸内科就诊。"
        )

        with llm_patch, tools_patch, kb_patch, react_patch, patch(
            "agents.router.get_chat_llm", side_effect=_exploding_llm
        ):
            first = await app.ainvoke(
                {
                    "messages": [HumanMessage(content=MILD_TEXT)],
                    "user_info": {},
                    "next_agent": "",
                    "active_agent": "clinic_agent",
                },
                config=config,
            )

            self.assertIn("__interrupt__", first)
            self.assertEqual(first["__interrupt__"][0].value, "咳嗽多久了呢？")
            # Nothing has been committed to the parent history yet.
            self.assertEqual(len(first["messages"]), 1)

            snapshot = await app.aget_state(config)
            pending = [i for task in snapshot.tasks for i in task.interrupts]
            self.assertEqual(len(pending), 1)

            emitted: list[dict] = []
            with patch("agents.clinic._emit", side_effect=emitted.append):
                second = await app.ainvoke(Command(resume="三天了，中等程度"), config=config)

        texts = [message.content for message in second["messages"]]
        self.assertIn(MILD_TEXT, texts)
        self.assertIn("咳嗽多久了呢？", texts)
        self.assertIn("三天了，中等程度", texts)
        self.assertIn("建议您到呼吸内科就诊。", texts)

        cards = [item for item in emitted if item["type"] == "card"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["payload"]["type"], "clinic_recommendation")
        self.assertEqual(cards[0]["payload"]["data"]["departments"], ["呼吸内科"])
        self.assertEqual(cards[0]["payload"]["data"]["severity"], "medium")


class _FakeSnapshot:
    def __init__(self, values, tasks=()):
        self.values = values
        self.tasks = tasks


class _FakeTask:
    def __init__(self, interrupts):
        self.interrupts = interrupts


class _FakeInterrupt:
    def __init__(self, value, id="int-1"):
        self.value = value
        self.id = id


class _FakeGraph:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.seen_config = None

    async def aget_state(self, config):
        self.seen_config = config
        return self._snapshot


class ThreadResumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch("dotenv.load_dotenv"):
            import main

        self.main = main
        self.config = {"configurable": {"thread_id": "t-1"}}
        self.turn_state = {"messages": ["new"]}
        self.full_state = {"messages": ["old", "new"]}

    async def test_unknown_thread_replays_the_full_history(self):
        graph = _FakeGraph(_FakeSnapshot(values={}))

        with patch.object(self.main, "get_master_app", return_value=graph):
            resolved = await self.main._resolve_graph_input(
                self.config, self.turn_state, self.full_state, "new"
            )

        self.assertIs(resolved, self.full_state)
        self.assertEqual(graph.seen_config, self.config)

    async def test_known_thread_sends_only_the_new_message(self):
        graph = _FakeGraph(_FakeSnapshot(values={"messages": ["old"]}))

        with patch.object(self.main, "get_master_app", return_value=graph):
            resolved = await self.main._resolve_graph_input(
                self.config, self.turn_state, self.full_state, "new"
            )

        self.assertIs(resolved, self.turn_state)

    async def test_pending_interrupt_resumes_with_the_user_answer(self):
        snapshot = _FakeSnapshot(
            values={"messages": ["old"]},
            tasks=(_FakeTask((_FakeInterrupt("持续多久了？"),)),),
        )
        graph = _FakeGraph(snapshot)

        with patch.object(self.main, "get_master_app", return_value=graph):
            resolved = await self.main._resolve_graph_input(
                self.config, self.turn_state, self.full_state, "三天了"
            )

        self.assertIsInstance(resolved, Command)
        self.assertEqual(resolved.resume, "三天了")

    async def test_exit_phrase_during_an_interrupt_abandons_the_thread(self):
        snapshot = _FakeSnapshot(
            values={"messages": ["old"]},
            tasks=(_FakeTask((_FakeInterrupt("持续多久了？"),)),),
        )
        graph = _FakeGraph(snapshot)

        with patch.object(self.main, "get_master_app", return_value=graph):
            resolved = await self.main._resolve_graph_input(
                self.config, self.turn_state, self.full_state, "退出"
            )

        self.assertIsNone(resolved)

    async def test_abandoned_thread_gets_a_fresh_id_and_the_full_history(self):
        request = self.main.ChatRequest(
            messages=[self.main.ChatMessage(role="user", content="退出")],
            thread_id="stale-thread",
        )
        captured: dict = {}

        async def _fake_stream(graph_input, config=None):
            captured["config"] = config
            captured["graph_input"] = graph_input
            yield 'data: {"type": "finish"}\n\n'

        with patch.object(self.main, "resolve_model_settings"), patch.object(
            self.main, "_resolve_graph_input", return_value=None
        ), patch.object(self.main, "_stream_agent_events", _fake_stream):
            response = await self.main.chat(request)
            chunks = [chunk async for chunk in response.body_iterator]

        new_thread_id = captured["config"]["configurable"]["thread_id"]
        self.assertNotEqual(new_thread_id, "stale-thread")
        self.assertIn(new_thread_id, chunks[0])
        self.assertNotIn("stale-thread", chunks[0])

    async def test_chat_endpoint_emits_a_session_event_with_the_thread_id(self):
        request = self.main.ChatRequest(
            messages=[self.main.ChatMessage(role="user", content="你好")],
            thread_id="thread-abc",
        )

        async def _fake_stream(_graph_input, _config=None):
            yield 'data: {"type": "finish"}\n\n'

        with patch.object(self.main, "resolve_model_settings"), patch.object(
            self.main, "_resolve_graph_input", return_value={"messages": []}
        ), patch.object(self.main, "_stream_agent_events", _fake_stream):
            response = await self.main.chat(request)
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertIn('"type": "session"', chunks[0])
        self.assertIn("thread-abc", chunks[0])

    async def test_chat_endpoint_generates_a_thread_id_when_none_is_sent(self):
        request = self.main.ChatRequest(
            messages=[self.main.ChatMessage(role="user", content="你好")]
        )
        captured: dict = {}

        async def _fake_resolve(config, turn_state, full_state, user_text):
            captured["config"] = config
            captured["user_text"] = user_text
            return full_state

        async def _fake_stream(_graph_input, _config=None):
            yield 'data: {"type": "finish"}\n\n'

        with patch.object(self.main, "resolve_model_settings"), patch.object(
            self.main, "_resolve_graph_input", _fake_resolve
        ), patch.object(self.main, "_stream_agent_events", _fake_stream):
            response = await self.main.chat(request)
            chunks = [chunk async for chunk in response.body_iterator]

        thread_id = captured["config"]["configurable"]["thread_id"]
        self.assertTrue(thread_id)
        self.assertIn(thread_id, chunks[0])
        self.assertEqual(captured["user_text"], "你好")


class CheckpointerShutdownTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch("dotenv.load_dotenv"):
            import main

        self.main = main

    async def test_memory_checkpointer_has_nothing_to_close(self):
        with patch.object(self.main, "_master_app", None):
            await self.main._close_checkpointer()  # must not raise

    async def test_async_connection_is_awaited(self):
        closed: list[bool] = []

        class _Conn:
            async def close(self):
                closed.append(True)

        class _Saver:
            conn = _Conn()

        class _App:
            checkpointer = _Saver()

        with patch.object(self.main, "_master_app", _App()):
            await self.main._close_checkpointer()

        self.assertEqual(closed, [True])


class StreamTranslationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch("dotenv.load_dotenv"):
            import main

        self.main = main

    def test_root_chunks_are_decoded_and_node_chunks_ignored(self):
        self.assertEqual(
            self.main._split_stream_chunk((("clinic_node:1",), "custom", {"a": 1})),
            ("custom", {"a": 1}),
        )
        self.assertEqual(
            self.main._split_stream_chunk(("updates", {"a": 1})),
            ("updates", {"a": 1}),
        )
        self.assertIsNone(self.main._split_stream_chunk({"messages": []}))

    async def test_custom_card_events_and_interrupts_become_sse_payloads(self):
        card = {
            "type": "card",
            "payload": {"type": "clinic_recommendation", "data": {"departments": ["呼吸内科"]}},
        }
        events = [
            {
                "event": "on_chain_stream",
                "name": "LangGraph",
                "data": {"chunk": (("clinic_node:1",), "custom", card)},
            },
            {
                "event": "on_chain_stream",
                "name": "LangGraph",
                "data": {"chunk": ((), "custom", {"type": "text", "content": "安全提示"})},
            },
            {
                "event": "on_chain_stream",
                "name": "LangGraph",
                "data": {"chunk": ((), "custom", {"type": "secret", "content": "x"})},
            },
            {
                "event": "on_chain_stream",
                "name": "LangGraph",
                "data": {
                    "chunk": ((), "updates", {"__interrupt__": (_FakeInterrupt("持续多久了？"),)})
                },
            },
            {
                "event": "on_chain_stream",
                "name": "LangGraph",
                "data": {
                    "chunk": ((), "updates", {"__interrupt__": (_FakeInterrupt("持续多久了？"),)})
                },
            },
        ]

        class _FakeStreamingGraph:
            async def astream_events(self, *_args, **_kwargs):
                for event in events:
                    yield event

        with patch.object(self.main, "get_master_app", return_value=_FakeStreamingGraph()):
            payloads = [
                chunk
                async for chunk in self.main._stream_agent_events({"messages": []}, self.config())
            ]

        decoded = [self.main.json.loads(chunk[len("data: "):]) for chunk in payloads]
        types = [item["type"] for item in decoded]
        self.assertEqual(types, ["card", "text", "text", "interrupt", "finish"])
        self.assertEqual(decoded[0]["payload"]["type"], "clinic_recommendation")
        self.assertEqual(decoded[2]["content"], "持续多久了？")

    def config(self):
        return {"configurable": {"thread_id": "t-stream"}}


if __name__ == "__main__":
    unittest.main()
