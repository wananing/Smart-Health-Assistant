---
name: symptom_scorer
description: |
  Use this skill during pre-diagnosis triage (clinic_agent) to assign a structured
  severity score (0–100) and triage colour (RED/YELLOW/GREEN) to the user's reported
  symptoms. Invoke automatically when the user has described at least one symptom.
  The score drives urgency messaging: RED means call 120 immediately, YELLOW means
  same-day visit, GREEN means watchful waiting. Always show triggered_flags to the user.
tags: [clinic]
version: "1.0"
---

# Symptom Scorer Skill

Rule-based clinical triage engine that evaluates free-text symptom descriptions
against a library of red-flag and yellow-flag patterns, fever thresholds,
duration escalation rules, pain scores, and age-specific risk weights.

## Scoring Axes

1. **Red-flag keywords** — life-threatening signs (chest pain, stroke, severe allergy) → +60 per flag
2. **Yellow-flag keywords** — urgent but non-emergency signs → +20 per flag
3. **Fever temperature** — parsed from free text (38°C → +8 … ≥40°C → +40)
4. **Symptom duration** — >3 days +10, >7 days +20, >2 weeks +30, >1 month +40
5. **Pain scale (NRS 0–10)** — mild +8, moderate +15, severe +30
6. **Age modifiers** — <3, >75 years → +15; <12, >65 years → +8

Final score is capped at 100.

## Required Inputs

- `symptoms_text` — raw symptom description from the user (Chinese or English)

## Optional Inputs

- `pain_scale` — 0–10 NRS self-reported pain score
- `duration_days` — symptom duration in days (auto-parsed from text if omitted)
- `age` — patient age for risk weighting

## Triage Thresholds

| Score | Colour | Action |
|-------|--------|--------|
| ≥70 or critical flag | 🔴 RED | Call 120 immediately |
| 35–69 | 🟡 YELLOW | See doctor within 4–8 hours |
| 0–34 | 🟢 GREEN | Watchful waiting 1–3 days |

## Agent Instructions

- Always display `triage_label` and `recommended_action` prominently
- List every item in `triggered_flags` — these explain the urgency to the user
- Show `disclaimer` below the assessment
- If RED: lead with the emergency call-to-action **before** any other text
