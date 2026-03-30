---
name: emergency_triage
description: |
  Use this skill as the FIRST action in clinic_agent whenever any symptom could
  indicate a life-threatening emergency. Triggered by keywords like 胸痛, 呼吸困难,
  意识丧失, 大出血, 口眼歪斜, 抽搐, 过敏, 高烧40度 or similar red-flag language.
  Produces a mandatory safety check that must be shown to the user before any
  other response. If the result is CRITICAL or URGENT, the agent must lead with
  "请立即拨打120" and stop further triage questioning.
tags: [clinic]
version: "1.0"
---

# Emergency Triage Skill

Fast, deterministic pattern-matching safety gate that runs **before** any LLM
reasoning on symptom inputs. Checks free-text for ACLS/ATLS red flags and
returns a mandatory action with zero hallucination risk (pure rule-based).

## Response Levels

| Level | Meaning | Required Agent Action |
|-------|---------|----------------------|
| CRITICAL | Potential life threat — call 120 NOW | Output "请立即拨打120" as first line; do not continue normal triage |
| URGENT | Needs ER within 1–2 hours | Recommend immediate hospital visit |
| PROMPT | Needs same-day clinic visit | Advise urgent appointment |
| NON_URGENT | Routine care appropriate | Proceed with normal triage flow |

## Required Input

- `symptoms_text` — raw symptom text from user

## Optional Inputs

- `age` — modulates paediatric and geriatric thresholds
- `duration_minutes` — symptom onset acuity (sudden < 30 min = higher severity)

## Critical Flags Detected

Cardiac: chest pain, palpitations with syncope, suspected MI
Neurological: stroke signs (FAST), severe headache, seizures, LOC
Respiratory: severe dyspnoea, airway obstruction, anaphylaxis
Haemorrhagic: uncontrolled bleeding, haematemesis
Paediatric: febrile seizures, respiratory distress in infants
Metabolic: suspected DKA, severe hypoglycaemia

## Agent Instructions

- Call this skill first — before symptom_scorer or any other reasoning
- If `level == "CRITICAL"`: immediately output the emergency message; do NOT ask follow-up questions
- Always output the `safety_message` field verbatim as the opening line of your response
- Show the `action` field as a clear, styled call-to-action
