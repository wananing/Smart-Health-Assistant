import { useState, type FC } from 'react';
import { Eye, ShieldCheck } from 'lucide-react';
import { Badge, ResultCard } from './ResultCard';
import { useTextScale } from '../../design/textScale';

interface SensitiveImagePreviewProps {
    imageUrl: string;
    label: string;
    hint?: string;
}

const SensitiveImagePreview: FC<SensitiveImagePreviewProps> = ({ imageUrl, label, hint }) => {
    const t = useTextScale();
    const [isRevealed, setIsRevealed] = useState(false);

    return (
        <ResultCard icon={ShieldCheck} title={label} meta={<Badge tone="brand">隐私保护</Badge>}>
            <button
                type="button"
                aria-label="按住查看报告原图"
                onPointerDown={() => setIsRevealed(true)}
                onPointerUp={() => setIsRevealed(false)}
                onPointerLeave={() => setIsRevealed(false)}
                onPointerCancel={() => setIsRevealed(false)}
                className="relative block w-full aspect-[4/3] overflow-hidden rounded-control bg-ink-900 touch-none"
            >
                <img
                    src={imageUrl}
                    alt=""
                    className={`w-full h-full object-cover transition duration-base ${isRevealed ? 'blur-0 scale-100' : 'blur-xl scale-105 opacity-80'}`}
                    draggable={false}
                />
                {!isRevealed && (
                    <div className="absolute inset-0 bg-ink-900/50 flex flex-col items-center justify-center gap-1 px-6 text-center text-white">
                        <Eye size={24} />
                        <div className={`font-semibold ${t.body}`}>报告可能包含个人信息</div>
                        <div className={`text-ink-100 ${t.caption}`}>{hint ?? '按住查看原图，松开恢复模糊'}</div>
                    </div>
                )}
            </button>
        </ResultCard>
    );
};

export default SensitiveImagePreview;
