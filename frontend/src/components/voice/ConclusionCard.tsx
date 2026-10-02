import type { FC } from 'react';
import { ChevronRight, Stethoscope } from 'lucide-react';
import type { ClinicRecommendationData } from '../../types';

interface ConclusionCardProps {
    recommendation: ClinicRecommendationData;
    onOpenDetails: () => void;
    isElderMode: boolean;
}

const URGENCY: Record<'emergency' | 'soon' | 'routine', { label: string; style: string }> = {
    emergency: { label: '请立即就医', style: 'bg-danger-50 text-danger-800 ring-danger-200' },
    soon: { label: '建议尽快就诊', style: 'bg-warning-50 text-warning-800 ring-warning-200' },
    routine: { label: '可择期就诊', style: 'bg-brand-50 text-brand-800 ring-brand-200' },
};

/** The triage result, raised onto the call screen as soon as the card arrives. */
const ConclusionCard: FC<ConclusionCardProps> = ({ recommendation, onOpenDetails, isElderMode }) => {
    const urgency = recommendation.urgency ? URGENCY[recommendation.urgency] : null;
    const departments = recommendation.departments ?? [];

    return (
        <section
            data-testid="conclusion-card"
            aria-label="分诊建议"
            className="rounded-card bg-gradient-to-br from-white to-brand-50/70 p-3.5 shadow-raised animate-rise motion-reduce:animate-none"
        >
            <div className="flex items-center gap-2 mb-1.5">
                <span className="w-6 h-6 rounded-full bg-brand-700 text-white flex items-center justify-center shrink-0">
                    <Stethoscope size={13} />
                </span>
                <span className={`font-semibold text-ink-900 ${isElderMode ? 'text-title' : 'text-body'}`}>分诊建议</span>
                {urgency && (
                    <span className={`ml-auto rounded-full px-2 py-0.5 font-semibold ring-1 ring-inset ${urgency.style} ${isElderMode ? 'text-body' : 'text-caption'}`}>
                        {urgency.label}
                    </span>
                )}
            </div>
            {recommendation.summary && (
                <p className={`text-ink-700 ${isElderMode ? 'text-title' : 'text-body'}`}>{recommendation.summary}</p>
            )}
            <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                {departments.map(dept => (
                    <span key={dept} className={`rounded-full bg-brand-700 text-white px-2.5 py-0.5 font-semibold ${isElderMode ? 'text-callout' : 'text-caption'}`}>{dept}</span>
                ))}
                <button
                    type="button"
                    onClick={onOpenDetails}
                    className={`ml-auto inline-flex items-center gap-0.5 font-semibold text-brand-800 hover:text-brand-900 ${isElderMode ? 'text-callout' : 'text-caption'}`}
                >
                    完整建议 <ChevronRight size={14} />
                </button>
            </div>
        </section>
    );
};

export default ConclusionCard;
