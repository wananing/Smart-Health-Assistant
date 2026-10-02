import { useState, useEffect } from 'react';
import { useGlobalStore } from '../../store/GlobalContext';
import { MODULES } from '../../data/mockData';
import type { ChatMessage, ChatMode } from '../../types';
import type { VisionScanType } from '../../services/chatService';
import InputBar from '../chat/InputBar';

const getVisionUserText = (scanType: VisionScanType) => {
    if (scanType === 'report') return '上传了一张检查报告图片，请帮我解读。';
    if (scanType === 'trace_code') return '上传了一张药品追溯码图片，请帮我查看用药信息。';
    return '上传了一张药盒图片，请帮我看看这个药。';
};

const BottomNav = () => {
    const { isElderMode, chatMode, enterChatMode, exitChatMode, messages, setMessages, threadId, setThreadId } = useGlobalStore();
    const [inputValue, setInputValue] = useState('');
    const [isVisionUploading, setIsVisionUploading] = useState(false);

    useEffect(() => {
        const handleCustomMessage = (e: Event) => {
            const ce = e as CustomEvent<string>;
            if (ce.detail) {
                handleSend(ce.detail);
            }
        };
        window.addEventListener('chat:send', handleCustomMessage);
        return () => window.removeEventListener('chat:send', handleCustomMessage);
    }, [messages, isElderMode, threadId]);

    const handleSend = async (text = inputValue) => {
        const content = text.trim();
        if (!content) return;

        setInputValue('');

        const userMsg: ChatMessage = {
            id: `msg-user-${Date.now()}`,
            role: 'user',
            text: content,
            timestamp: Date.now()
        };

        const assistantMsgId = `msg-ai-${Date.now()}`;
        const assistantMsg: ChatMessage = {
            id: assistantMsgId,
            role: 'assistant',
            text: '',
            timestamp: Date.now(),
            steps: [],
            isGenerating: true,
        };

        const updatedMessages = [...messages, userMsg];
        setMessages([...updatedMessages, assistantMsg]);

        const { streamChat } = await import('../../services/chatService');

        const updateAssistant = (updater: (msg: ChatMessage) => ChatMessage) => {
            setMessages(prev =>
                prev.map(m => m.id === assistantMsgId ? updater({ ...m }) : m)
            );
        };

        await streamChat(
            updatedMessages,
            {
                onChunk: (chunk) => {
                    updateAssistant(m => ({ ...m, text: m.text + chunk }));
                },
                onStep: (step) => {
                    updateAssistant(m => ({
                        ...m,
                        steps: [...(m.steps ?? []), step],
                    }));
                },
                onStepFinish: (nodeOrTool: string) => {
                    updateAssistant(m => ({
                        ...m,
                        steps: (m.steps ?? []).map(s =>
                            (s.node === nodeOrTool || s.tool === nodeOrTool) && !s.isFinished
                                ? { ...s, isFinished: true }
                                : s
                        ),
                    }));
                },
                onModeChange: (mode: ChatMode) => {
                    if (mode === 'general') {
                        // Backend routed to advisor_node — user exited a specialized mode.
                        exitChatMode();
                    } else {
                        enterChatMode(mode);
                    }
                },
                onCard: (card) => {
                    updateAssistant(m => ({
                        ...m,
                        cards: [...(m.cards ?? []), card],
                    }));
                },
                onSession: setThreadId,
                onDone: () => updateAssistant(m => ({ ...m, isGenerating: false })),
                onError: (err) => {
                    console.error("Chat error:", err);
                    updateAssistant(m => ({ ...m, text: m.text + "\n[网络错误，请稍后再试]", isGenerating: false }));
                }
            },
            { elder_mode: isElderMode },
            chatMode,
            threadId
        );
    };

    const handleVisionUpload = async (file: File, scanType: VisionScanType) => {
        if (!file.type.startsWith('image/')) return;

        setIsVisionUploading(true);

        const assistantMsgId = `msg-ai-vision-${Date.now()}`;
        const previewUrl = URL.createObjectURL(file);
        const userMsg: ChatMessage = {
            id: `msg-user-vision-${Date.now()}`,
            role: 'user',
            text: getVisionUserText(scanType),
            timestamp: Date.now(),
            cards: scanType === 'report'
                ? [{
                    type: 'sensitive_image_preview',
                    data: {
                        imageUrl: previewUrl,
                        label: '报告图片',
                    },
                }]
                : undefined,
        };

        const assistantMsg: ChatMessage = {
            id: assistantMsgId,
            role: 'assistant',
            text: '',
            timestamp: Date.now(),
            steps: [],
            isGenerating: true,
        };

        const updatedMessages = [...messages, userMsg];
        setMessages([...updatedMessages, assistantMsg]);

        const updateAssistant = (updater: (msg: ChatMessage) => ChatMessage) => {
            setMessages(prev =>
                prev.map(m => m.id === assistantMsgId ? updater({ ...m }) : m)
            );
        };

        const { streamVisionChat } = await import('../../services/chatService');

        await streamVisionChat(
            file,
            scanType,
            updatedMessages,
            {
                onChunk: (chunk) => {
                    updateAssistant(m => ({ ...m, text: m.text + chunk }));
                },
                onStep: (step) => {
                    updateAssistant(m => ({
                        ...m,
                        steps: [...(m.steps ?? []), step],
                    }));
                },
                onStepFinish: (nodeOrTool: string) => {
                    updateAssistant(m => ({
                        ...m,
                        steps: (m.steps ?? []).map(s =>
                            (s.node === nodeOrTool || s.tool === nodeOrTool) && !s.isFinished
                                ? { ...s, isFinished: true }
                                : s
                        ),
                    }));
                },
                onModeChange: (mode: ChatMode) => {
                    if (mode === 'general') {
                        exitChatMode();
                    } else {
                        enterChatMode(mode);
                    }
                },
                onCard: (card) => {
                    updateAssistant(m => ({
                        ...m,
                        cards: [...(m.cards ?? []), card],
                    }));
                },
                onSession: setThreadId,
                onDone: () => {
                    setIsVisionUploading(false);
                    updateAssistant(m => ({ ...m, isGenerating: false }));
                },
                onError: (err) => {
                    console.error("Vision chat error:", err);
                    setIsVisionUploading(false);
                    updateAssistant(m => ({ ...m, text: m.text + "\n[图片识别失败，请稍后再试]", isGenerating: false }));
                }
            },
            { elder_mode: isElderMode },
            threadId,
        );
    };

    return (
        <footer className="absolute bottom-0 left-0 w-full z-40 font-cn rounded-t-card bg-white/95 backdrop-blur-md shadow-docked pt-3 pb-[max(env(safe-area-inset-bottom),0.75rem)]">
            {/* Module shortcuts — switch chatMode context instead of navigating to pages */}
            <nav className="flex gap-2 overflow-x-auto scrollbar-hide px-4 pb-3" aria-label="功能入口">
                {MODULES.map((mod) => {
                    const active = chatMode === mod.id;
                    return (
                        <button
                            key={mod.id}
                            onClick={() => enterChatMode(mod.id)}
                            aria-current={active ? 'page' : undefined}
                            className={`shrink-0 flex items-center gap-1.5 rounded-full pl-2.5 pr-3.5 whitespace-nowrap active:scale-[0.97] transition duration-fast ${isElderMode ? 'h-11 text-callout' : 'h-9 text-body'} ${active
                                ? 'bg-brand-700 text-white font-semibold shadow-raised'
                                : 'bg-white text-ink-700 ring-1 ring-inset ring-ink-200 hover:bg-brand-50 hover:ring-brand-200'}`}
                        >
                            <mod.icon size={isElderMode ? 20 : 16} className={active ? 'text-white' : 'text-brand-700'} />
                            {mod.name}
                        </button>
                    );
                })}
            </nav>
            <div className="px-4">
                <InputBar
                    inputValue={inputValue}
                    setInputValue={setInputValue}
                    onSend={() => handleSend()}
                    onVisionUpload={handleVisionUpload}
                    isVisionUploading={isVisionUploading}
                />
            </div>
        </footer>
    );
};

export default BottomNav;
