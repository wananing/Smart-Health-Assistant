import type { FC } from 'react';
import { ClipboardList, Pencil } from 'lucide-react';
import type { SymptomFactField, SymptomFacts } from '../../types';
import { SYMPTOM_FACT_FIELDS, formatFactValue } from './symptomFactLabels';

interface SymptomFactsPanelProps {
    facts: Partial<SymptomFacts>;
    missing: SymptomFactField[];
    /** A recap confirmation is pending: highlight the card (the answers sit right below it) */
    confirmPending: boolean;
    onEdit: (field: SymptomFactField) => void;
    /** Collapse to a one-line summary (after the conclusion, and in elder mode where text is large) */
    compact: boolean;
    isElderMode: boolean;
}

/**
 * The 病历卡: filled facts as solid chips, empty ones listed as 待补充.
 * Every chip opens the editor, so ASR mistakes can be fixed by tapping.
 */
const SymptomFactsPanel: FC<SymptomFactsPanelProps> = ({
    facts, missing, confirmPending, onEdit, compact, isElderMode,
}) => {
    const filled = SYMPTOM_FACT_FIELDS.map(item => ({ ...item, value: formatFactValue(facts, item.field) })).filter(item => item.value);
    // Fields the backend still needs come first among the empty ones.
    const empty = SYMPTOM_FACT_FIELDS
        .filter(({ field }) => !formatFactValue(facts, field))
        .sort((a, b) => Number(missing.includes(b.field)) - Number(missing.includes(a.field)));

    const chipText = isElderMode ? 'text-title' : 'text-body';
    const labelText = isElderMode ? 'text-body' : 'text-caption';

    // Compact: one tappable summary row; the editor lists every field in full.
    if (compact) {
        return (
            <button
                type="button"
                aria-label="症状要点，点按修改"
                onClick={() => onEdit(filled[0]?.field ?? 'chief_complaint')}
                data-testid="facts-summary"
                className={`w-full flex items-center gap-2 rounded-card bg-white px-3.5 py-2.5 text-left shadow-raised transition duration-fast active:scale-[0.99] ${confirmPending ? 'ring-2 ring-warning-400' : ''} ${chipText}`}
            >
                <span className="w-6 h-6 shrink-0 rounded-full bg-brand-50 text-brand-700 flex items-center justify-center">
                    <ClipboardList size={14} />
                </span>
                <span className="shrink-0 font-semibold text-ink-800">症状要点</span>
                <span className="shrink-0 tabular-nums text-ink-500">{filled.length}/{SYMPTOM_FACT_FIELDS.length}</span>
                <span className="min-w-0 flex-1 truncate text-ink-700">{filled.length > 0 ? filled.map(item => item.value).join(' · ') : '点按补充'}</span>
                <Pencil size={14} className="shrink-0 text-ink-500" />
            </button>
        );
    }

    return (
        <section
            aria-label="症状要点"
            className={`relative rounded-card bg-white px-3.5 py-3 shadow-raised transition-shadow duration-slow ${confirmPending ? 'ring-2 ring-warning-400' : ''}`}
        >
            <div className="flex items-center justify-between mb-2">
                <span className={`flex items-center gap-1.5 font-semibold text-ink-800 ${isElderMode ? 'text-title' : 'text-body'}`}>
                    <span className="w-6 h-6 rounded-full bg-brand-50 text-brand-700 flex items-center justify-center">
                        <ClipboardList size={14} />
                    </span>
                    症状要点
                    <span className={`font-medium text-ink-500 tabular-nums ${labelText}`}>{filled.length}/{SYMPTOM_FACT_FIELDS.length}</span>
                </span>
                <span className={`text-ink-500 ${labelText}`}>{confirmPending ? '请核对' : '点按可修改'}</span>
            </div>

            {filled.length > 0 && <div className="flex flex-wrap gap-1.5">
                {filled.map(({ field, label, value }) => (
                    <button
                        key={field}
                        type="button"
                        data-fact={field}
                        data-filled="true"
                        onClick={() => onEdit(field)}
                        className={`group inline-flex items-baseline gap-1.5 max-w-full rounded-full bg-brand-50 pl-3 pr-2.5 py-1 text-left ring-1 ring-inset ring-brand-100 hover:ring-brand-300 active:scale-[0.98] transition ${chipText}`}
                    >
                        <span className={`shrink-0 text-brand-800 ${labelText}`}>{label}</span>
                        <span className="min-w-0 break-words font-semibold text-ink-900">{value}</span>
                        <Pencil size={11} className="shrink-0 self-center text-brand-700/60 group-hover:text-brand-700" />
                    </button>
                ))}
            </div>}

            {empty.length > 0 && (
                <p className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 ${filled.length > 0 ? 'mt-2' : ''} ${labelText}`}>
                    <span className="text-ink-500">待补充</span>
                    {empty.map(({ field, label }) => (
                        <button
                            key={field}
                            type="button"
                            data-fact={field}
                            data-filled="false"
                            onClick={() => onEdit(field)}
                            className={`underline decoration-dashed underline-offset-4 transition-colors duration-fast hover:text-brand-800 ${missing.includes(field) ? 'text-warning-800 decoration-warning-400' : 'text-ink-600 decoration-ink-300'}`}
                        >
                            {label}
                        </button>
                    ))}
                </p>
            )}
        </section>
    );
};

export default SymptomFactsPanel;
