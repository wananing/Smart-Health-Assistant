import type { FC, ReactNode } from 'react';

type Theme = 'rose' | 'indigo';

interface VitalCardProps {
    title: string;
    theme: Theme;
    icon: ReactNode;
    valueNode: ReactNode;
    statusText: string;
}

const THEMES = {
    rose: {
        container: 'bg-rose-50 border-rose-100',
        title: 'text-rose-600',
        status: 'text-rose-500 border-rose-100',
    },
    indigo: {
        container: 'bg-indigo-50 border-indigo-100',
        title: 'text-indigo-600',
        status: 'text-indigo-500 border-indigo-100',
    },
};

const VitalCard: FC<VitalCardProps> = ({ title, theme, icon, valueNode, statusText }) => {
    const styles = THEMES[theme];

    return (
        <div className={`p-4 rounded-2xl border ${styles.container}`}>
            <div className="flex justify-between items-start mb-2">
                <div className={`text-xs font-bold ${styles.title}`}>{title}</div>
                {icon}
            </div>
            <div className="text-3xl font-black text-slate-800 tabular-nums">{valueNode}</div>
            <div className={`text-[10px] mt-2 bg-white inline-block px-2 py-0.5 rounded-sm border ${styles.status}`}>
                {statusText}
            </div>
        </div>
    );
};

export default VitalCard;
