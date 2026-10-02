import { ChevronRight, Flame, Moon, Phone } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import GlobalChatView from '../../components/chat/GlobalChatView';
import ChatModeHeader from '../../components/chat/ChatModeHeader';
import SuggestionScroller from '../../components/chat/SuggestionScroller';

const STEP_GOAL_PERCENT = 85;
const RING_CIRCUMFERENCE = 2 * Math.PI * 16;

const HomeScreen = () => {
    const { isElderMode, setIsElderMode, chatMode, setChatMode, messages, openVoiceCall } = useGlobalStore();
    const isIdle = messages.length <= 1 && chatMode === 'general';

    const sendStarter = (text: string) => {
        window.dispatchEvent(new CustomEvent('chat:send', { detail: text }));
    };

    return (
        <div className="flex flex-col h-full overflow-hidden relative pb-24 font-cn bg-gradient-to-b from-brand-50 via-white to-ink-50">
            {/* Header: brand mark, status and the elder-mode switch */}
            <header className="shrink-0 z-10 flex items-center justify-between gap-3 px-5 pt-[max(env(safe-area-inset-top),1rem)] pb-3">
                <div className="flex items-center gap-3 min-w-0">
                    <div className={`rounded-full bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-white font-semibold shadow-raised shrink-0 ${isElderMode ? 'w-12 h-12 text-title' : 'w-10 h-10 text-callout'}`}>
                        健
                    </div>
                    <div className="min-w-0">
                        <h1 className={`font-semibold text-ink-900 truncate ${isElderMode ? 'text-title' : 'text-callout'}`}>大健康 AI 助手</h1>
                        <p className={`flex items-center gap-1.5 whitespace-nowrap text-ink-600 ${isElderMode ? 'text-body' : 'text-caption'}`}>
                            <span className="w-1.5 h-1.5 rounded-full bg-success-500 shrink-0" />
                            <span className="truncate">在线 · 随时为您服务</span>
                        </p>
                    </div>
                </div>
                <button
                    onClick={() => setIsElderMode(!isElderMode)}
                    role="switch"
                    aria-checked={isElderMode}
                    className={`shrink-0 flex items-center gap-2 rounded-full bg-white/90 pl-3.5 pr-1.5 font-semibold text-ink-800 shadow-raised ring-1 ring-inset ring-ink-200 active:scale-[0.98] transition duration-fast ${isElderMode ? 'h-11 text-callout' : 'h-9 text-body'}`}
                >
                    长辈模式
                    <span className={`relative rounded-full transition-colors duration-base ${isElderMode ? 'w-11 h-6 bg-brand-600' : 'w-9 h-5 bg-ink-300'}`}>
                        <span className={`absolute top-0.5 left-0.5 rounded-full bg-white shadow-raised transition-transform duration-base ${isElderMode ? 'w-5 h-5 translate-x-5' : 'w-4 h-4'}`} />
                    </span>
                </button>
            </header>

            {/* Elder mode: a big voice clinic entry; everyone else has the phone button by the input */}
            {isElderMode && (
                <div className="shrink-0 px-4 pb-3">
                    <button
                        onClick={openVoiceCall}
                        className={`w-full flex items-center rounded-card bg-gradient-to-br from-brand-600 to-brand-800 text-left text-white shadow-floating active:scale-[0.98] transition duration-fast ${isElderMode ? 'gap-4 px-5 py-4' : 'gap-3.5 px-4 py-3.5'}`}
                    >
                        <span className={`relative rounded-full bg-white/20 ring-1 ring-inset ring-white/30 flex items-center justify-center shrink-0 ${isElderMode ? 'w-14 h-14' : 'w-12 h-12'}`}>
                            <span className="absolute inset-0 rounded-full bg-white/20 animate-breathe motion-reduce:animate-none" />
                            <Phone size={isElderMode ? 26 : 22} fill="currentColor" strokeWidth={0} className="relative" />
                        </span>
                        <span className="flex-1 min-w-0">
                            <span className={`block font-semibold ${isElderMode ? 'text-headline' : 'text-title'}`}>语音问诊</span>
                            <span className={`block text-brand-50 ${isElderMode ? 'text-callout' : 'text-body'}`}>像打电话一样说症状</span>
                        </span>
                        <ChevronRight size={isElderMode ? 24 : 20} className="shrink-0 text-brand-100" />
                    </button>
                </div>
            )}

            {/* Today's health summary, only before the conversation starts */}
            {isIdle && (
                <div className="shrink-0 px-4 pb-2">
                    <button
                        onClick={() => setChatMode('dashboard')}
                        className="w-full text-left rounded-card bg-gradient-to-br from-white to-brand-50 p-4 shadow-raised active:scale-[0.99] transition duration-fast"
                    >
                        <div className={`flex items-center justify-between text-ink-600 ${isElderMode ? 'text-callout' : 'text-body'}`}>
                            <span>今日健康概览</span>
                            <ChevronRight size={16} className="text-ink-400" />
                        </div>
                        <div className="mt-2 flex items-center gap-4">
                            <div className="flex-1 min-w-0">
                                <div className="flex items-baseline gap-1.5">
                                    <span className={`font-semibold text-ink-900 tabular-nums ${isElderMode ? 'text-display' : 'text-headline'}`}>8,542</span>
                                    <span className={`text-ink-600 ${isElderMode ? 'text-callout' : 'text-body'}`}>步</span>
                                </div>
                                <div className={`mt-1.5 flex flex-wrap gap-x-4 gap-y-1 whitespace-nowrap text-ink-700 ${isElderMode ? 'text-callout' : 'text-body'}`}>
                                    <span className="flex items-center gap-1"><Flame size={14} className="text-warning-500" /> 320 千卡</span>
                                    <span className="flex items-center gap-1"><Moon size={14} className="text-info-500" /> 睡眠 7.5 小时</span>
                                </div>
                            </div>
                            <div className="relative w-14 h-14 shrink-0" aria-label={`今日步数目标完成 ${STEP_GOAL_PERCENT}%`}>
                                <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                                    <circle cx="18" cy="18" r="16" fill="none" strokeWidth="3.5" className="stroke-brand-100" />
                                    <circle
                                        cx="18" cy="18" r="16" fill="none" strokeWidth="3.5" strokeLinecap="round"
                                        className="stroke-brand-600"
                                        strokeDasharray={`${(STEP_GOAL_PERCENT / 100) * RING_CIRCUMFERENCE} ${RING_CIRCUMFERENCE}`}
                                    />
                                </svg>
                                <span className="absolute inset-0 flex items-center justify-center text-caption font-semibold text-brand-800 tabular-nums">{STEP_GOAL_PERCENT}%</span>
                            </div>
                        </div>
                    </button>
                </div>
            )}
            {isIdle && (
                <div className="shrink-0 pb-2">
                    <p className={`px-5 pb-1 text-ink-600 ${isElderMode ? 'text-body' : 'text-caption'}`}>可以这样问我</p>
                    <SuggestionScroller onSend={sendStarter} />
                </div>
            )}

            {/* Active chat mode banner */}
            <ChatModeHeader />

            {/* Chat history (scrollable) */}
            <div className="flex-1 overflow-y-auto min-h-0">
                <GlobalChatView />
            </div>
        </div>
    );
};

export default HomeScreen;
