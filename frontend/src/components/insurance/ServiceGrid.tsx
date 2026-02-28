import type { FC } from 'react';
import { MOCK_INSURANCE_SERVICES } from '../../data/mockData';

const ServiceGrid: FC = () => {
    return (
        <div className="grid grid-cols-2 gap-4">
            {MOCK_INSURANCE_SERVICES.map((item, i) => (
                <div key={i} className="bg-white p-5 rounded-3xl border border-slate-100 cursor-pointer hover:border-blue-200 transition-colors shadow-sm">
                    <div className={`w-10 h-10 rounded-full ${item.bg} flex items-center justify-center mb-3`}>
                        <item.icon size={20} className={item.color} />
                    </div>
                    <div className="font-bold mb-1 tracking-wide text-slate-800">{item.label}</div>
                    <div className="text-xs text-slate-500 line-clamp-1">{item.sub}</div>
                </div>
            ))}
        </div>
    );
};

export default ServiceGrid;
