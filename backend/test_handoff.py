"""
Deterministic tests for Command-based agent handoffs and the tightened
exit-phrase matcher. Every LLM factory is patched; nothing touches the network.
"""
import unittest
from typing import Any
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agents import clinic
from agents.graph import build_graph
from agents.handoff import (
    AGENT_TO_NODE,
    HANDOFF_TOOL_NAMES,
    MAX_HANDOFFS_PER_TURN,
    apply_handoff,
    get_handoff_tools,
    handoff_destinations,
    handoff_prompt_section,
    handoff_target,
    split_handoff,
)
from agents.router import is_exit_request
from test_fakes import FakeKnowledgeBase, ScriptedChatModel, scripted, tool_call


class _Structured:
    """Minimal `with_structured_output` stand-in for the clinic LLM."""

    def __init__(self, schema, facts, recommendation):
        self._schema = schema
        self._facts = facts
        self._recommendation = recommendation

    async def ainvoke(self, _messages):
        if self._schema is clinic.SymptomFacts:
            return self._facts
        return self._recommendation


class _ClinicChatModel(ScriptedChatModel):
    """Scripted model that also answers the clinic's structured-output calls."""

    facts: Any = None
    recommendation: Any = None

    def with_structured_output(self, schema, **_kwargs):
        return _Structured(schema, self.facts, self.recommendation)


def _handoff_tool_message(agent_id: str, call_id: str = "call_1") -> ToolMessage:
    return ToolMessage(
        content='{"handoff": "%s", "reason": ""}' % agent_id,
        name=f"transfer_to_{agent_id.removesuffix('_agent')}",
        tool_call_id=call_id,
    )


# ─── Exit phrases ─────────────────────────────────────────────────────────────

class ExitRequestMatchingTests(unittest.TestCase):
    def test_bare_and_punctuated_exit_phrases_match(self):
        for text in (
            "退出",
            "结束",
            " 退出 ",
            "退出。",
            "取消！",
            "结束问诊",
            "退出问诊",
            "我要退出",
            "不看了",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_exit_request(text))

    def test_phrase_followed_by_punctuation_matches(self):
        self.assertTrue(is_exit_request("不用了，谢谢"))
        self.assertTrue(is_exit_request("退出，帮我回到首页"))

    def test_mid_sentence_occurrences_no_longer_exit(self):
        for text in (
            "我想取消明天的预约",
            "这个药不用了吗",
            "结束以后还要复查吗",
            "检查结束了医生让我看报告",
            "医保卡取消绑定要去哪里办",
            "退烧药该怎么吃",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_exit_request(text))

    def test_empty_and_punctuation_only_are_not_exits(self):
        self.assertFalse(is_exit_request(""))
        self.assertFalse(is_exit_request("   "))
        self.assertFalse(is_exit_request("。。。"))


# ─── Handoff plumbing ─────────────────────────────────────────────────────────

class HandoffToolTests(unittest.TestCase):
    def test_an_agent_never_gets_a_tool_pointing_at_itself(self):
        tools = get_handoff_tools("insurance_agent")
        names = {t.name for t in tools}
        self.assertEqual(len(tools), len(AGENT_TO_NODE) - 1)
        self.assertNotIn("transfer_to_insurance", names)
        self.assertIn("transfer_to_clinic", names)
        self.assertLessEqual(names, set(HANDOFF_TOOL_NAMES))

    def test_the_tool_returns_a_recognisable_payload(self):
        transfer = next(
            t for t in get_handoff_tools("advisor_agent") if t.name == "transfer_to_clinic"
        )
        raw = transfer.invoke({"reason": "用户在描述症状"})
        message = ToolMessage(content=raw, name="transfer_to_clinic", tool_call_id="x")
        self.assertEqual(handoff_target(message), "clinic_agent")

    def test_prompt_section_lists_only_the_other_agents(self):
        section = handoff_prompt_section("clinic_agent")
        self.assertNotIn("transfer_to_clinic", section)
        self.assertIn("transfer_to_insurance", section)

    def test_destinations_cover_every_other_node(self):
        self.assertEqual(
            set(handoff_destinations("report_agent")),
            {"clinic_node", "insurance_node", "pharmacy_node", "advisor_node"},
        )

    def test_non_handoff_messages_are_ignored(self):
        self.assertIsNone(handoff_target(AIMessage(content="hi")))
        self.assertIsNone(
            handoff_target(ToolMessage(content="{}", name="get_insurance_balance", tool_call_id="x"))
        )
        self.assertIsNone(
            handoff_target(
                ToolMessage(content="not json", name="transfer_to_clinic", tool_call_id="x")
            )
        )


