import { ArrowLeft } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import VisualEngineGrid from '../../components/pharmacy/VisualEngineGrid';
import ReminderSection from '../../components/pharmacy/ReminderSection';
import ReminderCard from '../../components/pharmacy/ReminderCard';

const PharmacyScreen = () => {
    const { setChatMode, setScanType, setIsScanning } = useGlobalStore();

    return (
        <div className="p-6 bg-slate-50 h-full animate-in slide-in-from-right overflow-y-auto pb-32">
            <header className="flex items-center gap-4 mb-8">
                <ArrowLeft className="cursor-pointer hover:text-emerald-500 transition-colors text-slate-800" onClick={() => setChatMode('general')} />
                <h2 className="text-xl font-bold text-slate-800">药管家</h2>
            </header>

            {/* 视觉双核引擎 */}
            <VisualEngineGrid
                onScanMedBox={() => { setScanType('药盒'); setIsScanning(true); }}
                onScanTraceCode={() => { setScanType('追溯码'); setIsScanning(true); }}
            />

            <ReminderSection>
                <ReminderCard name="阿莫西林克拉维酸钾" type="胶囊" timeLabel="今天 13:00 (饭后半小时)" />
            </ReminderSection>
        </div>
    );
};

export default PharmacyScreen;
