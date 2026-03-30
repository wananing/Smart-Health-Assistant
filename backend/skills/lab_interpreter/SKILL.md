---
name: lab_interpreter
description: |
  Use this skill when the user shares lab test values (血常规, 血生化, 甲功, 凝血 etc.)
  and asks what they mean, whether they are normal, or what action to take. Triggered by
  phrases like "帮我看看化验单", "我的血红蛋白偏低是什么意思", "这个指标正常吗". Primarily
  used by report_agent; also available to clinic_agent when symptoms co-occur with results.
tags: [report, clinic]
version: "1.0"
---

# Lab Interpreter Skill

Interprets numeric laboratory values against evidence-based reference ranges,
classifies each item as HIGH / LOW / NORMAL, and provides a plain-language
clinical significance note for each abnormal result.

## Supported Test Panels

| Panel | Items |
|-------|-------|
| 血常规 (CBC) | WBC, RBC, HGB, PLT, HCT, MCV |
| 血糖 | GLU (空腹血糖), HBA1C |
| 肾功能 | CREA, BUN, UA |
| 肝功能 | ALT, AST |
| 血脂 | TC, TG, HDL, LDL |
| 甲状腺 | TSH, FT3, FT4 |
| 凝血 | PT, APTT, INR |

## Required Input

- `items` — list of `{name, value}` objects, e.g.:
  ```json
  [{"name": "WBC", "value": 11.5}, {"name": "HGB", "value": 102}]
  ```

## Optional Inputs

- `patient_age` — adjusts paediatric thresholds
- `patient_gender` — adjusts HGB, RBC, UA reference ranges

## Output Notes

- `summary` field provides a one-sentence triage conclusion
- Unrecognised item names return `status: "UNKNOWN"` — do not fabricate ranges
- Always show `disclaimer`: reference ranges vary by instrument and laboratory
- For critically abnormal values (e.g. WBC > 30, HGB < 60) recommend **immediate** medical attention
