# 00. Core Architecture & Global State Design Specification

## 1. Overview
This module defines the foundational architecture of the application, managing global cross-cutting concerns such as the user session, visual theme (Elder Mode), system-wide active screen routing, and centralized state sharing. It ensures all child sub-modules have access to unified configurations.

## 2. Key Features
- **Global Store Management**: Centralized single source of truth for app state (using React Context or Zustand).
- **Elder Mode (Accessibility Theme)**: Global toggle that dynamically adjusts typography, spacing, and layout to be more accessible for senior users.
- **Client-Side Routing / Screen Manager**: Controls the top-level active view (`currentScreen`) swap without full page reloads.
- **Mock Data Engine**: Central repository for simulating backend API responses to enable offline frontend design development.

## 3. User Flows
- **Theme Toggle**: User clicks "Elder Mode" → Global state updates `isElderMode = true` → Root wrapper adds `.elder-mode` CSS class → All child components re-render with larger fonts.
- **Screen Navigation**: User clicks the "Report" tab → Global state updates `currentScreen = 'report'` → `MobileWrapper` unmounts current view and mounts `ReportScreen`.

## 4. Data Dictionary (Types/Interfaces)

```typescript
// Shared Types for Core Architecture
export interface UserProfile {
  id: string;
  name: string;
  age: number;
  gender: 'M' | 'F';
  isVip: boolean;
}

export interface AppState {
  isElderMode: boolean;
  currentScreen: ScreenType;
  user: UserProfile;
}

export type ScreenType = 
  | 'home'
  | 'clinic' 
  | 'insurance' 
  | 'pharmacy' 
  | 'dashboard' 
  | 'services' 
  | 'report';
```

## 5. Component Breakdown
- **`App` (Root)**: Initializes Context Providers, global CSS imports, and mounts `MobileWrapper`.
- **`MobileWrapper`**: The primary physical device simulator container (`sm:w-[390px]`, `sm:h-[844px]`).
- **`GlobalStoreProvider`**: The Context Provider component wrapping `Children` that holds the `AppState`.

## 6. API / Mock Data Requirements
- Requires static initial mock data for `SYSTEM_NAME` ("大健康 AI") and `USER_NAME` ("王*虎").
