"""
Turn model, endpointing and watchdog timings.

Call state:   listening → (committed) → thinking → speaking → listening
              plus ``emergency``, which only a tap on "我没事，继续问诊" leaves.

Every turn has an integer ``turn_id`` and must end in exactly one terminal
outcome: ``done`` / ``interrupted`` / ``error`` / ``superseded``.

Turn boundaries are one kind of event, ``turn.end{source}``, whatever made
them: server endpointing (``vad``), the "说完了" button (``button``), typed
input (``text``) or a screen action (``ui``).

Endpointing = the ASR's silence event + an adaptive wait. A partial that
sounds unfinished (ends in 然后 / 还有 / 就是 / 那个, or has fewer than 3
characters) earns the longer wait. The numbers are starting points to tune
on real samples; a semantic end-of-turn model can replace
``looks_unfinished`` later without touching the gateway.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Literal

CallState = Literal["listening", "thinking", "speaking", "emergency"]
TurnOutcome = Literal["done", "interrupted", "error", "superseded"]

UNFINISHED_SUFFIXES: tuple[str, ...] = ("然后", "还有", "就是", "那个", "而且", "但是", "所以")
_PUNCT = " \t　，,。.！!？?；;、~～…·"


@dataclass(frozen=True)
class VoiceTimings:
    """All call timers, in seconds. Tests scale these down."""

    endpoint_min: float = 0.6
    endpoint_max: float = 2.5
    elder_endpoint_min: float = 1.0
    elder_endpoint_max: float = 3.0
    idle_prompt: float = 8.0         # listening with no voice → "您还在吗"
    idle_end: float = 20.0           # … then this much more → polite hang-up
    # No quick acknowledgement ("好的"): it sounded mechanical in testing. Only a
    # long silent run (in practice the conclusion) gets "我还在整理建议", repeated.
    filler_after: float = 8.0
    filler_repeat: float = 8.0
    graph_stall: float = 20.0        # no graph event for this long → give up
    graph_max: float = 120.0         # hard cap on one graph run, progress or not
    barge_in_min_speech: float = 0.3 # voice must last this long to interrupt
    protect_window: float = 0.5      # no barge-in during a sentence's first 0.5 s
    hello_timeout: float = 10.0
    flush_timeout: float = 1.5       # waiting for the ASR's last final
    playback_grace: float = 1.5      # extra wait for playback.ended
    audio_lead: float = 0.3          # send audio at most this far ahead of real time

    def scaled(self, factor: float) -> "VoiceTimings":
        return replace(
            self,
            **{name: getattr(self, name) * factor for name in self.__dataclass_fields__},
        )


def looks_unfinished(text: str) -> bool:
    core = text.strip().rstrip(_PUNCT)
    if len(re.sub(f"[{re.escape(_PUNCT)}]", "", core)) < 3:
        return True
    return core.endswith(UNFINISHED_SUFFIXES)


def endpoint_wait(text: str, timings: VoiceTimings, *, elder_mode: bool) -> float:
    """How long to wait after silence before committing the turn."""
    unfinished = looks_unfinished(text)
    if elder_mode:
        return timings.elder_endpoint_max if unfinished else timings.elder_endpoint_min
    return timings.endpoint_max if unfinished else timings.endpoint_min


@dataclass
class TurnTrace:
    """
    Per-turn trace record: durations, enums and ids only — never text.

    Mirrors the design's observability list: endpoint wait and source, ASR
    final latency and confidence, time to first sound vs. first content,
    speak_mode, outcome, interruption, played vs. generated audio, repeats,
    error class and degradation.
    """

    turn_id: int
    source: str = "system"
    endpoint_wait_ms: int | None = None
    asr_final_ms: int | None = None
    asr_confidence: float | None = None
    first_sound_ms: int | None = None
    first_content_ms: int | None = None
    speak_mode: str = "none"
    outcome: TurnOutcome | None = None
    interrupted: bool = False
    played_ms: int = 0
    generated_ms: int = 0
    repeat_count: int = 0
    error_class: str | None = None
    degraded: bool = False
    committed_at: float | None = field(default=None, repr=False)

    def finish(self, outcome: TurnOutcome) -> bool:
        """Set the terminal outcome once; later calls are ignored."""
        if self.outcome is not None:
            return False
        self.outcome = outcome
        if outcome == "interrupted":
            self.interrupted = True
        return True

    def log_line(self) -> str:
        return (
            f"--- [Voice] turn={self.turn_id} source={self.source} outcome={self.outcome} "
            f"speak={self.speak_mode} endpoint_ms={self.endpoint_wait_ms} "
            f"asr_ms={self.asr_final_ms} first_sound_ms={self.first_sound_ms} "
            f"first_content_ms={self.first_content_ms} interrupted={self.interrupted} "
            f"played_ms={self.played_ms} generated_ms={self.generated_ms} "
            f"repeats={self.repeat_count} error={self.error_class} degraded={self.degraded} ---"
        )


class NoHearLadder:
    """
    Escalation for empty / low-confidence finals, which never enter the graph:
    1st → "没听清，再说一遍", 2nd → suggest the button or typing,
    3rd → switch the client to push-to-talk. Elder mode starts at the button.
    """

    STEPS = ("not_heard", "not_heard_button", "push_to_talk")

    def __init__(self, *, elder_mode: bool) -> None:
        self._count = 1 if elder_mode else 0
        self._start = self._count

    def next_step(self) -> str:
        step = self.STEPS[min(self._count, len(self.STEPS) - 1)]
        self._count += 1
        return step

    def reset(self) -> None:
        self._count = self._start
