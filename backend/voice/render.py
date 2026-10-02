"""
Graph events → what goes on screen and what gets spoken.

Everything reaches the screen unchanged; this module only decides the spoken
subset (``speak_mode``) and makes it safe to say:

| turn                         | spoken                                              |
| ---------------------------- | --------------------------------------------------- |
| interrupt kind=followup      | the question as written (clinic keeps it ≤ 40 字)   |
| interrupt kind=confirm       | the template read-back                              |
| conclusion                   | recommendation.summary + 详细建议在屏幕上 + 免责    |
| handoff to another specialist| cue "这个问题我在屏幕上回答您"                      |

Every spoken sentence passes ``pre_speech_check`` (rules, synchronous): markdown
and emoji stripped, numbers/units/"120" normalised to their reading, no
absolute-diagnosis wording, and a conclusion must carry the disclaimer. A
failure means "screen only": the call says the ``see_screen`` cue instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

SpeakMode = Literal[
    "question", "confirm", "conclusion", "handoff", "see_screen", "skipped", "cue", "safety", "none"
]

SCREEN_POINTER = "详细建议在屏幕上。"
DISCLAIMER = "以上仅供参考，不能代替医生面诊。"

# Absolute-diagnosis wording the clinic prompt already forbids; if it slips
# through, it may be shown but never spoken.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "您得了", "你得了", "确诊", "您患有", "你患有", "诊断为", "肯定是", "一定是",
)
# Hedges that contain a forbidden phrase but say the opposite
# ("以医生诊断为准" = "the doctor's diagnosis decides"). Measured live: the
# model ends most summaries this way.
_HEDGES = re.compile(r"(诊断为准|确诊为准|诊断结果为准|确诊需)")

MAX_SPOKEN_CHARS = 160


@dataclass(frozen=True)
class SpeechPlan:
    speak_mode: SpeakMode
    sentences: tuple[str, ...] = ()
    cue_id: str | None = None
    interruptible: bool = True
    reason: str = ""


@dataclass(frozen=True)
class SpeechCheck:
    ok: bool
    text: str
    reason: str = ""


# ─── Text normalisation ───────────────────────────────────────────────────────

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U0000FE0F\U0000200D\U000020E3]"
)
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_QUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_MD_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_MD_MARKS = re.compile(r"(\*\*|__|\*|`+|~~)")

_UNITS = {
    "mmHg": "毫米汞柱",
    "mg": "毫克",
    "kg": "公斤",
    "ml": "毫升",
    "mL": "毫升",
    "cm": "厘米",
    "g": "克",
    "℃": "摄氏度",
    "°C": "摄氏度",
}
_UNIT_RE = re.compile(r"(?<=\d)\s*(mmHg|mg|kg|mL|ml|cm|°C|℃|g)(?![A-Za-z])")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~～—]\s*(\d+(?:\.\d+)?)")
# 120/110/119 are read digit by digit (幺二零) only when the context makes
# them a phone number: after a calling word ("拨打120", "急救电话120",
# "报警请打110") or right before 急救/救护车/报警/火警. Everywhere else —
# doses, heart rates, ranges, counts — they are ordinary numbers.
_HOTLINE_BEFORE_RE = re.compile(
    r"(?P<pre>(?:拨打|拨|打|呼叫|叫|急救电话|报警电话|火警电话|电话|报警|火警|急救)(?:电话)?(?:是|为)?\s*)"
    r"(?P<num>120|110|119)(?![\d.%/])"
)
_HOTLINE_AFTER_RE = re.compile(r"(?<![\d.\-~～—/])(?P<num>120|110|119)(?=\s*(?:急救|救护车|报警|火警))")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_YEAR_RE = re.compile(r"(?<![\d.])(\d{4})(?=年)")

_DIGITS = "零一二三四五六七八九"
_HOTLINE_DIGITS = "零幺二三四五六七八九"


def _small_int_to_zh(n: int) -> str:
    """0 < n < 10000."""
    units = ((1000, "千"), (100, "百"), (10, "十"), (1, ""))
    out: list[str] = []
    zero_pending = False
    for value, unit in units:
        digit = n // value % 10
        if digit == 0:
            if out:
                zero_pending = True
            continue
        if zero_pending:
            out.append("零")
            zero_pending = False
        out.append(_DIGITS[digit] + unit)
    return "".join(out)


def int_to_zh(n: int) -> str:
    """Read an integer the way it is spoken: 15 → 十五, 305 → 三百零五."""
    if n == 0:
        return "零"
    if n >= 100_000_000:
        return "".join(_DIGITS[int(d)] for d in str(n))
    high, low = divmod(n, 10_000)
    text = ""
    if high:
        text = _small_int_to_zh(high) + "万"
        if low and low < 1000:
            text += "零"
    if low:
        text += _small_int_to_zh(low)
    if text.startswith("一十"):
        text = text[1:]
    return text


def read_number(token: str) -> str:
    whole, _, fraction = token.partition(".")
    # Long digit strings are codes or phone numbers: read digit by digit.
    if len(whole) >= 5 and not fraction:
        return "".join(_DIGITS[int(d)] for d in whole)
    spoken = int_to_zh(int(whole))
    if fraction:
        spoken += "点" + "".join(_DIGITS[int(d)] for d in fraction)
    return spoken


def strip_markup(text: str) -> str:
    text = _EMOJI.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    text = _MD_QUOTE.sub("", text)
    text = _MD_BULLET.sub("", text)
    text = _MD_MARKS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_speech(text: str) -> str:
    """Strip markup and emoji, then spell numbers, units and hotlines as read."""
    text = strip_markup(text)
    def hotline(number: str) -> str:
        return "".join(_HOTLINE_DIGITS[int(d)] for d in number)

    text = _HOTLINE_BEFORE_RE.sub(lambda m: m.group("pre") + hotline(m.group("num")), text)
    text = _HOTLINE_AFTER_RE.sub(lambda m: hotline(m.group("num")), text)
    text = _PERCENT_RE.sub(lambda m: "百分之" + read_number(m.group(1)), text)
    text = _RANGE_RE.sub(lambda m: f"{m.group(1)}到{m.group(2)}", text)
    text = _UNIT_RE.sub(lambda m: _UNITS[m.group(1)], text)
    text = _YEAR_RE.sub(lambda m: "".join(_DIGITS[int(d)] for d in m.group(1)), text)
    text = _NUMBER_RE.sub(lambda m: read_number(m.group(0)), text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    """Split on sentence-final punctuation, keeping the punctuation."""
    parts = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
    return [part.strip() for part in parts if part.strip()]


def pre_speech_check(text: str, *, requires_disclaimer: bool = False) -> SpeechCheck:
    """Rule-based gate every spoken sentence passes before TTS."""
    spoken = normalize_for_speech(text)
    if not spoken:
        return SpeechCheck(False, "", "empty")
    unhedged = _HEDGES.sub("", spoken)
    for phrase in FORBIDDEN_PHRASES:
        if phrase in unhedged:
            return SpeechCheck(False, spoken, "absolute_diagnosis")
    if requires_disclaimer and DISCLAIMER not in spoken:
        return SpeechCheck(False, spoken, "missing_disclaimer")
    if len(spoken) > MAX_SPOKEN_CHARS:
        return SpeechCheck(False, spoken, "too_long")
    return SpeechCheck(True, spoken)


# ─── Plans per turn type ──────────────────────────────────────────────────────

def _checked(speak_mode: SpeakMode, text: str, *, requires_disclaimer: bool = False) -> SpeechPlan:
    check = pre_speech_check(text, requires_disclaimer=requires_disclaimer)
    if not check.ok:
        return SpeechPlan("see_screen", cue_id="see_screen", reason=check.reason)
    return SpeechPlan(speak_mode, tuple(split_sentences(check.text)))


def plan_interrupt(kind: str, question: str) -> SpeechPlan:
    """Follow-up or read-back: say the question itself."""
    return _checked("confirm" if kind == "confirm" else "question", question)


def plan_conclusion(recommendation: dict) -> SpeechPlan:
    """One spoken line from the structured summary — the same source as the card."""
    summary = str(recommendation.get("summary") or "").strip()
    if not summary:
        return SpeechPlan("see_screen", cue_id="see_screen", reason="no_summary")
    if summary[-1] not in "。！？!?":
        summary += "。"
    return _checked("conclusion", f"{summary}{SCREEN_POINTER}{DISCLAIMER}", requires_disclaimer=True)


def plan_handoff() -> SpeechPlan:
    return SpeechPlan("handoff", cue_id="handoff")


class LeadCutter:
    """
    Cuts the spoken lead (first sentence) off the streaming conclusion text.

    ``feed`` returns None while undecided, then exactly once either a
    ``SpeechPlan`` with ``speak_mode="conclusion"`` (speak it now) or one with
    ``speak_mode="see_screen"`` meaning "no usable lead — fall back to the
    structured summary after the card". The sentence must come within
    ``MAX_SPOKEN_LEAD_CHARS``, name a department (or the emergency), and pass
    ``pre_speech_check`` together with the screen pointer and disclaimer.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self.done = False
        self.sentence = ""

    def feed(self, chunk: str) -> SpeechPlan | None:
        if self.done:
            return None
        from agents.clinic import MAX_SPOKEN_LEAD_CHARS, extract_spoken_lead

        self._buffer += chunk
        lead = extract_spoken_lead(self._buffer)
        if not lead:
            stripped = self._buffer.lstrip()
            if stripped.startswith(("#", "-", "*", "|", ">")) or len(stripped) > MAX_SPOKEN_LEAD_CHARS:
                return self._fail("no_lead")
            return None
        self.done = True
        self.sentence = lead
        plain = strip_markup(lead)
        if len(plain) < 6 or not any(word in plain for word in ("科", "急诊", "120", "医院")):
            return self._fail("not_a_conclusion")
        plan = plan_conclusion({"summary": plain})
        return plan if plan.speak_mode == "conclusion" else self._fail(plan.reason or "check_failed")

    def _fail(self, reason: str) -> SpeechPlan:
        self.done = True
        return SpeechPlan("see_screen", reason=reason)


@dataclass
class RunOutcome:
    """What one graph run produced, as far as speaking is concerned."""

    interrupt_kind: str | None = None
    interrupt_question: str = ""
    recommendation: dict | None = None
    handed_off: bool = False
    error: str | None = None
    specialist_nodes: list[str] = field(default_factory=list)


def plan_for_outcome(outcome: RunOutcome) -> SpeechPlan:
    if outcome.interrupt_kind is not None:
        return plan_interrupt(outcome.interrupt_kind, outcome.interrupt_question)
    if outcome.recommendation:
        return plan_conclusion(outcome.recommendation)
    if outcome.handed_off:
        return plan_handoff()
    return SpeechPlan("see_screen", cue_id="see_screen", reason="no_spoken_content")
