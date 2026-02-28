import { useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import InsuranceCard from '../../components/insurance/InsuranceCard';
import ServiceGrid from '../../components/insurance/ServiceGrid';

const InsuranceScreen = () => {
    const { setChatMode, setScanType, setIsScanning } = useGlobalStore();
    const [showBalance, setShowBalance] = useState(false);

    return (
        <div className="p-6 bg-slate-50 h-full animate-in slide-in-from-right overflow-y-auto pb-32">
            <header className="flex items-center gap-4 mb-8">
                <ArrowLeft className="cursor-pointer hover:text-blue-500 transition-colors text-slate-800" onClick={() => setChatMode('general')} />
                <h2 className="text-xl font-bold text-slate-800">医疗保障管家</h2>
            </header>

            <InsuranceCard
                showBalance={showBalance}
                onToggleBalance={() => setShowBalance(!showBalance)}
                onScanPay={() => { setScanType('支付码'); setIsScanning(true); }}
            />

            <ServiceGrid />
        </div>
    );
};

export default InsuranceScreen;
