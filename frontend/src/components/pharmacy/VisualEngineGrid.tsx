import type { FC } from 'react';
import { Camera, ScanLine } from 'lucide-react';

interface VisualEngineGridProps {
    onScanMedBox: () => void;
    onScanTraceCode: () => void;
}

const VisualEngineGrid: FC<VisualEngineGridProps> = ({ onScanMedBox, onScanTraceCode }) => {
    return (
        <div className="grid grid-cols-2 gap-4 mb-10">
            <div className="aspect-square bg-white rounded-3xl flex flex-col items-center justify-center p-4 border border-slate-100 hover:border-emerald-500 transition-all cursor-pointer group shadow-sm" onClick={onScanMedBox}>
                <div className="w-16 h-16 bg-emerald-50 rounded-2xl flex items-center justify-center text-emerald-500 mb-4 group-hover:bg-emerald-500 group-hover:text-white transition-colors">
                    <Camera size={28} />
                </div>
                <span className="font-bold text-slate-800 text-lg mb-1">拍药盒</span>
                <span className="text-xs text-slate-500 font-medium">用药科普 · 自动比价</span>
            </div>
            <div className="aspect-square bg-white rounded-3xl flex flex-col items-center justify-center p-4 border border-slate-100 hover:border-blue-500 transition-all cursor-pointer group shadow-sm" onClick={onScanTraceCode}>
                <div className="w-16 h-16 bg-blue-50 rounded-2xl flex items-center justify-center text-blue-500 mb-4 group-hover:bg-blue-500 group-hover:text-white transition-colors">
                    <ScanLine size={28} />
                </div>
                <span className="font-bold text-slate-800 text-lg mb-1">扫追溯码</span>
                <span className="text-xs text-slate-500 font-medium">防伪验真 · 过期预警</span>
            </div>
        </div>
    );
};

export default VisualEngineGrid;
