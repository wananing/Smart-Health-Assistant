import type { FC } from 'react';
import { MapPin } from 'lucide-react';
import type { HospitalListing } from '../../types';

interface HospitalCardProps {
    hospital: HospitalListing | any;
}

const HospitalCard: FC<HospitalCardProps> = ({ hospital }) => {
    return (
        <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-100 flex items-center justify-between cursor-pointer hover:border-blue-200 transition-colors group">
            <div>
                <div className="font-bold text-slate-800 mb-2 flex items-center gap-2">
                    {hospital.name}
                    {hospital.isAd && <span className="text-[9px] bg-slate-100 text-slate-400 px-1 py-0.5 rounded">广告</span>}
                </div>
                <div className="flex gap-2">
                    {hospital.tags.map((tag: string) => (
                        <span key={tag} className={`text-[10px] font-bold px-2 py-0.5 rounded-md ${hospital.isAd ? 'bg-orange-50 text-orange-600' : 'bg-blue-50 text-blue-600'}`}>
                            {tag}
                        </span>
                    ))}
                </div>
            </div>
            <div className="flex flex-col items-end gap-3">
                <span className="text-xs text-slate-400 font-medium flex items-center gap-1"><MapPin size={12} />{hospital.distance}</span>
                <button className="text-xs bg-white border border-blue-500 text-blue-500 px-4 py-1.5 rounded-full font-bold group-hover:bg-blue-500 group-hover:text-white transition-colors shadow-sm">
                    去预约
                </button>
            </div>
        </div>
    );
};

export default HospitalCard;
