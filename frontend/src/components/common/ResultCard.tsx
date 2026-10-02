import type { FC, ReactNode } from 'react';
import { Check } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useTextScale } from '../../design/textScale';

/**
 * Building blocks shared by every result card in the chat, so the cards read as
 * one family: a white raised card, an icon tile + title header, stat tiles,
 * tone badges and divided lists. See docs/design-system.md.
 */

export type Tone = 'brand' | 'success' | 'warning' | 'danger' | 'neutral';

// success is deliberately quiet: a neutral pill with a green check. A green pill
// would read like the teal brand chips next to it, and "fine" should not compete
// with what needs attention (warning / danger).
const BADGE_TONES: Record<Tone, string> = {
    brand: 'bg-brand-50 text-brand-800 ring-brand-200',
    success: 'bg-ink-50 text-ink-700 ring-ink-200',
    warning: 'bg-warning-50 text-warning-800 ring-warning-200',
    danger: 'bg-danger-50 text-danger-700 ring-danger-200',
    neutral: 'bg-ink-50 text-ink-700 ring-ink-200',
};

const ICON_TONES: Record<Tone, string> = {
    brand: 'bg-brand-50 text-brand-700',
    success: 'bg-success-50 text-success-700',
    warning: 'bg-warning-50 text-warning-700',
    danger: 'bg-danger-50 text-danger-600',
    neutral: 'bg-ink-100 text-ink-600',
};

interface ResultCardProps {
    icon: LucideIcon;
    title: ReactNode;
    /** Right side of the header: a badge or a short caption. */
    meta?: ReactNode;
    tone?: Tone;
    /** Outline the whole card in danger red (emergencies). */
    alert?: boolean;
    dataCard?: string;
    children?: ReactNode;
}

export const ResultCard: FC<ResultCardProps> = ({ icon: Icon, title, meta, tone = 'brand', alert = false, dataCard, children }) => {
    const t = useTextScale();
    return (
        <section
            data-card={dataCard}
            className={`rounded-card bg-white shadow-raised overflow-hidden font-cn animate-rise motion-reduce:animate-none ${alert ? 'ring-2 ring-inset ring-danger-200' : ''}`}
        >
            <header className="flex items-center gap-2.5 px-4 pt-4 pb-3">
                <span className={`w-9 h-9 rounded-control flex items-center justify-center shrink-0 ${ICON_TONES[tone]}`}>
                    <Icon size={18} />
                </span>
                <h3 className={`flex-1 min-w-0 truncate font-semibold text-ink-900 ${t.callout}`}>{title}</h3>
                {meta && <div className="shrink-0">{meta}</div>}
            </header>
            {children && <div className="px-4 pb-4 space-y-3">{children}</div>}
        </section>
    );
};

export const Badge: FC<{ tone?: Tone; children: ReactNode }> = ({ tone = 'neutral', children }) => {
    const t = useTextScale();
    return (
        <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 font-semibold ring-1 ring-inset ${t.caption} ${BADGE_TONES[tone]}`}>
            {tone === 'success' && <Check size={12} strokeWidth={3} className="text-success-600" />}
            {children}
        </span>
    );
};

const VALUE_TONES: Record<Tone, string> = {
    brand: 'text-brand-800',
    success: 'text-ink-900',
    warning: 'text-warning-700',
    danger: 'text-danger-700',
    neutral: 'text-ink-900',
};

/** A labelled number in a soft tile; use in a grid. */
export const Stat: FC<{ label: string; value: ReactNode; sub?: ReactNode; tone?: Tone }> = ({ label, value, sub, tone = 'neutral' }) => {
    const t = useTextScale();
    return (
        <div className="min-w-0 rounded-control bg-ink-50 px-3 py-2.5">
            <div className={`text-ink-600 ${t.caption}`}>{label}</div>
            <div className={`font-semibold tabular-nums truncate ${t.callout} ${VALUE_TONES[tone]}`}>{value}</div>
            {sub && <div className={`text-ink-600 truncate ${t.caption}`}>{sub}</div>}
        </div>
    );
};

/** Small section heading inside a card. */
export const SectionLabel: FC<{ children: ReactNode }> = ({ children }) => {
    const t = useTextScale();
    return <div className={`mb-1.5 text-ink-600 ${t.caption}`}>{children}</div>;
};

/** A soft footnote: tips, disclaimers. */
export const Note: FC<{ icon?: LucideIcon; children: ReactNode }> = ({ icon: Icon, children }) => {
    const t = useTextScale();
    return (
        <p className={`flex gap-2 rounded-control bg-ink-50 px-3 py-2.5 text-ink-700 ${t.caption}`}>
            {Icon && <Icon size={14} className="mt-0.5 shrink-0 text-ink-500" />}
            <span>{children}</span>
        </p>
    );
};
