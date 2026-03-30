"""
Skill: lab_interpreter

Interprets common lab test values against reference ranges and produces
a structured abnormality report with clinical significance notes.

Supports:
  血常规 (CBC):  WBC, RBC, HGB, PLT, HCT, MCV
  血生化:        GLU, HbA1c, CREA, BUN, ALT, AST, TC, TG, HDL, LDL, UA
  甲功:          TSH, FT3, FT4
  凝血:          PT, APTT, INR

Used by: report_agent
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from skills.base import BaseSkill, SkillOutput


# ─── Reference Ranges ─────────────────────────────────────────────────────────
# Format: (low, high, unit, full_name_zh, clinical_note)
_REFERENCE_RANGES: dict[str, tuple] = {
    # 血常规
    "WBC":   (4.0,   10.0,  "×10⁹/L", "白细胞计数",   "升高提示感染/炎症；降低见于病毒感染、骨髓抑制"),
    "RBC":   (3.5,   5.5,   "×10¹²/L","红细胞计数",   "降低提示贫血；升高见于红细胞增多症或脱水"),
    "HGB":   (110,   160,   "g/L",     "血红蛋白",     "低于正常为贫血；需结合MCV判断贫血类型"),
    "PLT":   (100,   300,   "×10⁹/L", "血小板计数",   "降低见于特发性血小板减少性紫癜、DIC；升高见于感染、脾切除后"),
    "HCT":   (0.37,  0.50,  "%",       "红细胞压积",   "与HGB平行，辅助判断贫血和血液浓缩"),
    "MCV":   (80,    100,   "fL",      "平均红细胞体积","小细胞性贫血MCV<80，大细胞性贫血MCV>100"),
    # 血糖
    "GLU":   (3.9,   6.1,   "mmol/L",  "空腹血糖",     "≥7.0为糖尿病诊断标准；6.1-7.0为糖尿病前期"),
    "HBA1C": (4.0,   6.0,   "%",       "糖化血红蛋白",  "≥6.5%提示糖尿病；7.0%为糖尿病控制目标"),
    # 肾功能
    "CREA":  (44,    133,   "μmol/L",  "血肌酐",       "升高提示肾功能下降；女性正常上限约106μmol/L"),
    "BUN":   (2.9,   8.2,   "mmol/L",  "尿素氮",       "升高见于肾功能不全、脱水、高蛋白饮食"),
    "UA":    (149,   417,   "μmol/L",  "尿酸",         "男性>420提示高尿酸；女性>360；痛风风险增加"),
    # 肝功能
    "ALT":   (0,     40,    "U/L",     "丙氨酸氨基转移酶","升高提示肝细胞损伤；>3倍正常上限需重视"),
    "AST":   (0,     40,    "U/L",     "天冬氨酸氨基转移酶","AST/ALT比值辅助判断肝病类型"),
    # 血脂
    "TC":    (0,     5.2,   "mmol/L",  "总胆固醇",     "≥6.2为高胆固醇血症；心血管风险随之升高"),
    "TG":    (0,     1.7,   "mmol/L",  "甘油三酯",     "≥5.65严重升高，胰腺炎风险"),
    "HDL":   (1.0,   99,    "mmol/L",  "高密度脂蛋白",  "低HDL（<1.0男/<1.3女）是冠心病独立危险因素"),
    "LDL":   (0,     3.4,   "mmol/L",  "低密度脂蛋白",  "心血管高危患者目标<1.8；一般人群<3.4"),
    # 甲状腺
    "TSH":   (0.27,  4.2,   "mIU/L",  "促甲状腺激素",  "升高提示甲减；降低提示甲亢"),
    "FT3":   (3.1,   6.8,   "pmol/L",  "游离三碘甲状腺原氨酸","甲亢时升高，甲减时降低"),
    "FT4":   (12,    22,    "pmol/L",  "游离甲状腺素",  "甲亢时升高，甲减时降低"),
    # 凝血
    "PT":    (11,    13,    "s",       "凝血酶原时间",   "延长见于肝病、维生素K缺乏、口服抗凝药"),
    "APTT":  (28,    40,    "s",       "活化部分凝血活酶时间","延长见于血友病、肝素治疗"),
    "INR":   (0.8,   1.2,   "",        "国际标准化比值",  "口服华法林患者目标INR 2.0-3.0"),
}


# ─── I/O Schemas ──────────────────────────────────────────────────────────────

class LabItem(BaseModel):
    name: str = Field(description="检验项目名称或缩写，如 WBC、HGB、GLU")
    value: float = Field(description="检验结果数值")
    unit: str | None = Field(default=None, description="单位（可选，用于验证）")


class LabInterpreterInput(BaseModel):
    items: list[LabItem] = Field(description="需要解读的检验项目列表")
    patient_age: int | None = Field(default=None, description="患者年龄（影响部分参考范围）")
    patient_gender: Literal["male", "female"] | None = Field(default=None, description="患者性别")


class LabFinding(BaseModel):
    name: str
    full_name: str
    value: float
    unit: str
    status: Literal["HIGH", "LOW", "NORMAL", "UNKNOWN"]
    reference: str
    clinical_note: str


class LabInterpreterOutput(SkillOutput):
    total_items: int
    abnormal_count: int
    findings: list[LabFinding]
    summary: str


# ─── Skill Implementation ─────────────────────────────────────────────────────

class LabInterpreterSkill(BaseSkill):
    name = "lab_interpreter"
    description = (
        "解读用户提供的化验单数值，逐项对比参考范围，标注偏高/偏低/正常，"
        "并给出每项指标的临床意义说明。支持血常规、血生化、甲功、凝血等常见项目。"
    )
    tags = ["report", "clinic"]

    def run(self, **kwargs) -> LabInterpreterOutput:  # type: ignore[override]
        data = LabInterpreterInput(**kwargs)
        findings: list[LabFinding] = []

        for item in data.items:
            key = item.name.upper().replace("-", "").replace("_", "")
            ref = _REFERENCE_RANGES.get(key)

            if ref is None:
                findings.append(LabFinding(
                    name=item.name, full_name=item.name,
                    value=item.value, unit=item.unit or "",
                    status="UNKNOWN", reference="暂无参考范围",
                    clinical_note="该项目暂不在解读范围内，请咨询医生。",
                ))
                continue

            low, high, unit, full_name, note = ref

            # Gender-specific adjustments
            if key == "HGB":
                if data.patient_gender == "female":
                    low, high = 110, 150
                elif data.patient_gender == "male":
                    low, high = 120, 160
            if key == "RBC":
                if data.patient_gender == "female":
                    low, high = 3.5, 5.0
                elif data.patient_gender == "male":
                    low, high = 4.0, 5.5
            if key == "UA":
                if data.patient_gender == "female":
                    low, high = 89, 357

            if item.value > high:
                status = "HIGH"
            elif item.value < low:
                status = "LOW"
            else:
                status = "NORMAL"

            reference = f"{low}–{high} {unit}".strip()
            findings.append(LabFinding(
                name=item.name,
                full_name=full_name,
                value=item.value,
                unit=unit,
                status=status,
                reference=reference,
                clinical_note=note,
            ))

        abnormal = [f for f in findings if f.status in ("HIGH", "LOW")]
        if not abnormal:
            summary = "所有解读项目均在参考范围内，请结合临床症状综合判断。"
        else:
            parts = [f"{f.full_name}({'偏高' if f.status == 'HIGH' else '偏低'})" for f in abnormal]
            summary = f"发现 {len(abnormal)} 项异常：{'、'.join(parts)}。建议就诊时向医生说明，由医生结合病史综合评估。"

        return LabInterpreterOutput(
            skill_name=self.name,
            success=True,
            confidence=0.9,
            disclaimer="参考范围来自通用指南，不同医院/仪器可能存在差异，以原报告参考范围为准。",
            total_items=len(findings),
            abnormal_count=len(abnormal),
            findings=findings,
            summary=summary,
        )
