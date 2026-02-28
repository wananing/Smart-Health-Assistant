import type { ChatMessage, AgentStep, ChatMode, ChatCardPayload } from '../types';

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

let _stepCounter = 0;
const genStepId = () => `step-${++_stepCounter}-${Date.now()}`;

export const streamChat = async (
    messages: ChatMessage[],
    options: ChatServiceOptions,
    userInfo?: UserInfoPayload,
    chatMode: ChatMode = 'general'
) => {
    try {
        const payload = {
            messages: messages.map(msg => ({
                role: msg.role,
                content: msg.text
            })),
            user_info: userInfo ?? {},
            chat_mode: chatMode
        };

        const response = await fetch('http://localhost:8000/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

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

        options.onDone();

    } catch (err) {
        options.onError(err instanceof Error ? err : new Error(String(err)));
    }
};
