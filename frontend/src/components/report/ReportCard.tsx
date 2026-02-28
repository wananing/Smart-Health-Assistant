import type { FC } from 'react';
import { FileText } from 'lucide-react';
import type { MedicalReport } from '../../types';

interface ReportCardProps {
    report: MedicalReport;
}

const ReportCard: FC<ReportCardProps> = ({ report }) => {
    return (
        <div className="bg-white p-5 rounded-3xl shadow-sm border border-slate-100 cursor-pointer hover:border-teal-200 transition-colors flex gap-4 items-center">
            <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 shadow-sm ${report.isAbnormal ? 'bg-rose-50 text-rose-500' : 'bg-teal-50 text-teal-500'}`}>
                <FileText size={24} />
            </div>
            <div className="flex-1">
                <div className="flex justify-between items-start mb-2">
                    <span className="font-bold text-slate-800 text-sm leading-tight">{report.title}</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-md font-bold ${report.isAbnormal ? 'bg-rose-100 text-rose-600' : 'bg-teal-100 text-teal-600'}`}>
                        {report.analysisStatus}
                    </span>
                </div>
                <div className="text-xs font-bold text-slate-500 mb-1">{report.hospitalName}</div>
                <div className="text-[10px] text-slate-400">{report.date}</div>
            </div>
        </div>
    );
};

export default ReportCard;
