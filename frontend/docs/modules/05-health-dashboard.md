# 05. Health Dashboard Design Specification

## 1. Overview
The Health Dashboard ("健康小目标") provides a snapshot of the user's daily wellness metrics and habit-tracking progress. It aggregates hardware-synced data (like steps, heart rate, and sleep) and presents daily contextual goals.

## 2. Key Features
- **Vitals Overview Board**: Visualizes key metrics such as resting heart rate (bpm) and last night's total sleep duration in stylized, color-coded cards (e.g., Rose for Heart, Indigo for Sleep) along with qualitative tags ("正常水平" / Normal Level).
- **Daily Habit Tracker (Progress Bars)**: A list of defined health tasks (Water intake, Walking, Blood pressure measurement) featuring dynamic progress bars mapped to colored themes.
- **Micro-interactions**: Hover effects on cards and CSS transitions for progress bars filling up from 0 to current.

## 3. User Flows
- **View Vitals**: Home Screen "我的健康" widget clicked → Routes to `dashboard` → Displays full metrics.
- **Progress Interaction**: The bars animate on load `{{ width: \`\${task.progress}%\` }}`.

## 4. Data Dictionary (Types/Interfaces)

```typescript
export interface VitalSign {
  type: 'HeartRate' | 'Sleep' | 'BloodPressure' | 'Steps';
  currentValue: number | string;
  unit: string;
  statusTag: string; // e.g., 'Normal', 'Deep Sleep 2.5h'
}

export interface HabitGoal {
  id: string;
  title: string;
  currentValueStr: string; // e.g., '1200ml'
  progressPercentage: number; // 0-100
  colorTheme: string; // Tailwind class, e.g., 'bg-blue-400'
}
```

## 5. Component Breakdown
- **`VitalsHero`**: The top section holding the "今日数据看板" title and a grid of `VitalCard`s.
- **`VitalCard`**: Generic container accepting an icon, title, value, unit, and status tag.
- **`HabitList`**: Maps an array of `HabitGoal` to rendered `HabitRow` components.
- **`HabitRow`**: Includes a checkmark icon (lit up if progress > 0), text descriptors, and a relative width progress bar.

## 6. API / Mock Data Requirements
- Requires mock dataset for variables like 72 bpm, 7h30m sleep, and an array of 3 daily habit goals (water, steps, BP).
