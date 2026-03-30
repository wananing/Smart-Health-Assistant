"""
Skill: risk_assessor

Evaluates a user's 10-year cardiovascular disease (CVD) risk and type-2
diabetes risk using validated clinical scoring models:

  CVD Risk:      Simplified Framingham / WHO CVD Risk Chart (categorical)
  Diabetes Risk: Finnish Diabetes Risk Score (FINDRISC) — validated for Asian populations

Used by: clinic_agent, advisor_agent
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from skills.base import BaseSkill, SkillOutput


# ─── I/O Schemas ──────────────────────────────────────────────────────────────

class RiskAssessorInput(BaseModel):
    age: int = Field(gt=0, lt=120, description="年龄（岁）")
    gender: Literal["male", "female"] = Field(description="性别")
    systolic_bp: int | None = Field(default=None, description="收缩压（mmHg），如130")
    is_smoker: bool = Field(default=False, description="是否吸烟（目前）")
    has_diabetes: bool = Field(default=False, description="是否已确诊糖尿病")
    has_hypertension: bool = Field(default=False, description="是否已确诊高血压")
    bp_medication: bool = Field(default=False, description="是否正在服用降压药")
    family_history_cvd: bool = Field(default=False, description="直系亲属中是否有心血管病史（<60岁发病）")
    family_history_diabetes: bool = Field(default=False, description="直系亲属中是否有糖尿病史")
    bmi: float | None = Field(default=None, description="BMI（可通过health_calculator技能计算）")
    waist_cm: float | None = Field(default=None, description="腰围（厘米）")
    physical_activity: bool = Field(
        default=True, description="每天是否有≥30分钟中等强度体力活动（或工作包含体力劳动）"
    )
    fruit_veg_daily: bool = Field(
        default=True, description="是否每天摄入蔬菜或水果"
    )
    tc_mmol: float | None = Field(default=None, description="总胆固醇（mmol/L），可选")
    hdl_mmol: float | None = Field(default=None, description="HDL胆固醇（mmol/L），可选")


class RiskLevel(BaseModel):
    level: Literal["低风险", "中等风险", "高风险", "极高风险"]
    percentage: str   # e.g. "<5%", "10-20%"
    color: Literal["GREEN", "YELLOW", "ORANGE", "RED"]


class RiskAssessorOutput(SkillOutput):
    cvd_risk: RiskLevel
    diabetes_risk: RiskLevel
    cvd_score: int                    # raw score for CVD
    findrisc_score: int               # raw FINDRISC score
    key_modifiable_factors: list[str] # factors the user can change
    recommendations: list[str]


# ─── Scoring Logic ────────────────────────────────────────────────────────────

def _cvd_risk(data: RiskAssessorInput) -> tuple[int, RiskLevel]:
    """Simplified CVD risk scoring (categorical Framingham proxy)."""
    score = 0

    # Age
    if data.age >= 65:
        score += 4
    elif data.age >= 55:
        score += 3
    elif data.age >= 45:
        score += 2
    elif data.age >= 35:
        score += 1

    # Gender (males higher baseline CVD risk)
    if data.gender == "male":
        score += 1

    # Smoking
    if data.is_smoker:
        score += 3

    # Blood pressure
    sbp = data.systolic_bp
    if sbp:
        if sbp >= 180:
            score += 4
        elif sbp >= 160:
            score += 3
        elif sbp >= 140:
            score += 2
        elif sbp >= 130:
            score += 1
    if data.bp_medication:
        score += 1

    # Diabetes
    if data.has_diabetes:
        score += 3

    # Family history
    if data.family_history_cvd:
        score += 2

    # Cholesterol (if available)
    if data.tc_mmol and data.tc_mmol >= 6.2:
        score += 2
    elif data.tc_mmol and data.tc_mmol >= 5.2:
        score += 1
    if data.hdl_mmol and data.hdl_mmol < 1.0:
        score += 2

    # BMI
    if data.bmi:
        if data.bmi >= 30:
            score += 2
        elif data.bmi >= 25:
            score += 1

    if score <= 3:
        level = RiskLevel(level="低风险", percentage="<5%", color="GREEN")
    elif score <= 6:
        level = RiskLevel(level="中等风险", percentage="5-15%", color="YELLOW")
    elif score <= 9:
        level = RiskLevel(level="高风险", percentage="15-30%", color="ORANGE")
    else:
        level = RiskLevel(level="极高风险", percentage=">30%", color="RED")

    return score, level


def _findrisc(data: RiskAssessorInput) -> tuple[int, RiskLevel]:
    """FINDRISC — Finnish Diabetes Risk Score (validated 8-item instrument)."""
    score = 0

    # Age
    if data.age >= 65:
        score += 4
    elif data.age >= 55:
        score += 3
    elif data.age >= 45:
        score += 2

    # BMI
    bmi = data.bmi
    if bmi:
        if bmi >= 30:
            score += 3
        elif bmi >= 25:
            score += 1

    # Waist circumference (gender-specific)
    waist = data.waist_cm
    if waist:
        if data.gender == "male":
            if waist >= 102:
                score += 4
            elif waist >= 94:
                score += 3
        else:
            if waist >= 88:
                score += 4
            elif waist >= 80:
                score += 3

    # Physical activity
    if not data.physical_activity:
        score += 2

    # Fruit/vegetable consumption
    if not data.fruit_veg_daily:
        score += 1

    # Antihypertensive medication
    if data.bp_medication:
        score += 2

    # High blood glucose history
    if data.has_diabetes:
        score += 5  # already diabetic

    # Family history
    if data.family_history_diabetes:
        score += 5

    if score <= 7:
        level = RiskLevel(level="低风险", percentage="<1%", color="GREEN")
    elif score <= 11:
        level = RiskLevel(level="中等风险", percentage="1-4%", color="YELLOW")
    elif score <= 14:
        level = RiskLevel(level="高风险", percentage="17%", color="ORANGE")
    else:
        level = RiskLevel(level="极高风险", percentage=">33%", color="RED")

    return score, level


class RiskAssessorSkill(BaseSkill):
    name = "risk_assessor"
    description = (
        "基于用户的年龄、血压、血脂、生活方式等信息，评估10年心血管疾病（CVD）风险"
        "和2型糖尿病风险（FINDRISC量表），给出风险等级、关键可干预因素和预防建议。"
    )
    tags = ["clinic", "advisor"]

    def run(self, **kwargs) -> RiskAssessorOutput:  # type: ignore[override]
        data = RiskAssessorInput(**kwargs)
        cvd_score, cvd_level = _cvd_risk(data)
        findrisc_score, dm_level = _findrisc(data)

        # Identify modifiable factors
        modifiable: list[str] = []
        if data.is_smoker:
            modifiable.append("吸烟（戒烟可显著降低CVD风险）")
        if data.bmi and data.bmi >= 25:
            modifiable.append(f"超重/肥胖（BMI {data.bmi:.1f}，建议减重）")
        if data.systolic_bp and data.systolic_bp >= 130:
            modifiable.append(f"血压偏高（收缩压{data.systolic_bp}mmHg）")
        if not data.physical_activity:
            modifiable.append("缺乏体力活动（建议每日≥30分钟中等强度运动）")
        if not data.fruit_veg_daily:
            modifiable.append("蔬果摄入不足（建议每日≥500g）")
        if data.tc_mmol and data.tc_mmol >= 5.2:
            modifiable.append(f"胆固醇偏高（TC {data.tc_mmol}mmol/L）")

        # Recommendations
        recs: list[str] = []
        if cvd_level.color in ("ORANGE", "RED"):
            recs.append("建议尽快就诊心内科或全科，进行系统心血管风险评估")
        if dm_level.color in ("ORANGE", "RED"):
            recs.append("建议检测空腹血糖和糖化血红蛋白（HbA1c），排查糖尿病")
        recs += [
            "每年进行一次全面体检（血脂、血糖、血压）",
            "坚持地中海或DASH饮食模式，减少饱和脂肪和精制糖摄入",
            "保持每周150分钟以上中等强度有氧运动",
        ]
        if data.is_smoker:
            recs.insert(0, "立即戒烟——这是降低CVD风险最有效的单一措施")

        return RiskAssessorOutput(
            skill_name=self.name,
            success=True,
            confidence=0.7,
            disclaimer=(
                "本评估基于FINDRISC量表和Framingham简化模型，仅供健康管理参考，"
                "不能替代医院全面心血管风险评估（如ABI、颈动脉超声等）。"
            ),
            cvd_risk=cvd_level,
            diabetes_risk=dm_level,
            cvd_score=cvd_score,
            findrisc_score=findrisc_score,
            key_modifiable_factors=modifiable,
            recommendations=recs,
        )
