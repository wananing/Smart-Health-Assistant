import type { ChatMessage, AgentStep, ChatMode, ChatCardPayload, ThreadId } from '../types';

/** Maps LangGraph node names to ChatMode strings */
const NODE_TO_CHAT_MODE: Record<string, ChatMode> = {
    clinic_node: 'clinic',
    insurance_node: 'insurance',
    report_node: 'report',
    pharmacy_node: 'pharmacy',
    // advisor_node returning 'general' signals the user is exiting a specialized mode
    advisor_node: 'general',
};

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

let _stepCounter = 0;
const genStepId = () => `step-${++_stepCounter}-${Date.now()}`;

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
                    const data = JSON.parse(jsonStr);

                    switch (data.type) {
                        case 'session':
                            if (options.onSession && data.thread_id) {
                                options.onSession(data.thread_id as ThreadId);
                            }
                            break;

                        case 'interrupt':
                            options.onInterrupt?.(data.content ?? '');
                            break;

                        case 'text':
                            options.onChunk(data.content ?? '');
                            break;

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
                            console.log('[chatService] node_start:', data.node, '→ mode:', NODE_TO_CHAT_MODE[data.node] ?? '(no mapping)');
                            if (data.node && NODE_TO_CHAT_MODE[data.node] && options.onModeChange) {
                                console.log('[chatService] calling onModeChange:', NODE_TO_CHAT_MODE[data.node]);
                                options.onModeChange(NODE_TO_CHAT_MODE[data.node]);
                            }
                            break;
                        }

                        case 'node_end':
                            options.onStepFinish(data.node ?? '');
                            break;

                        case 'tool_start': {
                            const step: AgentStep = {
                                id: genStepId(),
                                type: 'tool_start',
                                tool: data.tool,
                                content: data.content ?? `调用工具：${data.tool}`,
                                isFinished: false,
                            };
                            options.onStep(step);
                            break;
                        }

                        case 'tool_end':
                            options.onStepFinish(data.tool ?? '');
                            break;

                        case 'card':
                            if (options.onCard && data.payload) {
                                options.onCard(data.payload as ChatCardPayload);
                            }
                            break;

                        case 'finish':
                            done = true;
                            break;

                        case 'error':
                            options.onError(new Error(data.content ?? '未知错误'));
                            done = true;
                            break;
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
