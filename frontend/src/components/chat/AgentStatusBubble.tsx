import React from 'react';
import type { AgentStep } from '../../types';

interface AgentStatusBubbleProps {
    steps: AgentStep[];
    isGenerating: boolean;
}

const AgentStatusBubble: React.FC<AgentStatusBubbleProps> = ({ steps, isGenerating }) => {
    if (steps.length === 0 && !isGenerating) return null;

    const allDone = steps.length > 0 && steps.every(s => s.isFinished);
    const isEmpty = steps.length === 0;
    const latestUnfinished = steps.find(s => !s.isFinished);

    return (
        <div className="mb-2">
            <details open={!allDone} className="group">
                <summary className="cursor-pointer list-none">
                    <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-teal-50 border border-teal-100 rounded-full text-xs font-medium text-teal-700 hover:bg-teal-100 transition-colors">
                        {allDone ? (
                            <>
                                <span className="text-emerald-500">✓</span>
                                <span>处理完成</span>
                            </>
                        ) : isEmpty ? (
                            <>
                                <span className="inline-block w-3 h-3 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
                                <span>智能体思考中...</span>
                            </>
                        ) : (
                            <>
                                <span className="inline-block w-3 h-3 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
                                <span>{latestUnfinished?.content ?? '正在处理...'}</span>
                            </>
                        )}
                        <span className="text-teal-400 group-open:rotate-180 transition-transform">▾</span>
                    </div>
                </summary>

                <div className="mt-2 ml-2 pl-3 border-l-2 border-teal-100 space-y-1">
                    {steps.map(step => (
                        <div key={step.id} className="flex items-center gap-2 text-xs text-slate-500">
                            {step.isFinished ? (
                                <span className="text-emerald-400 shrink-0">✓</span>
                            ) : (
                                <span className="inline-block w-2.5 h-2.5 border-2 border-teal-300 border-t-transparent rounded-full animate-spin shrink-0" />
                            )}
                            <span className={step.isFinished ? 'text-slate-400' : 'text-slate-600 font-medium'}>
                                {step.content}
                            </span>
                        </div>
                    ))}
                </div>
            </details>
        </div>
    );
};

export default AgentStatusBubble;
