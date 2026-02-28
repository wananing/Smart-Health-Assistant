import type { FC } from 'react';
import { CheckCircle2 } from 'lucide-react';
import type { HabitGoal } from '../../types';

interface HabitRowProps {
    task: HabitGoal | any;
}

const HabitRow: FC<HabitRowProps> = ({ task }) => {
    return (
        <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-100 flex items-center gap-4 cursor-pointer hover:border-teal-200 transition-colors">
            <div className="w-10 h-10 rounded-full bg-slate-50 flex items-center justify-center border border-slate-100 shrink-0">
                <CheckCircle2 size={24} className={task.progress > 0 ? "text-teal-500" : "text-slate-300"} />
            </div>
            <div className="flex-1">
                <div className="flex justify-between mb-2">
                    <span className="font-bold text-slate-800">{task.title}</span>
                    <span className="text-xs text-slate-500 font-medium bg-slate-50 px-2 py-1 rounded-md">{task.current}</span>
                </div>
                <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
                    <div className={`h-full ${task.color} rounded-full transition-all duration-1000`} style={{ width: `${task.progress}%` }}></div>
                </div>
            </div>
        </div>
    );
};

export default HabitRow;
