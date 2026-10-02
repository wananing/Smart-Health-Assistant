"""
Rule shortcuts that run on every committed utterance BEFORE the graph.

Exits are triggered by rules, not by the model: an emergency, hanging up and
"再说一遍" never depend on an LLM deciding to cooperate. All checks are pure
and take microseconds.

Order matters and is fixed in ``classify``:

1. emergency  — ``EmergencyTriageSkill`` (the same rules as the clinic's
                ``emergency_gate``), so the call can cut playback and take
                over the screen before the graph even returns. The utterance
                still goes into the graph so the transcript and card agree.
2. exit       — ``router.is_exit_request``: end the call, never sent to the graph.
3. repeat     — "再说一遍 / 没听清": replay the last spoken sentence locally.
4. otherwise  — an ordinary utterance for the graph.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from agents.clinic import is_affirmative_answer
from agents.router import is_exit_request
from skills.emergency_triage.skill import EmergencyTriageSkill

ShortcutKind = Literal["emergency", "exit", "repeat", "graph"]

REPEAT_PHRASES = frozenset(
    {
        "再说一遍", "再说一次", "你再说一遍", "您再说一遍", "请再说一遍", "麻烦再说一遍",
        "没听清", "没听清楚", "我没听清", "我没听清楚", "刚才说什么", "你说什么",
        "您说什么", "什么", "啥", "重复一下", "重复一遍", "再讲一遍", "听不清",
    }
)
_BOUNDARY = " \t　，,。.！!？?；;、~～…·"
_PARTICLES = "啊呀吧呢嘛哈"

# Back-channel noises that must not count as a barge-in.
BACKCHANNEL_CHARS = frozenset("嗯哦噢喔好对啊哎诶唔呃嗯是")


@dataclass(frozen=True)
class Shortcut:
    kind: ShortcutKind
    emergency_flags: tuple[str, ...] = field(default=())


def _core(text: str) -> str:
    return text.strip().strip(_BOUNDARY).rstrip(_PARTICLES).strip(_BOUNDARY)


def is_repeat_request(text: str) -> bool:
    """Anchored: the whole utterance must be a repeat phrase (plus particles)."""
    core = _core(text)
    return bool(core) and core in REPEAT_PHRASES


def is_backchannel(text: str) -> bool:
    """True for 嗯 / 哦 / 好的 / 对对 … — acknowledgements, not interruptions."""
    core = re.sub(f"[{re.escape(_BOUNDARY)}]", "", text)
    return bool(core) and all(char in BACKCHANNEL_CHARS | {"的"} for char in core)


def meaningful_length(text: str) -> int:
    return len(re.sub(f"[{re.escape(_BOUNDARY)}]", "", text))


def detect_emergency(text: str, age: int | None = None) -> tuple[str, ...] | None:
    """Red-flag flags when the rules say CRITICAL, else None."""
    result = EmergencyTriageSkill().run(symptoms_text=text, age=age)
    if result.level != "CRITICAL":
        return None
    return tuple(result.triggered_flags) or ("危急症状",)


def classify(text: str, *, age: int | None = None) -> Shortcut:
    flags = detect_emergency(text, age)
    if flags is not None:
        return Shortcut("emergency", flags)
    if is_exit_request(text):
        return Shortcut("exit")
    if is_repeat_request(text):
        return Shortcut("repeat")
    return Shortcut("graph")


__all__ = [
    "Shortcut",
    "classify",
    "detect_emergency",
    "is_affirmative_answer",
    "is_backchannel",
    "is_repeat_request",
    "meaningful_length",
]
