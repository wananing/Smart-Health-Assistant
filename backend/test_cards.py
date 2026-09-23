"""
Deterministic tests for agent-owned `card` SSE events.

Since v2.1.0 `main.py` no longer maps tool names to card types: every
card-producing tool (or its agent node) pushes the payload itself through
`agents.streaming`, and `_stream_agent_events` forwards the `custom` stream
verbatim. These tests pin both the payloads and their position in the stream.
"""
import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

import main
from agents import insurance, pharmacy, report
from agents.graph import build_graph
from test_fakes import scripted, tool_call


def _parse_sse(chunks: list[str]) -> list[dict]:
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


class MainIsToolNameAgnosticTests(unittest.TestCase):
    def test_the_tool_name_to_card_type_maps_are_gone(self):
        for attribute in (
            "_INSURANCE_TOOL_TO_CARD_TYPE",
            "_REPORT_TOOL_TO_CARD_TYPE",
            "PHARMACY_TOOL_TO_CARD_TYPE",
        ):
            self.assertFalse(hasattr(main, attribute), attribute)

    def test_the_ui_label_tables_are_still_there(self):
        self.assertIn("get_insurance_balance", main._SKILL_LABELS)
        self.assertIn("insurance_node", main._NODE_LABELS)

    def test_only_card_and_text_may_come_off_the_custom_stream(self):
        self.assertEqual(main._STREAMABLE_CUSTOM_TYPES, {"card", "text"})


class ToolLevelEmissionTests(unittest.TestCase):
    def test_insurance_tools_emit_their_own_cards(self):
        emitted: list[tuple] = []
        with patch.object(insurance, "emit_card", side_effect=lambda *a: emitted.append(a)):
            insurance.get_insurance_balance.invoke({})
            insurance.get_consumption_records.invoke({"months": 3})
            insurance.get_payment_records.invoke({"months": 6})
            insurance.get_cross_region_info.invoke({})

        self.assertEqual(
            [card_type for card_type, _ in emitted],
            [
                "insurance_balance",
                "insurance_expenses",
                "insurance_payments",
                "insurance_cross_region",
            ],
        )
        self.assertIn("personal_account", emitted[0][1])

    def test_pharmacy_tools_emit_their_own_cards(self):
        emitted: list[tuple] = []
        with patch.object(pharmacy, "emit_card", side_effect=lambda *a: emitted.append(a)):
            pharmacy.find_nearby_pharmacy.invoke({"location": "中关村"})
        self.assertEqual(emitted[0][0], "hospital_list")
        self.assertIn("pharmacies", emitted[0][1])

    def test_emitting_outside_a_graph_run_is_a_no_op(self):
        # No writer is installed here, so the tool must still return normally.
        raw = insurance.get_insurance_balance.invoke({})
        self.assertIn("personal_account", json.loads(raw))


class ReportNodeCardTests(unittest.TestCase):
    def test_lab_interpreter_results_become_report_analysis_cards(self):
        payload = {"skill_name": "lab_interpreter", "success": True, "results": []}
        messages = [
            AIMessage(content="先解读一下。"),
            ToolMessage(
                content=json.dumps(payload),
                name="lab_interpreter",
                tool_call_id="c1",
            ),
            ToolMessage(content="{}", name="load_skill", tool_call_id="c2"),
            ToolMessage(content="not json", name="lab_interpreter", tool_call_id="c3"),
        ]

        emitted: list[tuple] = []
        with patch.object(report, "emit_card", side_effect=lambda *a: emitted.append(a)):
            report._emit_report_cards(messages)

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0], ("report_analysis", payload))


class InsuranceSseSequenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_card_lands_after_the_tool_and_before_the_summary(self):
        app = build_graph(checkpointer=MemorySaver())
        router_model = scripted(AIMessage(content="insurance_agent"))
        insurance_model = scripted(
            tool_call("get_insurance_balance", {}, "c1"),
            AIMessage(content="您的个人账户还有 3248.56 元。"),
        )

        state = {
            "messages": [HumanMessage(content="我医保卡里还有多少钱？")],
            "user_info": {},
            "next_agent": "",
            "active_agent": "",
            "handoff_count": 0,
        }

        with patch.object(main, "_master_app", app), patch(
            "agents.router.get_chat_llm", return_value=router_model
        ), patch("agents.insurance.get_chat_llm", return_value=insurance_model):
            chunks = [
                payload
                async for payload in main._stream_agent_events(
                    state, {"configurable": {"thread_id": "cards-test"}}
                )
            ]

        events = _parse_sse(chunks)
        kinds = [
            f"{event['type']}:{event.get('tool') or event.get('node') or ''}"
            for event in events
        ]

        card_index = next(i for i, e in enumerate(events) if e["type"] == "card")
        tool_end_index = kinds.index("tool_end:get_insurance_balance")
        summary_index = next(
            i
            for i, event in enumerate(events)
            if event["type"] == "text" and "3248.56" in event.get("content", "")
        )

        self.assertLess(tool_end_index, card_index, kinds)
        self.assertLess(card_index, summary_index, kinds)

        card = events[card_index]["payload"]
        self.assertEqual(card["type"], "insurance_balance")
        self.assertIn("personal_account", card["data"])
        self.assertEqual(events[-1]["type"], "finish")

    async def test_a_tool_without_a_card_produces_no_card_event(self):
        app = build_graph(checkpointer=MemorySaver())
        router_model = scripted(AIMessage(content="insurance_agent"))
        insurance_model = scripted(
            tool_call("search_insurance_policy", {"query": "门诊报销比例"}, "c1"),
            AIMessage(content="门诊报销比例一般是 50%-70%。"),
        )

        state = {
            "messages": [HumanMessage(content="门诊能报多少？")],
            "user_info": {},
            "next_agent": "",
            "active_agent": "",
            "handoff_count": 0,
        }

        class _EmptyKb:
            async def aretrieve(self, _query, k=3):
                return []

            def format_context(self, _docs):
                return ""

        with patch.object(main, "_master_app", app), patch(
            "agents.router.get_chat_llm", return_value=router_model
        ), patch("agents.insurance.get_chat_llm", return_value=insurance_model), patch(
            "agents.insurance.get_knowledge_base", return_value=_EmptyKb()
        ):
            chunks = [
                payload
                async for payload in main._stream_agent_events(
                    state, {"configurable": {"thread_id": "cards-test-2"}}
                )
            ]

        events = _parse_sse(chunks)
        self.assertFalse([event for event in events if event["type"] == "card"])
        self.assertIn("tool_end", [event["type"] for event in events])


if __name__ == "__main__":
    unittest.main()
