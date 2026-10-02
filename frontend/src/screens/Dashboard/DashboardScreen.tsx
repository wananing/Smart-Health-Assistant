import { ChevronLeft } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import { useTextScale } from '../../design/textScale';
import VitalsHero from '../../components/dashboard/VitalsHero';
import HabitList from '../../components/dashboard/HabitList';

const DashboardScreen = () => {
    const { setChatMode } = useGlobalStore();
    const t = useTextScale();

    return (
        <div className="h-full overflow-y-auto font-cn bg-gradient-to-b from-brand-50 via-white to-ink-50 pb-40">
            <header className="sticky top-0 z-10 flex items-center gap-2 px-3 pt-[max(env(safe-area-inset-top),0.75rem)] pb-2 bg-white/80 backdrop-blur-md">
                <button
                    onClick={() => setChatMode('general')}
                    aria-label="返回"
                    className="w-10 h-10 rounded-full flex items-center justify-center text-ink-700 hover:bg-ink-100 active:scale-[0.94] transition duration-fast"
                >
                    <ChevronLeft size={24} />
                </button>
                <h2 className={`font-semibold text-ink-900 ${t.title}`}>健康小目标</h2>
            </header>

            <div className="px-4 pt-2 space-y-6">
                <VitalsHero />
                <HabitList />
            </div>
        </div>
    );
};

export default DashboardScreen;
