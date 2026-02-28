import { ArrowLeft } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import VitalsHero from '../../components/dashboard/VitalsHero';
import HabitList from '../../components/dashboard/HabitList';

const DashboardScreen = () => {
    const { setChatMode } = useGlobalStore();

    return (
        <div className="p-6 bg-slate-50 h-full animate-in slide-in-from-right overflow-y-auto pb-32">
            <header className="flex items-center gap-4 mb-6">
                <ArrowLeft className="cursor-pointer hover:text-teal-600 transition-colors text-slate-800" onClick={() => setChatMode('general')} />
                <h2 className="text-xl font-bold text-slate-800">健康小目标</h2>
            </header>

            <VitalsHero />
            <HabitList />
        </div>
    );
};

export default DashboardScreen;