class SplitHandoffTests(unittest.TestCase):
    def test_without_a_handoff_every_message_is_kept(self):
        messages = [AIMessage(content="您的余额是 3248.56 元。")]
        target, kept = split_handoff(messages)
        self.assertIsNone(target)
        self.assertEqual(kept, messages)

    def test_the_requesting_ai_message_and_everything_after_it_is_dropped(self):
        earlier = AIMessage(content="先查一下余额。")
        request = AIMessage(
            content="",
            tool_calls=[{"name": "transfer_to_clinic", "args": {}, "id": "call_9"}],
        )
        messages = [
            earlier,
            request,
            _handoff_tool_message("clinic_agent", "call_9"),
            AIMessage(content="好的，这就为您转接。"),
        ]
        target, kept = split_handoff(messages)
        self.assertEqual(target, "clinic_agent")
        self.assertEqual(kept, [earlier])

    def test_a_kept_prefix_never_ends_with_an_unanswered_tool_call(self):
        request = AIMessage(
            content="",
            tool_calls=[{"name": "transfer_to_report", "args": {}, "id": "call_1"}],
        )
        target, kept = split_handoff([request, _handoff_tool_message("report_agent")])
        self.assertEqual(target, "report_agent")
        self.assertEqual(kept, [])


class ApplyHandoffTests(unittest.TestCase):
    def test_plain_update_when_nothing_was_transferred(self):
        messages = [AIMessage(content="好的")]
        result = apply_handoff({}, messages)
        self.assertIsInstance(result, dict)
        self.assertEqual(result, {"messages": messages})

    def test_command_targets_the_agent_node_and_books_the_budget(self):
        request = AIMessage(
            content="",
            tool_calls=[{"name": "transfer_to_insurance", "args": {}, "id": "c1"}],
        )
        result = apply_handoff(
            {"handoff_count": 0},
            [request, _handoff_tool_message("insurance_agent", "c1")],
        )
        self.assertIsInstance(result, Command)
        self.assertEqual(result.goto, "insurance_node")
        self.assertEqual(result.update["active_agent"], "insurance_agent")
        self.assertEqual(result.update["next_agent"], "insurance_agent")
        self.assertEqual(result.update["handoff_count"], 1)
        self.assertEqual(result.update["messages"], [])

    def test_the_per_turn_budget_stops_ping_pong(self):
        request = AIMessage(
            content="",
            tool_calls=[{"name": "transfer_to_insurance", "args": {}, "id": "c1"}],
        )
        messages = [
            request,
            _handoff_tool_message("insurance_agent", "c1"),
            AIMessage(content="这就为您转接。"),
        ]
        result = apply_handoff({"handoff_count": MAX_HANDOFFS_PER_TURN}, messages)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["messages"], messages)

    def test_the_subgraph_variant_escapes_to_the_parent_graph(self):
        request = AIMessage(
            content="",
            tool_calls=[{"name": "transfer_to_pharmacy", "args": {}, "id": "c1"}],
        )
        prefix = AIMessage(content="症状我记下了。")
        result = apply_handoff(
            {"handoff_count": 0},
            [request, _handoff_tool_message("pharmacy_agent", "c1")],
            parent=True,
            prefix_messages=[prefix],
        )
        self.assertIsInstance(result, Command)
        self.assertEqual(result.graph, Command.PARENT)
        self.assertEqual(result.goto, "pharmacy_node")
        self.assertEqual(result.update["messages"], [prefix])


# ─── End-to-end through the master graph ──────────────────────────────────────

class _GraphHandoffCase(unittest.IsolatedAsyncioTestCase):
    """Helper base: runs the real master graph with scripted models."""

    async def _run(self, *, router_answer, models, messages, active_agent=""):
        app = build_graph(checkpointer=MemorySaver())
        patches = [
            patch(
                "agents.router.get_chat_llm",
                return_value=scripted(AIMessage(content=router_answer)),
            )
        ]
        for module, model in models.items():
            patches.append(patch(f"agents.{module}.get_chat_llm", return_value=model))

        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        return await app.ainvoke(
            {
                "messages": messages,
                "user_info": {},
                "next_agent": "",
                "active_agent": active_agent,
                "handoff_count": 0,
            },
            config={"configurable": {"thread_id": "handoff-test"}},
        )


