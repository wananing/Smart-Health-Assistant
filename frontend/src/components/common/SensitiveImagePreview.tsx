import { useState, type FC } from 'react';
import { Eye, ShieldCheck } from 'lucide-react';

interface SensitiveImagePreviewProps {
    imageUrl: string;
    label: string;
    hint?: string;
}

const SensitiveImagePreview: FC<SensitiveImagePreviewProps> = ({ imageUrl, label, hint }) => {
    const [isRevealed, setIsRevealed] = useState(false);

    return (
        <div className="bg-white border border-slate-100 rounded-2xl overflow-hidden shadow-sm">
            <div className="px-4 py-3 flex items-center justify-between border-b border-slate-100">
                <div className="flex items-center gap-2 text-slate-800">
                    <ShieldCheck size={16} className="text-teal-600" />
                    <span className="font-bold text-sm">{label}</span>
                </div>
                <span className="text-[10px] font-bold text-teal-700 bg-teal-50 px-2 py-1 rounded-md">隐私保护</span>
            </div>

            <button
                type="button"
                aria-label="按住查看报告原图"
                onPointerDown={() => setIsRevealed(true)}
                onPointerUp={() => setIsRevealed(false)}
                onPointerLeave={() => setIsRevealed(false)}
                onPointerCancel={() => setIsRevealed(false)}
                className="relative w-full aspect-[4/3] bg-slate-900 overflow-hidden touch-none"
            >
                <img
                    src={imageUrl}
                    alt=""
                    className={`w-full h-full object-cover transition-all duration-200 ${isRevealed ? 'blur-0 scale-100' : 'blur-xl scale-105 opacity-80'}`}
                    draggable={false}
                />
                {!isRevealed && (
                    <div className="absolute inset-0 bg-slate-950/45 flex flex-col items-center justify-center text-white px-6 text-center">
                        <Eye size={24} className="mb-2" />
                        <div className="font-black text-sm">报告可能包含个人信息</div>
                        <div className="text-xs text-slate-200 mt-1">{hint ?? '按住查看原图，松开恢复模糊'}</div>
                    </div>
                )}
            </button>
        </div>
    );
};

export default SensitiveImagePreview;
