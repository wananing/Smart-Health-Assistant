import { useState } from 'react';
import type { FC } from 'react';
import { Calendar } from 'lucide-react';

interface ReminderCardProps {
    name: string;
    type: string;
    timeLabel: string;
}

const ReminderCard: FC<ReminderCardProps> = ({ name, type, timeLabel }) => {
    const [medTaken, setMedTaken] = useState(false);

    return (
        <div className={`p-4 rounded-3xl flex items-center gap-4 border transition-all duration-500 ${medTaken ? 'bg-slate-100 border-slate-200 opacity-60 scale-[0.98]' : 'bg-white border-emerald-100 shadow-sm'}`}>
            <div className={`w-12 h-12 rounded-2xl flex items-center justify-center font-bold ${medTaken ? 'bg-slate-200 text-slate-400' : 'bg-emerald-50 text-emerald-600'}`}>
                {type}
            </div>
            <div className="flex-1">
                <div className={`font-bold ${medTaken ? 'text-slate-500 line-through decoration-2' : 'text-slate-800'}`}>
                    {name}
                </div>
                <div className="text-xs text-slate-500 mt-1 flex items-center gap-1">
                    <Calendar size={12} /> {medTaken ? '今日已完成' : timeLabel}
                </div>
            </div>
            <button
                onClick={() => setMedTaken(!medTaken)}
                className={`px-5 py-2.5 rounded-full text-sm font-bold border transition-all active:scale-90 ${medTaken ? 'bg-transparent text-slate-400 border-slate-300' : 'bg-emerald-500 text-white border-emerald-500 shadow-sm hover:bg-emerald-600'}`}
            >
                {medTaken ? '已打卡' : '去服用'}
            </button>
        </div>
    );
};

export default ReminderCard;