class InsuranceToPharmacyHandoffTests(_GraphHandoffCase):
    async def test_a_locked_specialist_releases_an_off_topic_question(self):
        insurance = scripted(
            tool_call("transfer_to_pharmacy", {"reason": "用户在问药品"}, "c1"),
            AIMessage(content="好的，为您转接用药助手。"),
        )
        pharmacy = scripted(AIMessage(content="布洛芬成人每次 200-400mg。"))

        result = await self._run(
            router_answer="insurance_agent",
            models={"insurance": insurance, "pharmacy": pharmacy},
            messages=[HumanMessage(content="布洛芬一次吃多少？")],
            # The user was locked into insurance mode by a previous turn.
            active_agent="insurance_agent",
        )

        self.assertEqual(result["active_agent"], "pharmacy_agent")
        self.assertEqual(result["next_agent"], "pharmacy_agent")
        self.assertEqual(result["handoff_count"], 1)
        self.assertEqual(result["messages"][-1].content, "布洛芬成人每次 200-400mg。")
        # The handoff plumbing never leaks into the conversation history.
        self.assertFalse(
            any(handoff_target(message) for message in result["messages"])
        )
        self.assertNotIn(
            "好的，为您转接用药助手。",
            [getattr(m, "content", "") for m in result["messages"]],
        )

    async def test_a_second_handoff_in_the_same_turn_is_refused(self):
        insurance = scripted(
            tool_call("transfer_to_pharmacy", {}, "c1"),
            AIMessage(content="为您转接。"),
        )
        pharmacy = scripted(
            tool_call("transfer_to_insurance", {}, "c2"),
            AIMessage(content="这个还是医保的问题。"),
        )

        result = await self._run(
            router_answer="insurance_agent",
            models={"insurance": insurance, "pharmacy": pharmacy},
            messages=[HumanMessage(content="医保能报销布洛芬吗？")],
            active_agent="insurance_agent",
        )

        self.assertEqual(result["handoff_count"], 1)
        self.assertEqual(result["active_agent"], "pharmacy_agent")
        self.assertEqual(result["messages"][-1].content, "这个还是医保的问题。")
        # The insurance model was consulted exactly once (no bounce back).
        self.assertEqual(len(insurance.invocations), 2)


class ClinicHandoffTests(_GraphHandoffCase):
    async def test_a_handoff_into_the_clinic_subgraph_runs_the_interview(self):
        insurance = scripted(
            tool_call("transfer_to_clinic", {"reason": "用户在描述症状"}, "c1"),
            AIMessage(content="为您转接预问诊。"),
        )
        clinic_model = _ClinicChatModel(
            script=[AIMessage(content="建议到呼吸内科就诊。")],
            invocations=[],
            facts=clinic.SymptomFacts(
                chief_complaint="咳嗽", duration="三天", severity="轻微"
            ),
            recommendation=clinic.TriageRecommendation(
                department=["呼吸内科"],
                urgency="soon",
                summary="建议尽快就诊",
                notes=["多喝温水"],
            ),
        )

        with patch("agents.clinic.get_knowledge_base", return_value=FakeKnowledgeBase()):
            result = await self._run(
                router_answer="insurance_agent",
                models={"insurance": insurance, "clinic": clinic_model},
                messages=[HumanMessage(content="我咳嗽三天了，有点轻微")],
                active_agent="insurance_agent",
            )

        self.assertEqual(result["active_agent"], "clinic_agent")
        self.assertEqual(result["handoff_count"], 1)
        self.assertEqual(result["messages"][-1].content, "建议到呼吸内科就诊。")

    async def test_the_clinic_subgraph_hands_off_through_the_master_graph(self):
        clinic_model = _ClinicChatModel(
            script=[
                tool_call("transfer_to_pharmacy", {"reason": "用户想买药"}, "c1"),
                AIMessage(content="为您转接用药助手。"),
            ],
            invocations=[],
            facts=clinic.SymptomFacts(
                chief_complaint="头痛", duration="一天", severity="轻微"
            ),
            recommendation=clinic.TriageRecommendation(
                department=["神经内科"], urgency="routine"
            ),
        )
        pharmacy = scripted(AIMessage(content="布洛芬成人每次 200-400mg。"))

        with patch("agents.clinic.get_knowledge_base", return_value=FakeKnowledgeBase()):
            result = await self._run(
                router_answer="clinic_agent",
                models={"clinic": clinic_model, "pharmacy": pharmacy},
                messages=[HumanMessage(content="头痛吃什么药")],
            )

        self.assertEqual(result["active_agent"], "pharmacy_agent")
        self.assertEqual(result["handoff_count"], 1)
        self.assertEqual(result["messages"][-1].content, "布洛芬成人每次 200-400mg。")
        self.assertFalse(any(handoff_target(m) for m in result["messages"]))

    async def test_the_clinic_conclude_node_escapes_to_the_parent_graph(self):
        model = scripted(
            tool_call("transfer_to_pharmacy", {"reason": "用户想买药"}, "c1"),
            AIMessage(content="为您转接用药助手。"),
        )
        state = {
            "messages": [HumanMessage(content="布洛芬能和阿司匹林一起吃吗")],
            "user_info": {},
            "collected": {"chief_complaint": "头痛", "duration": "一天", "severity": "轻微"},
            "turn_messages": [],
            "handoff_count": 0,
            "emergency_level": "NON_URGENT",
        }

        with patch("agents.clinic.get_chat_llm", return_value=model), patch(
            "agents.clinic.get_knowledge_base", return_value=FakeKnowledgeBase()
        ):
            result = await clinic.conclude(state)

        self.assertIsInstance(result, Command)
        self.assertEqual(result.graph, Command.PARENT)
        self.assertEqual(result.goto, "pharmacy_node")
        self.assertEqual(result.update["active_agent"], "pharmacy_agent")


if __name__ == "__main__":
    unittest.main()
