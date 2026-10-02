import type { FC } from 'react';
import { Stethoscope, ShieldCheck, Pill, FileText, Activity, Phone, X } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import type { ChatMode } from '../../types';

// Modes are told apart by icon and name; colour stays on the brand so the app reads as one product.
const MODE_CONFIG: Record<Exclude<ChatMode, 'general'>, {
    icon: FC<{ size?: number; className?: string }>;
    label: string;
}> = {
    clinic: { icon: Stethoscope, label: 'AI 诊室' },
    insurance: { icon: ShieldCheck, label: '医保专区' },
    pharmacy: { icon: Pill, label: '药管家' },
    report: { icon: FileText, label: '报告解读' },
    dashboard: { icon: Activity, label: '健康数据' },
};

const ChatModeHeader: FC = () => {
    const { chatMode, exitChatMode, openVoiceCall, isElderMode } = useGlobalStore();

    if (chatMode === 'general') return null;

    const config = MODE_CONFIG[chatMode];
    if (!config) return null;
    const Icon = config.icon;

    return (
        <div className="shrink-0 mx-4 mb-1 flex items-center gap-3 rounded-full bg-white/90 pl-1.5 pr-1.5 py-1.5 shadow-raised animate-rise motion-reduce:animate-none">
            <span className="w-9 h-9 rounded-full bg-brand-50 text-brand-700 flex items-center justify-center shrink-0">
                <Icon size={18} />
            </span>
            <span className={`flex-1 min-w-0 truncate font-semibold text-ink-900 ${isElderMode ? 'text-title' : 'text-callout'}`}>
                {config.label}
            </span>
            {chatMode === 'clinic' && (
                <button
                    onClick={openVoiceCall}
                    title="语音问诊"
                    className={`flex items-center gap-1.5 rounded-full bg-brand-700 px-3.5 font-semibold text-white shadow-raised hover:bg-brand-800 active:scale-[0.98] transition duration-fast shrink-0 ${isElderMode ? 'h-11 text-callout' : 'h-9 text-body'}`}
                >
                    <Phone size={15} fill="currentColor" strokeWidth={0} /> 语音问诊
                </button>
            )}
            <button
                onClick={exitChatMode}
                aria-label="退出当前模式"
                title="退出当前模式"
                className="w-9 h-9 rounded-full flex items-center justify-center text-ink-500 hover:bg-ink-100 hover:text-ink-800 transition-colors duration-base shrink-0"
            >
                <X size={18} />
            </button>
        </div>
    );
};

export default ChatModeHeader;
