import type { FC } from 'react';

interface ProgressStepperProps {
    currentStep: number;
    onStepChange: (step: number) => void;
}

const ProgressStepper: FC<ProgressStepperProps> = ({ currentStep, onStepChange }) => {
    return (
        <div className="flex justify-between mb-8 px-2 relative">
            <div className="absolute top-1/2 left-0 w-full h-0.5 bg-slate-200 -z-10"></div>
            {['选咨询人', '描述症状', '诊疗建议'].map((step, i) => (
                <div key={i} className="flex flex-col items-center gap-2 cursor-pointer group" onClick={() => onStepChange(i)}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all ${currentStep >= i ? 'bg-teal-500 text-white shadow-md ring-4 ring-teal-50' : 'bg-white border border-slate-200 text-slate-400 group-hover:bg-slate-100'}`}>{i + 1}</div>
                    <span className={`text-xs ${currentStep >= i ? 'text-teal-600 font-bold' : 'text-slate-500'}`}>{step}</span>
                </div>
            ))}
        </div>
    );
};

export default ProgressStepper;
