import type { FC } from 'react';
import { Check } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useTextScale } from '../../design/textScale';

type Tone = 'danger' | 'info';

interface VitalCardProps {
    title: string;
    tone: Tone;
    icon: LucideIcon;
    value: string;
    unit: string;
    status: string;
}

// Tone only colours the icon; the card itself stays white like every other card.
const ICON_TONES: Record<Tone, string> = {
    danger: 'bg-danger-50 text-danger-500',
    info: 'bg-info-50 text-info-600',
};

const VitalCard: FC<VitalCardProps> = ({ title, tone, icon: Icon, value, unit, status }) => {
    const t = useTextScale();

    return (
        <div className="rounded-card bg-white p-4 shadow-raised">
            <div className="flex items-center justify-between">
                <span className={`text-ink-600 ${t.body}`}>{title}</span>
                <span className={`w-8 h-8 rounded-full flex items-center justify-center ${ICON_TONES[tone]}`}>
                    <Icon size={16} />
                </span>
            </div>
            <div className="mt-1 flex items-baseline gap-1">
                <span className={`font-semibold text-ink-900 tabular-nums ${t.headline}`}>{value}</span>
                <span className={`text-ink-600 ${t.caption}`}>{unit}</span>
            </div>
            <div className={`mt-2 inline-flex items-center gap-1 rounded-full bg-ink-50 px-2.5 py-0.5 text-ink-700 ring-1 ring-inset ring-ink-200 ${t.caption}`}>
                <Check size={12} strokeWidth={3} className="text-success-600" />{status}
            </div>
        </div>
    );
};

export default VitalCard;
