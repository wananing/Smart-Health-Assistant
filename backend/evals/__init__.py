"""Small, provider-neutral evaluation contract for agent regression tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage


_CASE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


@dataclass(frozen=True)
class EvalCase:
    id: str
    input: str
    expected_agent: str
    expected_tools: tuple[str, ...] | None = None
    chat_mode: str = "general"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EvalCase":
        required = ("id", "input", "expected_agent")
        missing = [name for name in required if not str(data.get(name, "")).strip()]
        if missing:
            raise ValueError(f"missing required eval fields: {', '.join(missing)}")

        case_id = str(data["id"]).strip()
        if _CASE_ID_PATTERN.fullmatch(case_id) is None:
            raise ValueError(
                "case id must use 1-64 lowercase letters, digits, hyphens, or "
                "underscores"
            )

        raw_tools = data.get("expected_tools")
        if raw_tools is not None and not isinstance(raw_tools, list):
            raise ValueError("expected_tools must be a JSON array when provided")
        tools = None
        if raw_tools is not None:
            tools = tuple(str(tool).strip() for tool in raw_tools if str(tool).strip())

        return cls(
            id=case_id,
            input=str(data["input"]).strip(),
            expected_agent=str(data["expected_agent"]).strip(),
            expected_tools=tools,
            chat_mode=str(data.get("chat_mode", "general")).strip() or "general",
        )


@dataclass(frozen=True)
class EvalRun:
    case_id: str
    actual_agent: str
    actual_output: str
    tools_called: tuple[str, ...]


@dataclass(frozen=True)
class EvalScore:
    case_id: str
    route_score: float
    tool_score: float | None
    passed: bool


def load_cases(path: str | Path) -> list[EvalCase]:
    dataset_path = Path(path)
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("each row must be a JSON object")
            case = EvalCase.from_mapping(data)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(
                f"invalid eval case at {dataset_path}:{line_number}: {exc}"
            ) from exc
        if case.id in seen_ids:
            raise ValueError(f"duplicate eval case id: {case.id}")
        seen_ids.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError(f"eval dataset is empty: {dataset_path}")
    return cases


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                chunks.append(block["text"])
        return "".join(chunks)
    return str(content) if content is not None else ""


def extract_eval_run(case: EvalCase, state: Mapping[str, Any]) -> EvalRun:
    messages = state.get("messages", ())
    completed_tools = tuple(
        message.name
        for message in messages
        if isinstance(message, ToolMessage) and message.name
    )
    if not completed_tools:
        completed_tools = tuple(
            str(call.get("name", ""))
            for message in messages
            if isinstance(message, AIMessage)
            for call in message.tool_calls
            if call.get("name")
        )

    actual_output = next(
        (
            _message_text(message.content)
            for message in reversed(messages)
            if isinstance(message, AIMessage) and _message_text(message.content).strip()
        ),
        "",
    )
    return EvalRun(
        case_id=case.id,
        actual_agent=str(
            state.get("active_agent") or state.get("next_agent") or ""
        ),
        actual_output=actual_output,
        tools_called=completed_tools,
    )


def evaluate_run(case: EvalCase, run: EvalRun) -> EvalScore:
    if run.case_id != case.id:
        raise ValueError(
            f"eval case mismatch: expected {case.id}, received {run.case_id}"
        )

    route_score = float(run.actual_agent == case.expected_agent)
    tool_score: float | None = None
    if case.expected_tools is not None:
        expected = set(case.expected_tools)
        actual = set(run.tools_called)
        union = expected | actual
        tool_score = 1.0 if not union else len(expected & actual) / len(union)

    passed = route_score == 1.0 and (tool_score is None or tool_score == 1.0)
    return EvalScore(
        case_id=case.id,
        route_score=route_score,
        tool_score=tool_score,
        passed=passed,
    )


def evaluate_tools_with_deepeval(case: EvalCase, run: EvalRun) -> float | None:
    if case.expected_tools is None:
        return None
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
    try:
        from deepeval.metrics import ToolCorrectnessMetric
        from deepeval.test_case import LLMTestCase, ToolCall
        from evals.deepeval_adapter import ProjectEvaluationModel
    except ImportError as exc:
        raise RuntimeError(
            "DeepEval is not installed; run `uv sync --extra eval` in backend/"
        ) from exc

    test_case = LLMTestCase(
        input=case.input,
        actual_output=run.actual_output,
        tools_called=[ToolCall(name=name) for name in run.tools_called],
        expected_tools=[ToolCall(name=name) for name in case.expected_tools],
    )
    metric = ToolCorrectnessMetric(
        threshold=1.0,
        model=ProjectEvaluationModel(),
        include_reason=False,
        should_exact_match=True,
    )
    metric.measure(test_case)
    return float(metric.score or 0.0)


__all__ = [
    "EvalCase",
    "EvalRun",
    "EvalScore",
    "evaluate_run",
    "evaluate_tools_with_deepeval",
    "extract_eval_run",
    "load_cases",
]
