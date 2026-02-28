import type { FC } from 'react';
import { User, CheckCircle2 } from 'lucide-react';

interface PatientSelectorProps {
    onNext: () => void;
}

const PatientSelector: FC<PatientSelectorProps> = ({ onNext }) => {
    return (
        <div className="animate-in fade-in slide-in-from-bottom-4">
            <p className="font-bold text-slate-800 mb-3">本次为谁咨询？</p>
            <div className="p-4 bg-teal-50 rounded-2xl mb-4 border border-teal-200 cursor-pointer shadow-sm relative overflow-hidden">
                <div className="absolute -right-4 -top-4 text-teal-100/50"><User size={80} /></div>
                <label className="text-xs text-teal-600 font-bold uppercase mb-2 block relative z-10">当前选中</label>
                <div className="flex justify-between items-center relative z-10">
                    <span className="text-lg font-bold text-slate-800">本人 (王*虎)</span>
                    <CheckCircle2 className="text-teal-500" />
                </div>
            </div>
            <div className="p-4 bg-white rounded-2xl border border-slate-200 flex justify-between items-center text-slate-500 cursor-pointer hover:bg-slate-50 transition-colors">
                <span className="font-bold text-slate-700">父亲 (王*国)</span>
                <span className="text-xs">查看档案 {'>'}</span>
            </div>
            <button onClick={onNext} className="w-full mt-8 py-4 bg-teal-500 hover:bg-teal-600 text-white rounded-2xl font-bold shadow-lg shadow-teal-100 transition-all active:scale-95">下一步：描述症状</button>
        </div>
    );
};

export default PatientSelector;
