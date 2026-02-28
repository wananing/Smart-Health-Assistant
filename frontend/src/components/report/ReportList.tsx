import type { FC } from 'react';
import { MOCK_REPORTS } from '../../data/mockData';
import ReportCard from './ReportCard';

const ReportList: FC = () => {
    return (
        <>
            <div className="flex justify-between items-center mb-4 px-2">
                <h3 className="font-bold text-slate-800 text-lg">历史报告记录</h3>
                <span className="text-xs text-slate-500 font-normal cursor-pointer bg-slate-200 px-2 py-1 rounded-md">按时间排序 ▼</span>
            </div>
            <div className="space-y-4">
                {MOCK_REPORTS.map((report, i) => (
                    <ReportCard key={i} report={report as any} />
                ))}
            </div>
        </>
    );
};

export default ReportList;
