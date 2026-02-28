import type { FC } from 'react';
import { MOCK_HOSPITALS } from '../../data/mockData';
import HospitalCard from './HospitalCard';

const HospitalList: FC = () => {
    return (
        <>
            <div className="flex justify-between items-center mb-4 px-2">
                <h3 className="font-bold text-slate-800 text-lg">推荐医疗机构 (北京)</h3>
                <span className="text-xs text-blue-500 font-bold cursor-pointer hover:text-blue-600">切换城市</span>
            </div>
            <div className="space-y-4">
                {MOCK_HOSPITALS.map((hospital, i) => (
                    <HospitalCard key={i} hospital={hospital as any} />
                ))}
            </div>
        </>
    );
};

export default HospitalList;
