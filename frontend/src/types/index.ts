// 00-core-architecture
export interface UserProfile {
    id: string;
    name: string;
    age?: number;
    gender?: 'M' | 'F';
    isVip?: boolean;
}

export type ScreenType =
    | 'home'
    | 'clinic'
    | 'insurance'
    | 'pharmacy'
    | 'dashboard'
    | 'services'
    | 'report';

/** The active conversational context - determines the UI state of the chat */
export type ChatMode = 'general' | 'clinic' | 'insurance' | 'pharmacy' | 'report' | 'dashboard';

/** A structured UI card payload that can be embedded in a chat message */
export type ChatCardPayload =
    | { type: 'insurance_balance'; data: Record<string, unknown> }
    | { type: 'insurance_expenses'; data: Record<string, unknown> }
    | { type: 'insurance_payments'; data: Record<string, unknown> }
    | { type: 'insurance_cross_region'; data: Record<string, unknown> }
    | { type: 'clinic_recommendation'; data: Record<string, unknown> }
    | { type: 'report_analysis'; data: Record<string, unknown> }
    | { type: 'medication_task'; data: Record<string, unknown> }
    | { type: 'hospital_list'; data: Record<string, unknown> }
    /** Context transition cards — injected when entering or exiting a ChatMode */
    | { type: 'mode_welcome'; mode: ChatMode; title: string; description: string }
    | { type: 'mode_exit'; mode: ChatMode; title: string; summary?: string };


// 01-ai-chat-root
export type MessageRole = 'user' | 'assistant' | 'system';

/** Represents a single intermediate agent action step during generation */
export interface AgentStep {
    id: string;
    type: 'node_start' | 'node_end' | 'tool_start' | 'tool_end';
    node?: string;
    tool?: string;
    content: string;
    isFinished: boolean;
}

export interface ChatMessage {
    id: string;
    role: MessageRole;
    text: string;
    timestamp: number;
    /** Agent intermediate steps collected during streaming */
    steps?: AgentStep[];
    /** Whether the assistant message is still being generated */
    isGenerating?: boolean;
    /** Structured UI cards to render below the text bubble */
    cards?: ChatCardPayload[];
    actionPayload?: {
        type: 'NAVIGATION' | 'SUGGESTION_UPDATE';
        targetScreen?: ScreenType;
    };
}


export interface NavigationModule {
    id: ScreenType;
    name: string;
    iconRef: string; // Store icon string identifier to avoid circular dependencies with React components early on
}

// 02-ai-clinic
export interface ClinicSession {
    sessionId: string;
    step: 0 | 1 | 2;
    patientId: string;
    symptomsText: string;
    audioDurationMs?: number;
}

export interface RecommendationCard {
    summary: string;
    departments: string[];
    severityLevel: 'low' | 'medium' | 'high';
}

// 03-insurance
export interface InsuranceAccount {
    accountId: string;
    regionCode: string;
    insuranceType: 'Employee' | 'Resident' | 'Rural';
    balance: number;
    lastUpdated: number;
}

export interface ServiceLink {
    label: string;
    subLabel: string;
    iconName: string;
    colorTheme: string;
    bgTheme: string;
}

// 04-pharmacy
export type ScanType = '药盒' | '追溯码' | '支付码' | '报告';

export interface MedicationTask {
    id: string;
    name: string;
    type: 'Capsule' | 'Tablet' | 'Liquid';
    timeScheduled: number | string;
    instruction: string;
    isCompleted: boolean;
}

// 05-health-dashboard
export interface VitalSign {
    type: 'HeartRate' | 'Sleep' | 'BloodPressure' | 'Steps';
    currentValue: number | string;
    unit: string;
    statusTag: string;
}

export interface HabitGoal {
    id: string;
    title: string;
    currentValueStr: string;
    progressPercentage: number;
    colorTheme: string;
}

// 06-medical-services
export interface HospitalListing {
    id: string;
    name: string;
    tags: string[];
    distanceKm: string;
    isSponsored: boolean;
}

// 07-report-folder
export interface MedicalReport {
    id: string;
    title: string;
    date: string;
    hospitalName: string;
    analysisStatus: 'Pending' | 'Normal' | 'AI Interpreted' | string;
    isAbnormal: boolean;
}
