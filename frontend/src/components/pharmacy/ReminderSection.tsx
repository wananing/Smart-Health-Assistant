import type { FC, ReactNode } from 'react';
import { Bell } from 'lucide-react';

interface ReminderSectionProps {
    children: ReactNode;
}

const ReminderSection: FC<ReminderSectionProps> = ({ children }) => {
    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center mb-2 px-1">
                <h3 className="font-bold text-slate-800 flex items-center gap-2 text-lg">
                    <Bell size={20} className="text-orange-500" /> 近期用药提醒
                </h3>
                <span className="text-sm font-bold text-emerald-600 cursor-pointer hover:underline">家庭药箱 &gt;</span>
            </div>
            {children}
        </div>
    );
};

export default ReminderSection;
