import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from evals import EvalCase, EvalRun, evaluate_run, extract_eval_run, load_cases


class EvaluationContractTests(unittest.TestCase):
    def test_case_ids_must_be_anonymous_machine_safe_labels(self):
        with self.assertRaisesRegex(ValueError, "case id"):
            EvalCase.from_mapping(
                {
                    "id": "patient-张三",
                    "input": "测试输入",
                    "expected_agent": "advisor_agent",
                }
            )

    def test_load_cases_parses_optional_expected_tools(self):
        rows = [
            {
                "id": "report-lab",
                "input": "白细胞 12.0，请解读",
                "expected_agent": "report_agent",
                "expected_tools": ["lab_interpreter"],
            },
            {
                "id": "general-sleep",
                "input": "如何改善睡眠？",
                "expected_agent": "advisor_agent",
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                encoding="utf-8",
            )
            cases = load_cases(path)

        self.assertEqual(cases[0].expected_tools, ("lab_interpreter",))
        self.assertIsNone(cases[1].expected_tools)

    def test_local_score_requires_the_expected_route_and_exact_tool_set(self):
        case = EvalCase(
            id="report-lab",
            input="白细胞 12.0，请解读",
            expected_agent="report_agent",
            expected_tools=("lab_interpreter",),
        )

        passing = evaluate_run(
            case,
            EvalRun(
                case_id=case.id,
                actual_agent="report_agent",
                actual_output="白细胞偏高。",
                tools_called=("lab_interpreter",),
            ),
        )
        extra_tool = evaluate_run(
            case,
            EvalRun(
                case_id=case.id,
                actual_agent="report_agent",
                actual_output="白细胞偏高。",
                tools_called=("lab_interpreter", "load_skill"),
            ),
        )

        self.assertTrue(passing.passed)
        self.assertEqual(passing.route_score, 1.0)
        self.assertEqual(passing.tool_score, 1.0)
        self.assertFalse(extra_tool.passed)
        self.assertEqual(extra_tool.tool_score, 0.5)

    def test_cases_without_tool_expectations_only_score_routing(self):
        case = EvalCase(
            id="general-sleep",
            input="如何改善睡眠？",
            expected_agent="advisor_agent",
        )
        score = evaluate_run(
            case,
            EvalRun(
                case_id=case.id,
                actual_agent="advisor_agent",
                actual_output="保持规律作息。",
                tools_called=("risk_assessor",),
            ),
        )

        self.assertTrue(score.passed)
        self.assertIsNone(score.tool_score)

    def test_extract_run_collects_completed_tools_without_double_counting(self):
        case = EvalCase(
            id="report-lab",
            input="白细胞 12.0，请解读",
            expected_agent="report_agent",
            expected_tools=("lab_interpreter",),
        )
        state = {
            "active_agent": "report_agent",
            "messages": [
                HumanMessage(content=case.input),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "lab_interpreter",
                            "args": {"values": []},
                            "id": "call-1",
                        }
                    ],
                ),
                ToolMessage(
                    content="{}",
                    name="lab_interpreter",
                    tool_call_id="call-1",
                ),
                AIMessage(content="白细胞偏高，建议结合症状复查。"),
            ],
        }

        run = extract_eval_run(case, state)

        self.assertEqual(run.actual_agent, "report_agent")
        self.assertEqual(run.tools_called, ("lab_interpreter",))
        self.assertIn("建议", run.actual_output)


if __name__ == "__main__":
    unittest.main()
