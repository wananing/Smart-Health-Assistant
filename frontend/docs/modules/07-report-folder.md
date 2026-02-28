# 07. Report Folder Design Specification

## 1. Overview
The Report Folder ("检查报告夹") module is a digital archive for medical laboratory results and diagnostic imaging reports. It features a core "Photo Upload" flow that utilizes AI Optical Character Recognition (OCR) to extract structured data, highlight abnormalities, and append the results to a chronological timeline.

## 2. Key Features
- **Hero Upload Zone**: A massive dashed-border dropzone/button prompting users to snap a photo of their physical reports. Triggers the device camera/scanner UI.
- **Historical Report Feed**: A vertical list organizing past reports. Features sorting controls (e.g., "Sort by Date").
- **AI Interpretation Badges**: Each report card displays an AI status badge ("AI已解读" - AI Interpreted, or "正常" - Normal) and visually flags abnormal results with a red theme.

## 3. User Flows
- **Scan Report Flow**: Click Hero Upload Zone → `isScanning` activates holding `scanType='报告'` → Scanner overlay renders → Timeout/Scan complete → Routes to `home` and AI Assistant outputs "您的报告《血常规化验单》已成功提取！AI 发现您的“白细胞计数”略微偏高..."
- **Review History Flow**: Scroll down → View cards for specific dates (e.g., Blood Test, Thyroid Ultrasound) → Future expansion to a detailed viewer modal.

## 4. Data Dictionary (Types/Interfaces)

```typescript
export interface MedicalReport {
  id: string;
  title: string; // e.g., '血常规化验单' (Complete Blood Count)
  date: string; // ISO or 'YYYY-MM-DD'
  hospitalName: string;
  analysisStatus: 'Pending' | 'Normal' | 'AI Interpreted';
  isAbnormal: boolean; // Triggers the Rose/Red UI styling
  extractedData?: ReportDataPoint[];
}

export interface ReportDataPoint {
  metricName: string; // e.g., 'WBC'
  value: number;
  referenceRange: string;
  flag: 'H' | 'L' | 'N';
}
```

## 5. Component Breakdown
- **`UploadHero`**: The dashed-border button calling `setScanType('报告')`.
- **`ReportTimeline`**: Iterates through the list of `MedicalReport` objects.
- **`ReportCard`**: Conditionally renders normal (teal) vs. abnormal (rose) color schemes based on the `isAbnormal` boolean. Contains the icon, title, date, hospital, and status tag.

## 6. API / Mock Data Requirements
- Requires a mock AI OCR payload to inject into the `setMessages` history upon successful scanning.
- Mock array of `MedicalReport`s featuring at least one abnormal (Red) and one normal (Teal) result.
