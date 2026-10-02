// 00-core-architecture

/** The active conversational context - determines the UI state of the chat */
export type ChatMode = 'general' | 'clinic' | 'insurance' | 'pharmacy' | 'report' | 'dashboard';

/** Server-side LangGraph conversation id, issued by the backend `session` SSE event */
export type ThreadId = string;

/** Payload the clinic subgraph streams as a `clinic_recommendation` card */
export type ClinicRecommendationData = {
    summary?: string;
    departments?: string[];
    /** UI severity, derived from `urgency` by the backend */
    severity?: 'low' | 'medium' | 'high';
    urgency?: 'emergency' | 'soon' | 'routine';
    notes?: string[];
};

/** Symptom profile the clinic subgraph extracts (`SymptomFacts` in `agents/clinic.py`) */
export interface SymptomFacts {
    chief_complaint: string;
    location: string;
    duration: string;
    severity: string;
    associated_symptoms: string[];
    onset: string;
    triggers: string;
}

export type SymptomFactField = keyof SymptomFacts;

/** One collected fact in the summary card, already rendered to a string by the backend */
export interface ClinicSummaryFact {
    field: string;
    label: string;
    value: string;
}

/**
 * Payload of the `clinic_summary` card the voice gateway sends after a call
 * ends (`build_clinic_summary` in `backend/voice/gateway.py`).
 */
export type ClinicSummaryData = {
    /** `incomplete`: the call ended before a triage conclusion */
    status: 'completed' | 'incomplete';
    consultant?: string;
    /** ISO timestamps */
    started_at?: string;
    ended_at?: string;
    duration_seconds?: number;
    chief_complaint?: string;
    /** Only the filled fields, in display order */
    facts?: ClinicSummaryFact[];
    departments?: string[];
    urgency?: 'emergency' | 'soon' | 'routine' | null;
    summary?: string;
    notes?: string[];
    /** Red flags the emergency gate matched during the call */
    emergency_flags?: string[];
    disclaimer?: string;
};

/** Call states the voice gateway announces with `state` frames */
export type VoiceServerState = 'listening' | 'thinking' | 'speaking' | 'emergency';

/** Which question a voice `interrupt` is waiting on */
export type VoiceInterruptKind = 'followup' | 'confirm';

/** One line of the call's live captions; user lines start as partials */
export interface VoiceCaption {
    id: string;
    role: 'user' | 'assistant';
    text: string;
    /** User: ASR final received. Assistant: no more text will be appended. */
    isFinal: boolean;
    timestamp: number;
    cards?: ChatCardPayload[];
}

/** A structured UI card payload that can be embedded in a chat message */
export type ChatCardPayload =
    | { type: 'insurance_balance'; data: Record<string, unknown> }
    | { type: 'insurance_expenses'; data: Record<string, unknown> }
    | { type: 'insurance_payments'; data: Record<string, unknown> }
    | { type: 'insurance_cross_region'; data: Record<string, unknown> }
    | { type: 'clinic_recommendation'; data: ClinicRecommendationData }
    | { type: 'clinic_summary'; data: ClinicSummaryData }
    | { type: 'report_analysis'; data: Record<string, unknown> }
    | { type: 'medication_task'; data: Record<string, unknown> }
    | { type: 'hospital_list'; data: Record<string, unknown> }
    | { type: 'sensitive_image_preview'; data: { imageUrl: string; label: string; hint?: string } }
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
}

// 02-ai-clinic

// 03-insurance

// 04-pharmacy

// 05-health-dashboard

export interface HabitGoal {
    title: string;
    /** Today's value as shown, e.g. "1200ml" */
    current: string;
    /** 0–100 */
    progress: number;
    /** Design-token tone of the progress bar */
    tone: 'brand' | 'info' | 'danger';
}

// 06-medical-services

// 07-report-folder
