---
name: medication_calculator
description: |
  Use this skill when the user asks about medication dosing, how much of a drug to take
  based on their weight or age, or when a pharmacy_agent or clinic_agent needs to verify
  safe dosage ranges. Triggered by phrases like "我体重60公斤该吃多少剂量", "儿童用量怎么算",
  "这个药的最大剂量是多少", or "按体重算应该用多少". Supports weight-based and
  age-based dosing for common drug classes. Always returns a disclaimer and recommends
  confirming with a pharmacist or physician.
tags: [pharmacy, clinic]
version: "1.0"
---

# Medication Calculator Skill

Computes weight-based and age-based medication doses for common drug classes
using standard clinical dosing references (e.g. BNF, UpToDate guidelines).

## Supported Drug Classes

| Class | Examples | Dosing Method |
|-------|---------|---------------|
| 解热镇痛 NSAIDs | 布洛芬, 对乙酰氨基酚 | Weight-based (mg/kg) |
| 抗生素 Antibiotics | 阿莫西林, 头孢克洛 | Weight-based (mg/kg/day) |
| 抗组胺 Antihistamines | 氯苯那敏, 氯雷他定 | Age/weight-based |
| 消化道 GI | 奥美拉唑, 多潘立酮 | Fixed adult / weight-adjusted paediatric |
| 降压 Antihypertensives | 氨氯地平, 依那普利 | Fixed titration (refer to physician) |

## Required Inputs

- `drug_name` — generic drug name (e.g. 布洛芬, 阿莫西林)
- `weight_kg` — patient body weight
- `age_years` — patient age

## Optional Inputs

- `indication` — reason for use (may select different dosing schedule)
- `renal_impairment` — `"mild" | "moderate" | "severe"` for dose adjustment notes
- `is_pregnant` — triggers pregnancy safety classification

## Output Notes

- Doses are displayed as a range (low–high) with frequency
- **Prescription drugs**: Output includes a mandatory "需凭处方" warning
- **Paediatric**: Per-kg doses always calculated; max dose cap enforced
- Always show `disclaimer` and `max_dose_warning` if applicable
- Recommend confirming with 执业药师 (licensed pharmacist) before dispensing

## Safety Rules

- Never recommend doses above established maximum daily limits
- For `renal_impairment == "severe"`: output dose reduction note and physician referral
- For pregnancy: display FDA/CFDA category and safety note
- For age < 2 years: explicitly state "需在医生指导下使用"
