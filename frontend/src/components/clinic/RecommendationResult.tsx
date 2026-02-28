import type { FC } from 'react';
import { Stethoscope } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';

const RecommendationResult: FC = () => {
    const { setChatMode } = useGlobalStore();

    return (
        <div className="animate-in fade-in slide-in-from-bottom-4 space-y-4">
            <div className="p-5 bg-gradient-to-br from-teal-50 to-emerald-50 rounded-3xl border border-teal-100 shadow-sm relative overflow-hidden">
                <div className="absolute right-0 bottom-0 opacity-5 text-teal-600"><Stethoscope size={100} /></div>
                <h3 className="font-bold text-teal-800 flex items-center gap-2 mb-3"><Stethoscope size={18} /> AI 预问诊分析完成</h3>
                <p className="text-sm text-teal-700 leading-relaxed mb-4 relative z-10">根据您的描述，您的失眠症状可能与近期的生活压力或神经衰弱有关。若伴有心慌、多梦等情况，建议您寻求专业医生评估。</p>
                <div className="bg-white/60 p-3 rounded-xl border border-white relative z-10">
                    <span className="text-xs text-teal-600 font-bold block mb-1">推荐科室：</span>
                    <span className="bg-teal-100 text-teal-700 text-xs px-2 py-1 rounded-md font-bold">中医内科</span>
                    <span className="bg-teal-100 text-teal-700 text-xs px-2 py-1 rounded-md font-bold ml-2">神经内科</span>
                </div>
            </div>
            <button onClick={() => setChatMode('general')} className="w-full py-4 bg-white hover:bg-slate-50 border-2 border-teal-500 text-teal-600 rounded-2xl font-bold shadow-sm transition-all active:scale-95">前往预约挂号</button>
        </div>
    );
};

export default RecommendationResult;
