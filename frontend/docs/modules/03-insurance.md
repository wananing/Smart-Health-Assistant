# 03. Insurance Manager Design Specification

## 1. Overview
The Insurance Manager ("查医保") module serves as a digital wallet for the National Medical Insurance Electronic Certificate. It displays real-time balance, provides a quick "Pay" barcode/QR code generation flow, and links to related financial and administrative healthcare services.

## 2. Key Features
- **Digital Insurance Card**: A prominently displayed gradient card showing the regional insurance type (e.g., "北京市 城镇职工医保") and a masked/unmasked balance toggle.
- **Quick Payment Gateway**: A prominent "去支付" (Go Pay) button that triggers a scanner/barcode presentation screen overlay for pharmacy or hospital checkout.
- **Service Grid**: A 2x2 grid offering quick access to "Consumption History", "Annual Payment Status", "Family Pooling Management", and "Cross-Provincial Registration".

## 3. User Flows
- **Balance Reveal Flow**: User opens Insurance → Clicks eye icon near "个人账户余额" → Balance changes from `****` to `2,458.32` → Eye icon swaps state.
- **Checkout Flow**: User selects "去支付" → `isScanning` triggers with `scanType='支付码'` → Scanner overlay covers screen → User presents code to terminal.

## 4. Data Dictionary (Types/Interfaces)

```typescript
export interface InsuranceAccount {
  accountId: string;
  regionCode: string; // e.g., '110000' for Beijing
  insuranceType: 'Employee' | 'Resident' | 'Rural';
  balance: number;
  lastUpdated: number; // timestamp
}

export interface ServiceLink {
  label: string;
  subLabel: string;
  iconRef: string; // Lucide icon name
  routePath: string; // Future routing target
  colorTheme: string; // Tailwind color prefix (e.g., 'teal', 'blue')
}
```

## 5. Component Breakdown
- **`InsuranceCard`**: The hero section. Contains the state `showBalance` and renders the mock balance.
- **`PayButton`**: An integrated trigger within the card that invokes `setScanType('支付码')`.
- **`ServiceGrid`**: Iterates over an array of `ServiceLink` objects to render the 4 action tiles.

## 6. API / Mock Data Requirements
- Requires a mock `fetchAccountBalance()` response (e.g., `2458.32`).
- Mock arrays for the bottom 4 services: "消费记录", "年度缴费", "共济管理", "异地备案".
