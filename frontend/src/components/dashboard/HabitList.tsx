import type { FC } from 'react';
import { MOCK_HABITS } from '../../data/mockData';
import { useTextScale } from '../../design/textScale';
import HabitRow from './HabitRow';

const HabitList: FC = () => {
    const t = useTextScale();
    const done = MOCK_HABITS.filter(habit => habit.progress >= 100).length;

    return (
        <section>
            <div className="mb-3 flex items-baseline justify-between px-1">
                <h3 className={`font-semibold text-ink-900 ${t.title}`}>每日打卡</h3>
                <span className={`text-ink-600 ${t.caption}`}>已完成 {done}/{MOCK_HABITS.length}</span>
            </div>
            <div className="space-y-2.5">
                {MOCK_HABITS.map(habit => <HabitRow key={habit.title} habit={habit} />)}
            </div>
        </section>
    );
};

export default HabitList;
