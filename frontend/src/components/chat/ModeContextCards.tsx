import type { FC } from 'react';
import type { ChatCardPayload } from '../../types';
import { useGlobalStore } from '../../store/GlobalContext';

// Quick-start topics per mode. The mode's name and exit live in ChatModeHeader,
// so the welcome card only carries the introduction and these chips.
const MODE_CHIPS: Record<string, string[]> = {
    clinic: ['头晕头痛', '胃肠不适', '咳嗽发烧', '睡眠问题'],
    insurance: ['查医保余额', '消费明细', '缴费记录', '异地就医'],
    pharmacy: ['查药品说明', '扫描药盒', '附近药店', '药品相互作用'],
    report: ['血常规解读', '肝功能指标', '血糖分析', '影像报告'],
};

const EXIT_MODES = new Set(['clinic', 'insurance', 'pharmacy', 'report']);

// ─── Welcome Card ────────────────────────────────────────────────────────────

interface WelcomeCardProps {
    payload: Extract<ChatCardPayload, { type: 'mode_welcome' }>;
}

export const ModeWelcomeCard: FC<WelcomeCardProps> = ({ payload }) => {
    const { isElderMode } = useGlobalStore();
    const chips = MODE_CHIPS[payload.mode];
    if (!chips) return null;

    const handleChip = (chip: string) => {
        window.dispatchEvent(new CustomEvent('chat:send', { detail: chip }));
    };

    return (
        <div className="rounded-card bg-gradient-to-br from-white to-brand-50/70 p-4 shadow-raised animate-rise motion-reduce:animate-none">
            <p className={`text-ink-700 ${isElderMode ? 'text-title' : 'text-callout'}`}>{payload.description}</p>
            <p className={`mt-3 mb-2 text-ink-600 ${isElderMode ? 'text-body' : 'text-caption'}`}>可以这样问</p>
            <div className="flex flex-wrap gap-2">
                {chips.map((chip) => (
                    <button
                        key={chip}
                        onClick={() => handleChip(chip)}
                        className={`rounded-full bg-white px-3.5 text-brand-800 ring-1 ring-inset ring-brand-200 hover:bg-brand-50 active:scale-[0.98] transition duration-fast ${isElderMode ? 'h-11 text-callout' : 'h-9 text-body'}`}
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
    const { isElderMode } = useGlobalStore();
    if (!EXIT_MODES.has(payload.mode)) return null;

    return (
        <div className="flex flex-col items-center py-2 w-full animate-rise motion-reduce:animate-none">
            <div className="flex items-center gap-3 w-full">
                <div className="flex-1 h-px bg-ink-200" />
                <span className={`rounded-full bg-white/90 px-3 py-1 text-ink-600 shadow-raised ${isElderMode ? 'text-body' : 'text-caption'}`}>
                    {payload.title}
                </span>
                <div className="flex-1 h-px bg-ink-200" />
            </div>
            {payload.summary && (
                <p className={`mt-1.5 text-center text-ink-500 ${isElderMode ? 'text-body' : 'text-caption'}`}>{payload.summary}</p>
            )}
        </div>
    );
};
