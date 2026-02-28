# 04. Pharmacy & Medication Design Specification

## 1. Overview
The Pharmacy ("药管家") module provides a centralized dashboard for managing personal and family medications. It features visual scanning tools for fast drug identification and verification, coupled with smart pill reminders and access to nearby pharmacy directories.

## 2. Key Features
- **Visual Dual-Core Engine**: Two distinct scanner triggers:
  - **"Pill Box Scan" (拍药盒)**: Identifies the drug name, fetches instructions, and compares prices nearby.
  - **"Traceability Barcode Scan" (扫追溯码)**: Verifies drug authenticity and checks expiration dates based on the 20-digit national code.
- **Medication Reminders**: A timeline-based card displaying upcoming doses, integrating "Take Medication" (`medTaken` toggle) actions to visually strike out completed tasks.
- **Family Medicine Cabinet**: A link to manage a shared inventory of household drugs and track expiry dates.

## 3. User Flows
- **Pill Identifier Flow**: User clicks "拍药盒" → `isScanning` activates holding `scanType='药盒'` → Scanner overlay renders → Timeout/Scan complete → Routes to `home` and AI Assistant outputs "识别成功！这是【布洛芬缓释胶囊】..."
- **Daily Adherence Flow**: Reminder card shows "Amoxicillin Clavulanate Potassium Capsule" → User clicks "去服用" → Button swaps to "已打卡", text gains strikethrough styling, card container fades slightly.

## 4. Data Dictionary (Types/Interfaces)

```typescript
export interface ScannerContext {
  mode: 'PillBox' | 'TraceabilityCode' | 'ReportScanner' | 'PaymentQR';
  isActive: boolean;
  onSuccess: (result: ScanResult) => void;
}

export interface MedicationTask {
  id: string;
  name: string;
  type: 'Capsule' | 'Tablet' | 'Liquid';
  timeScheduled: number; // timestamp or string '13:00'
  instruction: string; // e.g., '饭后半小时'
  isCompleted: boolean;
}
```

## 5. Component Breakdown
- **`VisualEngineGrid`**: Safely holds the two hero buttons invoking `setScanType('药盒')` and `setScanType('追溯码')`.
- **`ReminderSection`**: Includes a section header with notification bell, "家庭药箱" link, and a mapped list of `ReminderCard`s.
- **`ReminderCard`**: Handles its own local state `medTaken` to trigger CSS transition animations (opacity drop, scale-down, strikethrough).

## 6. API / Mock Data Requirements
- Requires integration with the global `setMessages` function upon successful scan to inject the LLM-simulated pharmaceutical response.
- Mock list of `MedicationTask` containing "阿莫西林克拉维酸钾" at 13:00.
