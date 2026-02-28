import { ArrowLeft } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import UploadHero from '../../components/report/UploadHero';
import ReportList from '../../components/report/ReportList';

const ReportScreen = () => {
    const { setChatMode, setScanType, setIsScanning } = useGlobalStore();

    return (
        <div className="p-6 bg-slate-50 h-full animate-in slide-in-from-right overflow-y-auto pb-32">
            <header className="flex items-center gap-4 mb-6">
                <ArrowLeft className="cursor-pointer hover:text-teal-600 transition-colors text-slate-800" onClick={() => setChatMode('general')} />
                <h2 className="text-xl font-bold text-slate-800">检查报告夹</h2>
            </header>

            <UploadHero onUploadClick={() => { setScanType('报告'); setIsScanning(true); }} />
            <ReportList />
        </div>
    );
};

export default ReportScreen;
