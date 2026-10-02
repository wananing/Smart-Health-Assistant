import type { AgentStep, ChatCardPayload, ChatMode, ThreadId } from '../types';
import type { ChatServiceOptions } from './chatService';

/** Maps LangGraph node names to ChatMode strings */
const NODE_TO_CHAT_MODE: Record<string, ChatMode> = {
    clinic_node: 'clinic',
    insurance_node: 'insurance',
    report_node: 'report',
    pharmacy_node: 'pharmacy',
    // advisor_node returning 'general' signals the user is exiting a specialized mode
    advisor_node: 'general',
};

let _stepCounter = 0;
const genStepId = () => `step-${++_stepCounter}-${Date.now()}`;

/** One decoded SSE event (or the same-shaped JSON frame on the voice WebSocket) */
export interface StreamEvent {
    type: string;
    content?: string;
    node?: string;
    tool?: string;
    thread_id?: string;
    payload?: unknown;
}

/** The callbacks `dispatchStreamEvent` needs; the voice client supplies these too */
export type StreamEventHandlers = Omit<ChatServiceOptions, 'onDone' | 'onError'>;

/**
 * Handle the event types shared by the `/api/chat` SSE stream and the
 * `/api/voice` WebSocket: session, interrupt, text, node/tool steps and cards.
 * Returns false for any other type so the caller can handle it.
 */
export const dispatchStreamEvent = (data: StreamEvent, options: StreamEventHandlers): boolean => {
    switch (data.type) {
        case 'session':
            if (options.onSession && data.thread_id) {
                options.onSession(data.thread_id as ThreadId);
            }
            return true;

        case 'interrupt':
            options.onInterrupt?.(data.content ?? '');
            return true;

        case 'text':
            options.onChunk(data.content ?? '');
            return true;

        case 'node_start': {
            const step: AgentStep = {
                id: genStepId(),
                type: 'node_start',
                node: data.node,
                content: data.content ?? `进入节点：${data.node}`,
                isFinished: false,
            };
            options.onStep(step);
            // Automatically switch chatMode based on which agent node started
            console.log('[chatService] node_start:', data.node, '→ mode:', (data.node && NODE_TO_CHAT_MODE[data.node]) ?? '(no mapping)');
            if (data.node && NODE_TO_CHAT_MODE[data.node] && options.onModeChange) {
                console.log('[chatService] calling onModeChange:', NODE_TO_CHAT_MODE[data.node]);
                options.onModeChange(NODE_TO_CHAT_MODE[data.node]);
            }
            return true;
        }

        case 'node_end':
            options.onStepFinish(data.node ?? '');
            return true;

        case 'tool_start': {
            const step: AgentStep = {
                id: genStepId(),
                type: 'tool_start',
                tool: data.tool,
                content: data.content ?? `调用工具：${data.tool}`,
                isFinished: false,
            };
            options.onStep(step);
            return true;
        }

        case 'tool_end':
            options.onStepFinish(data.tool ?? '');
            return true;

        case 'card':
            if (options.onCard && data.payload) {
                options.onCard(data.payload as ChatCardPayload);
            }
            return true;

        default:
            return false;
    }
};
