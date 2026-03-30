"""
Skill: emergency_triage

Fast, deterministic safety gate — zero LLM involvement, pure rule-matching.
Must be the FIRST skill called in clinic_agent when any symptom is reported.

Returns a mandatory safety level (CRITICAL / URGENT / PROMPT / NON_URGENT)
and a pre-written safety message that the agent must display verbatim.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from skills.base import BaseSkill, SkillOutput


# ─── Red-flag pattern library ─────────────────────────────────────────────────

_CRITICAL_PATTERNS = [
    (r"剧烈胸痛|胸口剧痛|压榨性.*胸痛|胸痛.*大汗|心梗", "疑似急性心梗"),
    (r"呼吸困难|喘不过气|透不过气|窒息感|憋气.*严重", "严重呼吸困难"),
    (r"意识丧失|昏迷|昏厥|不省人事|叫不醒", "意识障碍"),
    (r"大量出血|喷血|血流不止|吐血.*大量|便血.*大量", "大出血"),
    (r"口眼歪斜|半身不遂|突然.*说不出话|手臂无力.*突然|卒中|脑梗", "疑似卒中（FAST阳性）"),
    (r"雷击.*头痛|突发.*最剧烈.*头痛|蛛网膜", "雷击样头痛（蛛网膜下腔出血）"),
    (r"喉头水肿|过敏.*休克|全身.*皮疹.*呼吸|过敏性休克", "过敏性休克"),
    (r"抽搐.*婴儿|婴儿.*抽|新生儿.*惊厥", "新生儿/婴儿惊厥"),
    (r"高烧.*4[0-9]|4[0-9].*度.*发烧|体温.*4[0-9]", "超高热（≥40℃）"),
    (r"严重.*低血糖|血糖.*[12]\d?\b.*意识", "严重低血糖伴意识改变"),
]

_URGENT_PATTERNS = [
    (r"持续.*胸闷|心悸.*晕|心跳.*不规则", "心脏症状"),
    (r"肢体.*麻木.*突然|视力.*突然.*模糊|复视.*突然", "神经系统急症征兆"),
    (r"高烧.*3[89]|3[89].*度.*不退|发烧.*三天以上", "持续高热"),
    (r"严重.*腹痛|腹痛.*不能站|剧烈.*腹绞痛", "急腹症"),
    (r"骨折|脱臼|严重.*外伤|头部.*撞击.*意识", "创伤"),
    (r"剧烈.*头痛.*呕吐|头痛.*颈部僵硬", "脑膜刺激征"),
    (r"儿童.*抽搐|热性惊厥|小孩.*抽", "儿童惊厥"),
    (r"中毒|误服|农药|药物过量", "中毒/过量"),
]

_PROMPT_PATTERNS = [
    (r"持续.*发烧|发烧.*三天|38.*度.*两天", "持续发热"),
    (r"腹痛.*持续|腹泻.*血|拉血", "消化道症状"),
    (r"耳鸣.*突然|听力.*下降.*突然", "突发耳部症状"),
    (r"眼睛.*红.*分泌物|视力.*下降", "眼部症状"),
    (r"尿频.*尿急.*尿痛.*发烧|尿血", "泌尿系统感染"),
]


def _match_patterns(text: str, patterns: list) -> list[str]:
    found = []
    for pattern, label in patterns:
        if re.search(pattern, text):
            found.append(label)
    return found


# ─── I/O Schemas ──────────────────────────────────────────────────────────────

class EmergencyTriageInput(BaseModel):
    symptoms_text: str = Field(description="用户描述的症状原文")
    age: int | None = Field(default=None, description="患者年龄（岁）")
    duration_minutes: float | None = Field(
        default=None, description="症状出现至今的分钟数（<30分钟为急性发作）"
    )


EmergencyLevel = Literal["CRITICAL", "URGENT", "PROMPT", "NON_URGENT"]


class EmergencyTriageOutput(SkillOutput):
    level: EmergencyLevel
    level_zh: str
    triggered_flags: list[str]
    safety_message: str     # Agent MUST display this verbatim as the opening line
    action: str
    call_ambulance: bool    # True → display "请立即拨打120" prominently


# ─── Skill Implementation ─────────────────────────────────────────────────────

_LEVEL_LABELS = {
    "CRITICAL":   "危急——请立即拨打120",
    "URGENT":     "紧急——请在1-2小时内前往急诊",
    "PROMPT":     "较紧——建议今日内就医",
    "NON_URGENT": "一般——可择期就诊或居家观察",
}

_SAFETY_MESSAGES = {
    "CRITICAL": (
        "⚠️ **紧急警报：请立即拨打120！**\n\n"
        "您描述的症状可能是危及生命的紧急情况。请立即停止当前活动，"
        "拨打急救电话 **120**，或让身边的人立即送您前往最近的急诊室。"
        "请不要自行驾车。"
    ),
    "URGENT": (
        "🟠 **请在1-2小时内前往急诊或紧急门诊。**\n\n"
        "您的症状需要尽快接受医疗评估，请不要等待。如症状在等待过程中加重，请立即拨打120。"
    ),
    "PROMPT": (
        "🟡 **建议今日内就医。**\n\n"
        "您的症状应在今天内接受医生评估，请尽快预约或前往门诊，如症状明显加重请就近急诊。"
    ),
    "NON_URGENT": (
        "🟢 您描述的症状目前没有明显紧急迹象，我们来进一步了解情况。"
    ),
}


class EmergencyTriageSkill(BaseSkill):
    name = "emergency_triage"
    description = (
        "对用户描述的症状做第一道安全检查，快速识别危急/紧急/一般情况，"
        "输出必须展示给用户的安全提示。应在clinic_agent所有其他处理之前优先调用。"
    )
    tags = ["clinic"]

    def run(self, **kwargs) -> EmergencyTriageOutput:  # type: ignore[override]
        data = EmergencyTriageInput(**kwargs)
        text = data.symptoms_text

        critical_flags = _match_patterns(text, _CRITICAL_PATTERNS)
        urgent_flags = _match_patterns(text, _URGENT_PATTERNS)
        prompt_flags = _match_patterns(text, _PROMPT_PATTERNS)

        # Acute onset boosts severity
        acuity_boost = data.duration_minutes is not None and data.duration_minutes < 30

        # Age modifiers
        age = data.age
        high_risk_age = age is not None and (age < 3 or age > 75)

        if critical_flags or (urgent_flags and acuity_boost and high_risk_age):
            level: EmergencyLevel = "CRITICAL"
            flags = critical_flags or urgent_flags
        elif urgent_flags or (prompt_flags and acuity_boost):
            level = "URGENT"
            flags = urgent_flags or prompt_flags
        elif prompt_flags:
            level = "PROMPT"
            flags = prompt_flags
        else:
            level = "NON_URGENT"
            flags = []

        return EmergencyTriageOutput(
            skill_name=self.name,
            success=True,
            confidence=0.85,
            disclaimer="本检查基于规则匹配，无法替代医疗专业判断。如有疑问请立即就医。",
            level=level,
            level_zh=_LEVEL_LABELS[level],
            triggered_flags=flags,
            safety_message=_SAFETY_MESSAGES[level],
            action=_LEVEL_LABELS[level],
            call_ambulance=(level == "CRITICAL"),
        )
