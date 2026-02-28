# 06. Medical Services Design Specification

## 1. Overview
The Medical Services ("就医服务") module centralizes access to official healthcare resources, including hospital directories, appointment booking (outpatient and physicals), and intelligent triaging based on location.

## 2. Key Features
- **Smart Triage Search Bar**: A prominent, wide text input that handles keywords ("医院、科室、医生" - Hospital, Dept, Doctor).
- **Service Quick Actions**: A 3-column grid for primary actions: "Appointment Booking", "Nearby Hospitals", and "Physical Exam Booking".
- **Hospital Recommendation Feed**: A curated list of nearby medical institutions (e.g., Beijing Union Medical College Hospital) tailored to the localized city (e.g., Beijing).
- **Ad/Sponsored Badges**: A visual tagging system separating organic hospital results from sponsored diagnostic centers (e.g., Ciming Checkup).

## 3. User Flows
- **Search Flow**: Entering query → AI routes or filters the hospital list.
- **Hospital Booking Flow**: Clicking "去预约" (Go to Book) on a card → Future expansion to an appointment scheduling sub-calendar.
- **City Switch Flow**: Clicking "切换城市" (Switch City) → Future expansion to a geolocation selector picker.

## 4. Data Dictionary (Types/Interfaces)

```typescript
export interface HospitalListing {
  id: string;
  name: string;
  tags: string[]; // e.g., ['三级甲等', '综合'] (Level 3A, General)
  distanceKm: number;
  isSponsored: boolean; // Flag to render the Ad badge
  bookingEndpoint: string;
}

export interface QuickService {
  label: string;
  iconName: string;
  colorTheme: string;
  bgTheme: string;
}
```

## 5. Component Breakdown
- **`SearchHeader`**: The gradient hero area containing the `SearchInput` mimicking an autocomplete bar.
- **`BookingActionGrid`**: The flex container holding mapped `QuickServiceCard`s.
- **`HospitalList`**: The vertical scroll container mapping `HospitalListing` to individual `HospitalCard` rows.
- **`HospitalCard`**: Displays the name, distance (with Pin icon), mapped tag badges, optional Ad tag, and the primary CTA button.

## 6. API / Mock Data Requirements
- Requires an array of `HospitalListing` (e.g., 协和, 北大三院, 慈铭).
- City default parameter initialized to "Beijing".
