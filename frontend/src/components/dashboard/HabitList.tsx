import type { FC } from 'react';
import { MOCK_HABITS } from '../../data/mockData';
import HabitRow from './HabitRow';

const HabitList: FC = () => {
    return (
        <div>
            <h3 className="font-bold text-slate-800 mb-4 px-2 text-lg">每日打卡计划</h3>
            <div className="space-y-3">
                {MOCK_HABITS.map((task, i) => (
                    <HabitRow key={i} task={task as any} />
                ))}
            </div>
        </div>
    );
};

export default HabitList;
