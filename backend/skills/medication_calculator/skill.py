"""
Skill: medication_calculator

Computes weight-based and age-based medication doses for common drug classes.
Returns a structured dose recommendation with safety warnings.

Data source: standard clinical dosing references (BNF, UpToDate, CFDA guidelines).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from skills.base import BaseSkill, SkillOutput


# ─── Dosing Database ──────────────────────────────────────────────────────────
# Format: drug_key → {adult_dose, paediatric_mg_per_kg, max_daily_mg,
#                      frequency, route, otc, pregnancy_category, notes}

_DOSING_DB: dict[str, dict] = {
    "布洛芬": {
        "class": "NSAID解热镇痛",
        "adult_dose_mg": "200–400",
        "paediatric_mg_per_kg": 10,
        "max_daily_adult_mg": 1200,   # OTC limit; Rx limit 3200
        "max_daily_paediatric_mg_per_kg": 40,
        "frequency": "每4-6小时一次（勿超过每日4次）",
        "route": "口服",
        "otc": True,
        "min_age_years": 0.5,
        "pregnancy_category": "C（孕晚期禁用）",
        "renal_note": "肾功能不全者减量，eGFR<30避免使用",
        "notes": "餐后服用减少胃刺激；消化性溃疡者禁用",
    },
    "对乙酰氨基酚": {
        "class": "解热镇痛",
        "adult_dose_mg": "325–650",
        "paediatric_mg_per_kg": 15,
        "max_daily_adult_mg": 4000,
        "max_daily_paediatric_mg_per_kg": 75,
        "frequency": "每4-6小时一次（勿超过每日4次）",
        "route": "口服",
        "otc": True,
        "min_age_years": 0.25,
        "pregnancy_category": "B（孕期相对安全，需医生指导）",
        "renal_note": "中重度肾功能不全延长给药间隔至8小时",
        "notes": "严禁与其他含对乙酰氨基酚制剂同用；避免饮酒",
    },
    "阿莫西林": {
        "class": "青霉素类抗生素",
        "adult_dose_mg": "250–500",
        "paediatric_mg_per_kg": 25,
        "max_daily_adult_mg": 3000,
        "max_daily_paediatric_mg_per_kg": 100,
        "frequency": "每8小时一次（每日3次）",
        "route": "口服",
        "otc": False,
        "min_age_years": 0,
        "pregnancy_category": "B（孕期可用）",
        "renal_note": "eGFR 10-30：每12小时一次；eGFR<10：每24小时一次",
        "notes": "需凭处方购买；用药前须询问青霉素过敏史",
    },
    "头孢克洛": {
        "class": "第二代头孢菌素",
        "adult_dose_mg": "250–500",
        "paediatric_mg_per_kg": 20,
        "max_daily_adult_mg": 4000,
        "max_daily_paediatric_mg_per_kg": 40,
        "frequency": "每8小时一次",
        "route": "口服",
        "otc": False,
        "min_age_years": 1,
        "pregnancy_category": "B",
        "renal_note": "肾功能不全需调整剂量",
        "notes": "需凭处方购买；青霉素过敏者慎用（交叉过敏约1-10%）",
    },
    "氯雷他定": {
        "class": "第二代抗组胺药",
        "adult_dose_mg": "10",
        "paediatric_mg_per_kg": None,   # Fixed paediatric dose
        "paediatric_fixed": {2: 5, 12: 10},  # age_years→mg
        "max_daily_adult_mg": 10,
        "frequency": "每日一次",
        "route": "口服",
        "otc": True,
        "min_age_years": 2,
        "pregnancy_category": "B",
        "renal_note": "肾功能不全者改为隔日服用",
        "notes": "少嗜睡，适合白天使用；驾车者可用",
    },
    "氯苯那敏": {
        "class": "第一代抗组胺药",
        "adult_dose_mg": "4",
        "paediatric_mg_per_kg": 0.1,
        "max_daily_adult_mg": 24,
        "max_daily_paediatric_mg_per_kg": 0.5,
        "frequency": "每4-6小时一次",
        "route": "口服",
        "otc": True,
        "min_age_years": 2,
        "pregnancy_category": "B",
        "renal_note": "无需调整",
        "notes": "有明显嗜睡；驾车、操作机器者禁用",
    },
    "奥美拉唑": {
        "class": "质子泵抑制剂",
        "adult_dose_mg": "20–40",
        "paediatric_mg_per_kg": 0.7,
        "max_daily_adult_mg": 80,
        "max_daily_paediatric_mg_per_kg": 3.3,
        "frequency": "每日1-2次（餐前30分钟服用）",
        "route": "口服",
        "otc": False,
        "min_age_years": 1,
        "pregnancy_category": "C",
        "renal_note": "无需调整",
        "notes": "需凭处方购买；长期使用需关注低镁血症和骨质疏松",
    },
}

_ALIASES = {
    "泰诺": "对乙酰氨基酚",
    "必理通": "对乙酰氨基酚",
    "芬必得": "布洛芬",
    "美林": "布洛芬",
    "开瑞坦": "氯雷他定",
    "扑尔敏": "氯苯那敏",
    "洛赛克": "奥美拉唑",
}


# ─── I/O Schemas ──────────────────────────────────────────────────────────────

class MedicationCalcInput(BaseModel):
    drug_name: str = Field(description="药品通用名或常见品牌名，如布洛芬、泰诺")
    weight_kg: float = Field(gt=0, lt=500, description="患者体重（千克）")
    age_years: float = Field(ge=0, lt=120, description="患者年龄（岁，可用小数如0.5表示6个月）")
    renal_impairment: Literal["none", "mild", "moderate", "severe"] = Field(
        default="none", description="肾功能损害程度"
    )
    is_pregnant: bool = Field(default=False, description="是否妊娠")


class MedicationCalcOutput(SkillOutput):
    drug_name: str
    drug_class: str
    is_otc: bool
    recommended_dose_mg: str
    max_single_dose_mg: float
    max_daily_dose_mg: float
    frequency: str
    route: str
    pregnancy_category: str | None
    renal_note: str
    warnings: list[str]
    max_dose_warning: str | None


# ─── Skill Implementation ─────────────────────────────────────────────────────

class MedicationCalculatorSkill(BaseSkill):
    name = "medication_calculator"
    description = (
        "根据患者体重和年龄，计算常见药物的推荐剂量和最大日剂量，"
        "标注处方/非处方属性、妊娠安全分级和肾功能调整建议。"
        "用于pharmacy_agent和clinic_agent辅助用药指导。"
    )
    tags = ["pharmacy", "clinic"]

    def run(self, **kwargs) -> MedicationCalcOutput:  # type: ignore[override]
        data = MedicationCalcInput(**kwargs)

        # Resolve aliases
        key = _ALIASES.get(data.drug_name, data.drug_name)
        db = _DOSING_DB.get(key)

        warnings: list[str] = []

        if db is None:
            return MedicationCalcOutput(
                skill_name=self.name,
                success=False,
                confidence=0.0,
                disclaimer="未找到该药品剂量数据，请咨询执业药师或医生。",
                drug_name=data.drug_name,
                drug_class="未知",
                is_otc=False,
                recommended_dose_mg="未知——请咨询药师",
                max_single_dose_mg=0,
                max_daily_dose_mg=0,
                frequency="请遵医嘱",
                route="口服",
                pregnancy_category=None,
                renal_note="",
                warnings=["该药品不在当前数据库中，请务必咨询专业药师或医生。"],
                max_dose_warning=None,
            )

        is_paediatric = data.age_years < 12

        # Age gate
        min_age = db.get("min_age_years", 0)
        if data.age_years < min_age:
            warnings.append(
                f"⚠️ {key}不适用于{data.age_years}岁以下儿童，需在医生指导下使用。"
            )

        mg_per_kg: float | None = None
        max_daily: float

        if is_paediatric:
            fixed = db.get("paediatric_fixed")
            mg_per_kg = db.get("paediatric_mg_per_kg")
            if fixed:
                dose_mg = next(
                    (v for age_thresh, v in sorted(fixed.items()) if data.age_years >= age_thresh),
                    list(fixed.values())[0]
                )
                recommended = f"{dose_mg}mg"
                max_single = float(dose_mg)
                max_daily = float(db.get("max_daily_adult_mg", max_single * 4))
            elif mg_per_kg is not None:
                dose_mg = round(data.weight_kg * mg_per_kg, 1)
                max_mg_per_kg = db.get("max_daily_paediatric_mg_per_kg", mg_per_kg * 4)
                max_daily = round(data.weight_kg * max_mg_per_kg, 1)
                recommended = f"{dose_mg}mg（按{mg_per_kg}mg/kg计算）"
                max_single = dose_mg
            else:
                recommended = db["adult_dose_mg"] + "mg（成人剂量参考，需医生评估）"
                max_single = float(str(db["adult_dose_mg"]).split("–")[-1])
                max_daily = float(db.get("max_daily_adult_mg", max_single * 4))
        else:
            recommended = db["adult_dose_mg"] + "mg"
            max_single = float(str(db["adult_dose_mg"]).split("–")[-1])
            max_daily = float(db.get("max_daily_adult_mg", max_single * 4))

        # Renal adjustments
        renal_note = db.get("renal_note", "")
        if data.renal_impairment in ("moderate", "severe"):
            warnings.append(f"⚠️ 肾功能{data.renal_impairment}损害：{renal_note}")

        # Pregnancy
        preg_cat = db.get("pregnancy_category", "")
        if data.is_pregnant:
            warnings.append(f"⚠️ 妊娠安全分级：{preg_cat}。请在产科医生指导下使用。")

        # Prescription warning
        if not db.get("otc", True):
            warnings.insert(0, "⚠️ 本药为处方药，必须凭医生处方购买，不可自行用药。")

        # Max dose check
        max_dose_warning = None
        if is_paediatric and mg_per_kg is not None:
            max_daily_paed = round(
                data.weight_kg * db.get("max_daily_paediatric_mg_per_kg", mg_per_kg * 4), 1
            )
            max_dose_warning = f"儿童最大日剂量上限：{max_daily_paed}mg，切勿超量。"

        return MedicationCalcOutput(
            skill_name=self.name,
            success=True,
            confidence=0.85,
            disclaimer=(
                "本计算结果基于标准剂量指南，仅供参考。实际用药剂量请由执业药师或医生根据"
                "患者完整病情、联合用药等因素综合评估确认。"
            ),
            drug_name=key,
            drug_class=db["class"],
            is_otc=db.get("otc", False),
            recommended_dose_mg=recommended,
            max_single_dose_mg=max_single,
            max_daily_dose_mg=max_daily,
            frequency=db["frequency"],
            route=db["route"],
            pregnancy_category=preg_cat or None,
            renal_note=renal_note,
            warnings=warnings + ([db["notes"]] if db.get("notes") else []),
            max_dose_warning=max_dose_warning,
        )
