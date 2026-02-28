import type { FC } from 'react';
import type { ChatCardPayload } from '../../types';
import { useGlobalStore } from '../../store/GlobalContext';

// Per-mode: gradient, icon, suggestion chips
const MODE_META: Record<string, {
    gradient: string;
    borderColor: string;
    iconBg: string;
    icon: string;
    chips: string[];
}> = {
    clinic: {
        gradient: 'from-emerald-50 to-teal-50',
        borderColor: 'border-emerald-100',
        iconBg: 'bg-emerald-500',
        icon: '🩺',
        chips: ['头晕头痛', '胃肠不适', '咳嗽发烧', '睡眠问题'],
    },
    insurance: {
        gradient: 'from-blue-50 to-sky-50',
        borderColor: 'border-blue-100',
        iconBg: 'bg-blue-500',
        icon: '🏦',
        chips: ['查医保余额', '消费明细', '缴费记录', '异地就医'],
    },
    pharmacy: {
        gradient: 'from-orange-50 to-amber-50',
        borderColor: 'border-orange-100',
        iconBg: 'bg-orange-500',
        icon: '💊',
        chips: ['查药品说明', '扫描药盒', '附近药店', '药品相互作用'],
    },
    report: {
        gradient: 'from-purple-50 to-indigo-50',
        borderColor: 'border-purple-100',
        iconBg: 'bg-indigo-500',
        icon: '📋',
        chips: ['血常规解读', '肝功能指标', '血糖分析', '影像报告'],
    },
};

const EXIT_MODE_META: Record<string, { color: string; label: string; icon: string }> = {
    clinic: { color: 'text-emerald-600', label: '问诊', icon: '🩺' },
    insurance: { color: 'text-blue-600', label: '医保咨询', icon: '🏦' },
    pharmacy: { color: 'text-orange-600', label: '药管家', icon: '💊' },
    report: { color: 'text-indigo-600', label: '报告解读', icon: '📋' },
};

// ─── Welcome Card ────────────────────────────────────────────────────────────

interface WelcomeCardProps {
    payload: Extract<ChatCardPayload, { type: 'mode_welcome' }>;
}

export const ModeWelcomeCard: FC<WelcomeCardProps> = ({ payload }) => {
    const { exitChatMode } = useGlobalStore();
    const meta = MODE_META[payload.mode];
    if (!meta) return null;

    const handleChip = (chip: string) => {
        window.dispatchEvent(new CustomEvent('chat:send', { detail: chip }));
    };

    return (
        <div className={`rounded-2xl border ${meta.borderColor} bg-gradient-to-br ${meta.gradient} p-4 shadow-sm animate-in slide-in-from-bottom-2`}>
            {/* Header */}
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5">
                    <div className={`w-9 h-9 ${meta.iconBg} rounded-xl flex items-center justify-center text-lg shadow-sm`}>
                        {meta.icon}
                    </div>
                    <span className="font-bold text-slate-800 text-sm leading-tight">{payload.title.replace(/^[^\s]+\s/, '')}</span>
                </div>
                <button
                    onClick={exitChatMode}
                    className="text-slate-400 hover:text-slate-600 text-xs font-medium px-2 py-1 rounded-lg hover:bg-white/60 transition-all"
                >
                    退出
                </button>
            </div>

            {/* Description */}
            <p className="text-slate-600 text-sm leading-relaxed mb-3">{payload.description}</p>

            {/* Quick suggestion chips */}
            <div className="flex flex-wrap gap-2">
                {meta.chips.map((chip) => (
                    <button
                        key={chip}
                        onClick={() => handleChip(chip)}
                        className="px-3 py-1.5 bg-white/70 hover:bg-white text-slate-700 hover:text-slate-900 rounded-full text-xs font-medium border border-white shadow-sm transition-all active:scale-95"
                    >
                        {chip}
                    </button>
                ))}
            </div>
        </div>
    );
};

// ─── Exit Card ───────────────────────────────────────────────────────────────

interface ExitCardProps {
    payload: Extract<ChatCardPayload, { type: 'mode_exit' }>;
}

export const ModeExitCard: FC<ExitCardProps> = ({ payload }) => {
    const meta = EXIT_MODE_META[payload.mode];
    if (!meta) return null;

    return (
        <div className="flex flex-col items-center justify-center py-4 px-2 animate-in fade-in w-full">
            {/* Divider line */}
            <div className="flex items-center gap-4 w-full max-w-sm mb-2 opacity-80">
                <div className="flex-1 h-px bg-slate-200" />
                <div className={`flex items-center gap-1.5 text-xs font-medium ${meta.color} bg-white/60 px-3 py-1 rounded-full border border-slate-100 shadow-sm backdrop-blur-sm`}>
                    <span>{meta.icon}</span>
                    <span>{payload.title}</span>
                </div>
                <div className="flex-1 h-px bg-slate-200" />
            </div>
            {payload.summary && (
                <p className="text-slate-400 text-[11px] text-center">{payload.summary}</p>
            )}
        </div>
    );
};
