import type { FC } from 'react';
import { Calendar, MapPin, Activity } from 'lucide-react';

const BookingActionGrid: FC = () => {
    return (
        <div className="grid grid-cols-3 gap-3 mb-8">
            {[
                { icon: Calendar, label: '预约挂号', color: 'text-blue-500', bg: 'bg-blue-50' },
                { icon: MapPin, label: '附近医院', color: 'text-emerald-500', bg: 'bg-emerald-50' },
                { icon: Activity, label: '体检预约', color: 'text-orange-500', bg: 'bg-orange-50' }
            ].map((action, i) => (
                <div key={i} className="bg-white flex flex-col items-center justify-center p-4 rounded-3xl shadow-sm border border-slate-100 cursor-pointer hover:shadow-md hover:-translate-y-1 transition-all">
                    <div className={`w-12 h-12 rounded-2xl ${action.bg} flex items-center justify-center mb-3`}>
                        <action.icon size={24} className={action.color} />
                    </div>
                    <span className="text-xs font-bold text-slate-700">{action.label}</span>
                </div>
            ))}
        </div>
    );
};

export default BookingActionGrid;
