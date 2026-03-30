---
name: health_calculator
description: |
  Use this skill when the user provides their height, weight, age, and gender and asks
  about their BMI, ideal weight, daily calorie needs (TDEE), or waist-to-height ratio.
  Also triggered by questions like "am I overweight?", "how many calories should I eat?",
  or "what is my healthy weight range?". Applies to advisor_agent and clinic_agent.
tags: [advisor, clinic]
version: "1.0"
---

# Health Calculator Skill

Computes body-metric indicators from user-provided measurements using validated
clinical formulas. All calculations are statistical estimates and must be
accompanied by the embedded disclaimer.

## Capabilities

| Metric | Formula | Output |
|--------|---------|--------|
| BMI | weight_kg / height_m² | Value + WHO/Asian category |
| Ideal weight | Devine formula | kg + difference from current |
| BMR | Mifflin-St Jeor | kcal/day at rest |
| TDEE | BMR × activity factor | kcal/day adjusted for lifestyle |
| Waist-height ratio | waist_cm / height_cm | ratio + cardiovascular risk tier |

## Required Inputs

- `height_cm` — height in centimetres (50–300)
- `weight_kg` — weight in kilograms (1–500)
- `age` — age in years
- `gender` — `"male"` or `"female"`

## Optional Inputs

- `activity_level` — one of `sedentary | light | moderate | active | very_active`
- `waist_cm` — waist circumference for WHR cardiovascular risk (adds `whr_risk` field)

## Output Notes

- BMI categories use **Asian cutpoints** (overweight ≥24.0, obese ≥28.0)
- Always display the `disclaimer` field alongside results
- If `weight_diff_kg` is positive the user should lose weight; negative means gain
