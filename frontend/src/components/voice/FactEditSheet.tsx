import { useState } from 'react';
import type { FC } from 'react';
import type { SymptomFactField, SymptomFacts } from '../../types';
import { SYMPTOM_FACT_FIELDS, formatFactValue } from './symptomFactLabels';

interface FactEditSheetProps {
    initialField: SymptomFactField;
    facts: Partial<SymptomFacts>;
    onSave: (field: SymptomFactField, value: string) => void;
    onCancel: () => void;
    isElderMode: boolean;
}

/** Bottom sheet for correcting a symptom field by typing; any field can be picked. */
const FactEditSheet: FC<FactEditSheetProps> = ({ initialField, facts, onSave, onCancel, isElderMode }) => {
    const [field, setField] = useState(initialField);
    const [value, setValue] = useState(() => formatFactValue(facts, initialField));
    const meta = SYMPTOM_FACT_FIELDS.find(item => item.field === field);

    const pick = (next: SymptomFactField) => {
        setField(next);
        setValue(formatFactValue(facts, next));
    };

    return (
        <div className="absolute inset-0 z-40 flex flex-col justify-end bg-ink-900/30 backdrop-blur-sm" onClick={onCancel}>
            <div
                role="dialog"
                aria-label="修改症状要点"
                className="bg-white rounded-t-card px-5 pt-3 pb-[max(env(safe-area-inset-bottom),1.5rem)] space-y-4 shadow-floating animate-rise motion-reduce:animate-none"
                onClick={event => event.stopPropagation()}
            >
                <div className="w-10 h-1.5 bg-ink-200 rounded-full mx-auto" />
                <p className={`font-semibold text-ink-900 ${isElderMode ? 'text-headline' : 'text-callout'}`}>修改症状要点</p>
                <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="选择要修改的要点">
                    {SYMPTOM_FACT_FIELDS.map(item => (
                        <button
                            key={item.field}
                            type="button"
                            role="tab"
                            aria-selected={item.field === field}
                            data-edit-field={item.field}
                            onClick={() => pick(item.field)}
                            className={`rounded-full px-3 py-1.5 font-medium transition ${isElderMode ? 'text-callout' : 'text-body'} ${item.field === field
                                ? 'bg-brand-700 text-white shadow-raised'
                                : 'bg-ink-100 text-ink-700 hover:bg-ink-200'}`}
                        >
                            {item.label}
                        </button>
                    ))}
                </div>
                <textarea
                    autoFocus
                    value={value}
                    onChange={event => setValue(event.target.value)}
                    placeholder={meta?.placeholder}
                    aria-label={meta?.label}
                    rows={2}
                    className={`w-full resize-none rounded-control bg-ink-50 p-3.5 text-ink-900 ring-1 ring-inset ring-ink-200 placeholder:text-ink-500 focus:outline-none focus:ring-2 focus:ring-brand-600 ${isElderMode ? 'text-headline' : 'text-callout'}`}
                />
                <div className="grid grid-cols-2 gap-3">
                    <button
                        type="button"
                        onClick={onCancel}
                        className={`rounded-control bg-ink-100 font-semibold text-ink-700 hover:bg-ink-200 transition ${isElderMode ? 'h-14 text-title' : 'h-12 text-callout'}`}
                    >
                        取消
                    </button>
                    <button
                        type="button"
                        onClick={() => onSave(field, value.trim())}
                        disabled={!value.trim()}
                        className={`rounded-control bg-brand-700 font-semibold text-white shadow-raised hover:bg-brand-800 transition disabled:bg-ink-100 disabled:text-ink-500 disabled:shadow-none ${isElderMode ? 'h-14 text-title' : 'h-12 text-callout'}`}
                    >
                        保存
                    </button>
                </div>
            </div>
        </div>
    );
};

export default FactEditSheet;
