import type { SymptomFactField, SymptomFacts } from '../../types';

/** Display order and labels of the seven `SymptomFacts` fields */
export const SYMPTOM_FACT_FIELDS: { field: SymptomFactField; label: string; placeholder: string }[] = [
    { field: 'chief_complaint', label: '主诉', placeholder: '最主要的不适，如：头疼' },
    { field: 'location', label: '部位', placeholder: '如：额头、右下腹' },
    { field: 'duration', label: '持续时间', placeholder: '如：三天' },
    { field: 'severity', label: '严重程度', placeholder: '轻微 / 中等 / 严重' },
    { field: 'associated_symptoms', label: '伴随症状', placeholder: '多个症状用顿号隔开，如：恶心、怕光' },
    { field: 'onset', label: '起病方式', placeholder: '如：突然开始、逐渐加重' },
    { field: 'triggers', label: '诱因', placeholder: '如：熬夜后加重，休息能缓解' },
];

/** The value as one display string; '' when the field is empty */
export const formatFactValue = (facts: Partial<SymptomFacts>, field: SymptomFactField): string => {
    const value = facts[field];
    if (Array.isArray(value)) return value.filter(Boolean).join('、');
    return typeof value === 'string' ? value.trim() : '';
};
