import type { FC } from 'react';
import { Activity, CheckCircle2, Droplets, Footprints } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { HabitGoal } from '../../types';
import { useTextScale } from '../../design/textScale';

const TONES: Record<HabitGoal['tone'], { bar: string; icon: string; Icon: LucideIcon }> = {
    info: { bar: 'bg-info-500', icon: 'bg-info-50 text-info-600', Icon: Droplets },
    brand: { bar: 'bg-brand-500', icon: 'bg-brand-50 text-brand-700', Icon: Footprints },
    danger: { bar: 'bg-danger-400', icon: 'bg-danger-50 text-danger-500', Icon: Activity },
};

const HabitRow: FC<{ habit: HabitGoal }> = ({ habit }) => {
    const t = useTextScale();
    const tone = TONES[habit.tone];
    const complete = habit.progress >= 100;
    const Icon = complete ? CheckCircle2 : tone.Icon;

    return (
        <div className="rounded-card bg-white p-4 shadow-raised flex items-center gap-3.5">
            <span className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${complete ? 'bg-success-50 text-success-600' : tone.icon}`}>
                <Icon size={20} />
            </span>
            <div className="flex-1 min-w-0">
                <div className="mb-2 flex items-baseline justify-between gap-2">
                    <span className={`font-semibold text-ink-900 truncate ${t.body}`}>{habit.title}</span>
                    <span className={`shrink-0 tabular-nums ${habit.progress > 0 ? 'text-ink-700' : 'text-ink-500'} ${t.caption}`}>{habit.current}</span>
                </div>
                <div
                    className="h-2 w-full rounded-full bg-ink-100 overflow-hidden"
                    role="progressbar"
                    aria-valuenow={habit.progress}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${habit.title} 完成度`}
                >
                    <div className={`h-full rounded-full transition-[width] duration-slow ${tone.bar}`} style={{ width: `${habit.progress}%` }} />
                </div>
            </div>
        </div>
    );
};

export default HabitRow;
