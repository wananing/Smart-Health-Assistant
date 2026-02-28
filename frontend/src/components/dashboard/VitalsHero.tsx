import type { FC } from 'react';
import { Activity, Heart, Smartphone } from 'lucide-react';
import VitalCard from './VitalCard';

const VitalsHero: FC = () => {
    return (
        <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-100 mb-6 relative overflow-hidden">
            <h3 className="font-bold text-slate-800 mb-5 flex items-center gap-2 relative z-10">
                <Activity className="text-teal-500" /> 今日数据看板
            </h3>
            <div className="grid grid-cols-2 gap-4 relative z-10">
                <VitalCard
                    title="心率"
                    theme="rose"
                    icon={<Heart size={16} className="text-rose-400" />}
                    valueNode={<>72 <span className="text-xs font-normal text-slate-500">bpm</span></>}
                    statusText="正常水平"
                />
                <VitalCard
                    title="昨晚睡眠"
                    theme="indigo"
                    icon={<Smartphone size={16} className="text-indigo-400" />}
                    valueNode={<>7<span className="text-xs font-normal text-slate-500">h</span> 30<span className="text-xs font-normal text-slate-500">m</span></>}
                    statusText="深睡 2.5h"
                />
            </div>
        </div>
    );
};

export default VitalsHero;
