import { ChevronRight, Zap, Activity } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import GlobalChatView from '../../components/chat/GlobalChatView';
import ChatModeHeader from '../../components/chat/ChatModeHeader';

const SUGGESTIONS = [
    "大便带血的原因",
    "降压药能停吗",
    "适合老年人的运动",
    "最近血压高怎么办",
    "医保账户怎么查",
];

const HomeScreen = () => {
    const { isElderMode, setIsElderMode, setChatMode, messages } = useGlobalStore();

    const handleSuggestionClick = (text: string) => {
        window.dispatchEvent(new CustomEvent('chat:send', { detail: text }));
    };

    return (
        <div className="flex flex-col h-full animate-in fade-in duration-500 overflow-hidden bg-slate-50 relative pb-24">
            {/* Top status bar */}
            <div className="bg-white border-b border-slate-100 shadow-sm flex-shrink-0 z-10">
                <div className="p-4 flex justify-between items-center">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-teal-500 flex items-center justify-center text-white font-bold text-lg shadow-md shadow-teal-100">健</div>
                        <div>
                            <h1 className={`font-bold text-slate-800 ${isElderMode ? 'text-xl' : 'text-base'}`}>大健康 AI 助手</h1>
                            <p className="text-teal-600 text-xs font-medium">在线中 · 随时为您服务</p>
                        </div>
                    </div>
                    <button
                        onClick={() => setIsElderMode(!isElderMode)}
                        className={`px-3 py-1.5 rounded-full font-bold transition-all shadow-sm text-sm ${isElderMode ? 'bg-orange-500 text-white shadow-orange-200' : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'}`}
                    >
                        {isElderMode ? '退出长辈模式' : '长辈模式'}
                    </button>
                </div>

                {/* Health dashboard only shown in idle state (no chat yet) */}
                {messages.length <= 1 && (
                    <div className="px-4 pb-4">
                        <div
                            className="bg-gradient-to-br from-teal-500 to-emerald-400 text-white rounded-2xl p-4 shadow-lg shadow-teal-100 mb-3 cursor-pointer hover:-translate-y-0.5 transition-all"
                            onClick={() => setChatMode('dashboard')}
                        >
                            <div className="flex justify-between items-center mb-2 text-teal-50 text-xs font-bold">
                                <span>我的健康 · 今日概览</span>
                                <ChevronRight size={14} />
                            </div>
                            <div className="flex items-end gap-1.5">
                                <span className={`font-black leading-none ${isElderMode ? 'text-5xl' : 'text-3xl'}`}>8,542</span>
                                <span className="text-teal-50 pb-0.5 text-sm font-medium">步</span>
                                <div className="ml-auto w-12 h-12 relative">
                                    <svg className="w-full h-full" viewBox="0 0 36 36">
                                        <path className="stroke-current text-teal-600/30" strokeWidth="4" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                        <path className="stroke-current text-white" strokeWidth="4" strokeDasharray="75, 100" strokeLinecap="round" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    </svg>
                                    <div className="absolute inset-0 flex items-center justify-center text-[9px] font-bold">75%</div>
                                </div>
                            </div>
                            <div className="mt-2 text-xs text-teal-50 flex gap-3">
                                <span className="flex items-center gap-1"><Zap size={12} className="text-yellow-300" /> 320kcal</span>
                                <span className="flex items-center gap-1"><Activity size={12} /> 睡眠 7.5h</span>
                            </div>
                        </div>

                        {/* Quick suggestion pills */}
                        <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
                            {SUGGESTIONS.map((tag, i) => (
                                <button
                                    key={i}
                                    onClick={() => handleSuggestionClick(tag)}
                                    className="whitespace-nowrap px-3 py-1.5 bg-slate-50 hover:bg-teal-50 text-slate-600 hover:text-teal-700 rounded-full text-xs font-medium border border-slate-100 transition-colors"
                                >
                                    {tag}
                                </button>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* Active chat mode banner */}
            <ChatModeHeader />

            {/* Chat history (scrollable) */}
            <div className="flex-1 overflow-y-auto min-h-0 pb-52">
                <GlobalChatView />
            </div>
        </div>
    );
};

export default HomeScreen;
