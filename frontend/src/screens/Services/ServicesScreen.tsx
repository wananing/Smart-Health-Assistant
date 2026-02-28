import { ArrowLeft } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import SearchHeader from '../../components/services/SearchHeader';
import BookingActionGrid from '../../components/services/BookingActionGrid';
import HospitalList from '../../components/services/HospitalList';

const ServicesScreen = () => {
    const { setChatMode } = useGlobalStore();

    return (
        <div className="p-6 bg-slate-50 h-full animate-in slide-in-from-right overflow-y-auto pb-32">
            <header className="flex items-center gap-4 mb-6">
                <ArrowLeft className="cursor-pointer hover:text-blue-600 transition-colors text-slate-800" onClick={() => setChatMode('general')} />
                <h2 className="text-xl font-bold text-slate-800">就医服务</h2>
            </header>

            <SearchHeader />
            <BookingActionGrid />
            <HospitalList />
        </div>
    );
};

export default ServicesScreen;
