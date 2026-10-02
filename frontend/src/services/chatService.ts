import type { ChatMessage, AgentStep, ChatMode, ChatCardPayload, ThreadId } from '../types';
import { dispatchStreamEvent, type StreamEvent } from './streamEvents';

export interface ChatServiceOptions {
    onChunk: (text: string) => void;
    onStep: (step: AgentStep) => void;
    onStepFinish: (nodeOrTool: string) => void;
    /** Called when LangGraph enters a specialized agent node, or advisor_node (general) to exit a mode */
    onModeChange?: (mode: ChatMode) => void;
    /** Called when a backend tool yields a structured UI card payload */
    onCard?: (card: ChatCardPayload) => void;
    /** Called with the server-side thread id so it can be reused on the next turn */
    onSession?: (threadId: ThreadId) => void;
    /**
     * Called when the graph suspended on an `interrupt()` (a clinic follow-up
     * question). The question itself already arrived as `text` chunks, so the
     * UI only needs this to know the turn ended with a pending question.
     */
    onInterrupt?: (question: string) => void;
    onDone: () => void;
    onError: (error: Error) => void;
}

export interface UserInfoPayload {
    name?: string;
    age?: number;
    medical_history?: string;
    elder_mode?: boolean;
    region?: string;
}

export type VisionScanType = 'report' | 'drug_box' | 'trace_code';

const consumeSseResponse = async (response: Response, options: ChatServiceOptions) => {
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }

    if (!response.body) {
        throw new Error("ReadableStream not yet supported in this browser.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let done = false;
    let buffer = '';

    while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;

        if (value) {
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            // Keep the last (potentially incomplete) line in the buffer
            buffer = lines.pop() ?? '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const jsonStr = line.slice(6).trim();
                if (!jsonStr) continue;

                try {
                    const data = JSON.parse(jsonStr) as StreamEvent;
                    if (data.type === 'finish') {
                        done = true;
                    } else if (data.type === 'error') {
                        options.onError(new Error(data.content ?? '未知错误'));
                        done = true;
                    } else {
                        dispatchStreamEvent(data, options);
                    }
                } catch {
                    // Ignore malformed JSON lines
                }
            }
        }
    }
};

export const streamChat = async (
    messages: ChatMessage[],
    options: ChatServiceOptions,
    userInfo?: UserInfoPayload,
    chatMode: ChatMode = 'general',
    threadId?: ThreadId | null
) => {
    try {
        // With a thread_id the backend checkpointer owns the history and only
        // needs the newest user message; without one it replays everything.
        const outbound = threadId ? messages.slice(-1) : messages;
        const payload = {
            messages: outbound.map(msg => ({
                role: msg.role,
                content: msg.text
            })),
            user_info: userInfo ?? {},
            chat_mode: chatMode,
            thread_id: threadId ?? null
        };

        const response = await fetch('http://localhost:8000/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        await consumeSseResponse(response, options);

        options.onDone();

    } catch (err) {
        options.onError(err instanceof Error ? err : new Error(String(err)));
    }
};

export const streamVisionChat = async (
    file: File,
    scanType: VisionScanType,
    messages: ChatMessage[],
    options: ChatServiceOptions,
    userInfo?: UserInfoPayload,
    threadId?: ThreadId | null
) => {
    try {
        const outbound = threadId ? messages.slice(-1) : messages;
        const formData = new FormData();
        formData.append('file', file);
        formData.append('scan_type', scanType);
        formData.append('user_info', JSON.stringify(userInfo ?? {}));
        formData.append('thread_id', threadId ?? '');
        formData.append('messages', JSON.stringify(outbound.map(msg => ({
            role: msg.role,
            content: msg.text
        }))));

        const response = await fetch('http://localhost:8000/api/vision-chat', {
            method: 'POST',
            body: formData
        });

        await consumeSseResponse(response, options);
        options.onDone();

    } catch (err) {
        options.onError(err instanceof Error ? err : new Error(String(err)));
    }
};
