import React from 'react';
import { Check, ChevronDown } from 'lucide-react';
import type { AgentStep } from '../../types';
import { useGlobalStore } from '../../store/GlobalContext';

interface AgentStatusBubbleProps {
    steps: AgentStep[];
    isGenerating: boolean;
}

const Spinner = ({ size }: { size: string }) => (
    <span className={`inline-block ${size} rounded-full border-2 border-accent-400 border-t-transparent animate-spin motion-reduce:animate-none shrink-0`} />
);

const AgentStatusBubble: React.FC<AgentStatusBubbleProps> = ({ steps, isGenerating }) => {
    const { isElderMode } = useGlobalStore();
    if (steps.length === 0 && !isGenerating) return null;

    const allDone = steps.length > 0 && steps.every(s => s.isFinished);
    const latestUnfinished = steps.find(s => !s.isFinished);
    const textSize = isElderMode ? 'text-body' : 'text-caption';

    return (
        <details open={!allDone} className="group">
            <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden">
                <span className={`inline-flex items-center gap-2 rounded-full bg-white/90 px-3 py-1.5 shadow-raised transition-colors duration-base ${textSize} ${allDone ? 'text-ink-600' : 'text-accent-700'}`}>
                    {allDone ? (
                        <>
                            <Check size={14} className="text-success-600" />
                            <span>已完成</span>
                        </>
                    ) : (
                        <>
                            <Spinner size="w-3 h-3" />
                            <span>{latestUnfinished?.content ?? '正在思考…'}</span>
                        </>
                    )}
                    {steps.length > 0 && (
                        <ChevronDown size={14} className="text-ink-400 group-open:rotate-180 transition-transform duration-base" />
                    )}
                </span>
            </summary>

            {steps.length > 0 && (
                <ol className="mt-2 ml-3 pl-3 border-l border-ink-200 space-y-1">
                    {steps.map(step => (
                        <li key={step.id} className={`flex items-center gap-2 ${textSize}`}>
                            {step.isFinished
                                ? <Check size={12} className="text-success-600 shrink-0" />
                                : <Spinner size="w-2.5 h-2.5" />}
                            <span className={step.isFinished ? 'text-ink-500' : 'text-ink-800'}>{step.content}</span>
                        </li>
                    ))}
                </ol>
            )}
        </details>
    );
};

export default AgentStatusBubble;
