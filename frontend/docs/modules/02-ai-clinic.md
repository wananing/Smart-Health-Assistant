# 02. AI Clinic Design Specification

## 1. Overview
The AI Clinic ("AI 诊室") module provides an intelligent pre-diagnosis triage system. It guides the user through selecting a patient profile (self or family member), capturing symptoms via text or voice ("描述症状"), and automatically outputting AI-generated medical advice and department recommendations ("推荐科室").

## 2. Key Features
- **Dynamic Step Progress Indicator**: A horizontal timeline showing the current phase: "选咨询人" (Select Patient) → "描述症状" (Describe Symptoms) → "诊疗建议" (Recommendations).
- **Patient Profile Switcher**: Interactive cards to quickly swap context between the primary user and linked family profiles (e.g., father, mother).
- **Multi-modal Symptom Input**: A voice-recording interface (`isRecording` state toggle pulse effect) with fallback text suggestions, plus an entry point to the "Report Scanner" for OCR inputs.
- **AI Triage Result Card**: A stylized summary of the AI's triage analysis containing the explanation, severity context, and highlighted department tags.
- **Legal Disclaimer Banner**: A mandatory orange warning notifying users that AI advice cannot replace professional medical diagnosis or 120 emergency services.

## 3. User Flows
- **Triage Flow**: 
  1. Opens Clinic → Step 0: User selects "本人 (王*虎)" → Clicks Next.
  2. Step 1: User clicks Voice Record → `isRecording` activates → User speaks symptoms → Clicks stop.
  3. Step 2: System analyzes → Outputs "Recommendations" Step.
  4. User clicks "Go to booking" → Routes `currentScreen` to `services`.

## 4. Data Dictionary (Types/Interfaces)

```typescript
export interface ClinicSession {
  sessionId: string;
  step: 0 | 1 | 2;
  patientId: string; // Linked to UserProfile
  symptomsText: string;
  audioDurationMs?: number;
}

export interface RecommendationCard {
  summary: string;
  departments: string[]; // e.g., ['中医内科', '神经内科']
  severityLevel: 'low' | 'medium' | 'high';
}
```

## 5. Component Breakdown
- **`ProgressStepper`**: Maps the array `['选咨询人', '描述症状', '诊疗建议']` onto a horizontal line.
- **`PatientSelector`**: A grid of selectable cards detailing family members.
- **`InputMethodPanel`**: The side-by-side buttons for Camera (Report Scan) and Mic (Voice Desc).
- **`RecommendationResult`**: The final output view containing the analysis text and tag list.

## 6. API / Mock Data Requirements
- Requires mock `setTimeout` simulation of voice processing logic that advances `clinicStep` from 1 to 2.
- Mock analysis payload containing: "失眠症状可能与近期的生活压力或神经衰弱有关..." and tags `[中医内科, 神经内科]`.
