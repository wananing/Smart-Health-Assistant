---
name: risk_assessor
description: |
  Use this skill when the user wants to understand their long-term cardiovascular
  disease (CVD) or type-2 diabetes risk. Triggered by questions like "我心脏病风险高吗",
  "我会得糖尿病吗", "帮我评估健康风险", or after learning the user has multiple risk
  factors (smoking, hypertension, obesity, family history). Used by clinic_agent and
  advisor_agent. Pair with health_calculator to obtain BMI before calling this skill.
tags: [clinic, advisor]
version: "1.0"
---

# Risk Assessor Skill

Evaluates a user's 10-year disease risk using two validated clinical instruments:

| Model | Target | Basis |
|-------|--------|-------|
| Simplified Framingham | Cardiovascular disease (CVD) | 12-factor weighted scoring |
| FINDRISC | Type-2 diabetes | Finnish 8-item validated scale |

## Risk Levels

| Level | CVD 10yr | Diabetes 10yr | Colour |
|-------|----------|---------------|--------|
| 低风险 | <5% | <1% | 🟢 GREEN |
| 中等风险 | 5–15% | 1–4% | 🟡 YELLOW |
| 高风险 | 15–30% | ~17% | 🟠 ORANGE |
| 极高风险 | >30% | >33% | 🔴 RED |

## Required Inputs

- `age`, `gender`
- `is_smoker` (bool)

## Optional but Highly Recommended

- `systolic_bp` — systolic blood pressure in mmHg
- `bmi` — obtain via `health_calculator` skill if not known
- `has_diabetes`, `has_hypertension`, `bp_medication`
- `family_history_cvd`, `family_history_diabetes`
- `physical_activity`, `fruit_veg_daily`
- `tc_mmol`, `hdl_mmol` — for more precise CVD scoring

## Agent Instructions

- List `key_modifiable_factors` — these are the user's highest-leverage interventions
- Present `recommendations` as an actionable checklist
- For HIGH or 极高风险: strongly encourage specialist referral (心内科 / 内分泌科)
- Always display `disclaimer` — risk models are population-level estimates
