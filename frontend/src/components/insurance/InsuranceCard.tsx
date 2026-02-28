import type { FC } from 'react';
import { ShieldCheck, Eye, EyeOff, ScanLine } from 'lucide-react';

interface InsuranceCardProps {
    showBalance: boolean;
    onToggleBalance: () => void;
    onScanPay: () => void;
}

const InsuranceCard: FC<InsuranceCardProps> = ({ showBalance, onToggleBalance, onScanPay }) => {
    return (
        <div className="bg-gradient-to-br from-blue-500 to-cyan-500 rounded-3xl p-6 mb-6 shadow-lg shadow-blue-100 relative overflow-hidden text-white">
            <div className="absolute -top-4 -right-4 p-4 opacity-10"><ShieldCheck size={120} /></div>
            <div className="mb-10 relative z-10">
                <div className="text-blue-100 text-xs mb-1 tracking-widest font-bold flex items-center gap-1"><ShieldCheck size={14} /> 国家医保电子凭证</div>
                <div className="text-2xl font-bold tracking-wider">北京市 城镇职工医保</div>
            </div>
            <div className="flex justify-between items-end relative z-10">
                <div>
                    <div className="text-blue-100 text-xs mb-1 font-medium flex items-center gap-2">
                        个人账户余额 (元)
                        <button
                            onClick={onToggleBalance}
                            className="text-blue-100 hover:text-white p-1 rounded-full hover:bg-white/10 transition-colors"
                            aria-label="Toggle map balance visibility"
                        >
                            {showBalance ? <Eye size={16} /> : <EyeOff size={16} />}
                        </button>
                    </div>
                    <div className="text-4xl font-black tabular-nums transition-all">{showBalance ? '2,458.32' : '****'}</div>
                </div>
                <div className="bg-white p-2.5 rounded-2xl cursor-pointer hover:scale-105 transition-transform shadow-md" onClick={onScanPay}>
                    <div className="w-14 h-14 bg-blue-50 rounded-xl flex items-center justify-center text-blue-600"><ScanLine size={32} /></div>
                    <div className="text-slate-800 text-[11px] text-center mt-2 font-black tracking-wide">去支付</div>
                </div>
            </div>
        </div>
    );
};

export default InsuranceCard;
