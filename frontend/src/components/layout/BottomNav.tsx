import { useState, useEffect } from 'react';
import { useGlobalStore } from '../../store/GlobalContext';
import { MODULES } from '../../data/mockData';
import type { ChatMessage, ChatMode } from '../../types';
import SuggestionScroller from '../chat/SuggestionScroller';
import InputBar from '../chat/InputBar';

const BottomNav = () => {
    const { isElderMode, chatMode, enterChatMode, exitChatMode, messages, setMessages } = useGlobalStore();
    const [inputValue, setInputValue] = useState('');

    useEffect(() => {
        const handleCustomMessage = (e: Event) => {
            const ce = e as CustomEvent<string>;
            if (ce.detail) {
                handleSend(ce.detail);
            }
        };
        window.addEventListener('chat:send', handleCustomMessage);
        return () => window.removeEventListener('chat:send', handleCustomMessage);
    }, [messages, isElderMode]);

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
                onDone: () => updateAssistant(m => ({ ...m, isGenerating: false })),
                onError: (err) => {
                    console.error("Chat error:", err);
                    updateAssistant(m => ({ ...m, text: m.text + "\n[网络错误，请稍后再试]", isGenerating: false }));
                }
            },
            { elder_mode: isElderMode },
            chatMode
        );
    };

    return (
        <footer className="absolute bottom-0 left-0 w-full p-4 bg-white/95 backdrop-blur-md border-t border-slate-100 z-40 rounded-t-3xl shadow-[0_-10px_40px_rgba(0,0,0,0.03)] pb-6">
            <SuggestionScroller onSend={handleSend} />
            <InputBar inputValue={inputValue} setInputValue={setInputValue} onSend={() => handleSend()} />

            {/* Nav icons — switch chatMode context instead of navigating to pages */}
            <div className="flex justify-between mt-5 px-3">
                {MODULES.map((mod) => (
                    <button
                        key={mod.id}
                        onClick={() => enterChatMode(mod.id as ChatMode)}
                        className="flex flex-col items-center gap-1.5 group"
                    >
                        <div className={`w-11 h-11 rounded-2xl flex items-center justify-center transition-all duration-300 ${chatMode === mod.id ? 'bg-teal-500 text-white shadow-md shadow-teal-200' : 'bg-slate-50 text-slate-400 group-hover:bg-teal-50 group-hover:text-teal-600'}`}>
                            <mod.icon size={20} />
                        </div>
                        <span className={`font-bold transition-colors ${chatMode === mod.id ? 'text-teal-600' : 'text-slate-400'} ${isElderMode ? 'text-sm' : 'text-[10px]'}`}>{mod.name}</span>
                    </button>
                ))}
            </div>
        </footer>
    );
};

export default BottomNav;
