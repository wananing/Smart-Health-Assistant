"""
Skill: health_calculator

Provides body-metrics calculations:
  - BMI (Body Mass Index) with WHO classification
  - Ideal body weight (Devine formula)
  - Daily caloric needs (Mifflin-St Jeor equation)
  - Waist-to-height ratio (cardiovascular risk proxy)

Used by: advisor_agent, clinic_agent
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from skills.base import BaseSkill, SkillOutput


# ─── I/O Schemas ──────────────────────────────────────────────────────────────

class HealthCalcInput(BaseModel):
    height_cm: float = Field(gt=50, lt=300, description="身高（厘米）")
    weight_kg: float = Field(gt=1, lt=500, description="体重（千克）")
    age: int = Field(gt=0, lt=150, description="年龄（岁）")
    gender: Literal["male", "female"] = Field(description="性别：male 或 female")
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"] = Field(
        default="sedentary",
        description="活动水平：sedentary久坐/light轻度/moderate中度/active活跃/very_active高强度",
    )
    waist_cm: float | None = Field(
        default=None, gt=30, lt=250, description="腰围（厘米，可选，用于心血管风险评估）"
    )


class HealthCalcOutput(SkillOutput):
    bmi: float
    bmi_category: str          # 偏瘦 / 正常 / 超重 / 肥胖 / 严重肥胖
    bmi_category_en: str
    ideal_weight_kg: float
    weight_diff_kg: float      # positive = need to lose; negative = need to gain
    bmr_kcal: float            # Basal Metabolic Rate
    tdee_kcal: float           # Total Daily Energy Expenditure
    waist_height_ratio: float | None
    whr_risk: str | None       # 正常 / 边界 / 高风险


# ─── Skill Implementation ─────────────────────────────────────────────────────

_ACTIVITY_FACTORS = {
    "sedentary":   1.2,
    "light":       1.375,
    "moderate":    1.55,
    "active":      1.725,
    "very_active": 1.9,
}

_BMI_CATEGORIES = [
    (18.5, "偏瘦",   "Underweight"),
    (24.0, "正常",   "Normal"),
    (28.0, "超重",   "Overweight"),
    (32.0, "肥胖",   "Obese"),
    (float("inf"), "严重肥胖", "Severely Obese"),
]


class HealthCalculatorSkill(BaseSkill):
    name = "health_calculator"
    description = (
        "计算用户的 BMI、理想体重、每日热量需求（TDEE）和腰围身高比，给出健康体重评估。"
        "输入：身高、体重、年龄、性别、活动水平；可选：腰围。"
    )
    tags = ["advisor", "clinic"]

    def run(self, **kwargs) -> HealthCalcOutput:  # type: ignore[override]
        data = HealthCalcInput(**kwargs)

        h_m = data.height_cm / 100
        bmi = round(data.weight_kg / (h_m ** 2), 1)

        # WHO / 亚洲标准 BMI 分类（亚洲人群超重切点24.0, 肥胖28.0）
        category_zh, category_en = "正常", "Normal"
        for threshold, zh, en in _BMI_CATEGORIES:
            if bmi < threshold:
                category_zh, category_en = zh, en
                break

        # Devine ideal body weight
        if data.gender == "male":
            ideal_kg = 50 + 0.91 * (data.height_cm - 152.4)
        else:
            ideal_kg = 45.5 + 0.91 * (data.height_cm - 152.4)
        ideal_kg = max(ideal_kg, 30.0)
        weight_diff = round(data.weight_kg - ideal_kg, 1)

        # Mifflin-St Jeor BMR
        if data.gender == "male":
            bmr = 10 * data.weight_kg + 6.25 * data.height_cm - 5 * data.age + 5
        else:
            bmr = 10 * data.weight_kg + 6.25 * data.height_cm - 5 * data.age - 161

        tdee = bmr * _ACTIVITY_FACTORS[data.activity_level]

        # Waist-to-height ratio
        whr = None
        whr_risk = None
        if data.waist_cm:
            whr = round(data.waist_cm / data.height_cm, 3)
            if whr < 0.4:
                whr_risk = "偏低"
            elif whr < 0.5:
                whr_risk = "正常"
            elif whr < 0.6:
                whr_risk = "边界风险"
            else:
                whr_risk = "高风险（建议就医评估）"

        return HealthCalcOutput(
            skill_name=self.name,
            success=True,
            confidence=1.0,
            disclaimer="以上数据为统计学估算，仅供参考，不能替代专业医学评估。",
            bmi=bmi,
            bmi_category=category_zh,
            bmi_category_en=category_en,
            ideal_weight_kg=round(ideal_kg, 1),
            weight_diff_kg=weight_diff,
            bmr_kcal=round(bmr),
            tdee_kcal=round(tdee),
            waist_height_ratio=whr,
            whr_risk=whr_risk,
        )
