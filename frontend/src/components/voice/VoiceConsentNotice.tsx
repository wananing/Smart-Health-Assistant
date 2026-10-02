import type { FC } from 'react';
import { ShieldCheck } from 'lucide-react';
import VoiceOrb from './VoiceOrb';

const NO_LEVEL = () => 0;

interface VoiceConsentNoticeProps {
    /** Runs inside the tap, so it can unlock audio and request the microphone */
    onAccept: () => void;
    onDecline: () => void;
    isElderMode: boolean;
}

const POINTS = [
    <>通话中您的声音会实时发送给<b className="font-semibold text-ink-900">第三方语音服务商</b>，用于转成文字和生成语音播报。</>,
    <><b className="font-semibold text-ink-900">不保存录音。</b>转写的文字会作为问诊记录保留在对话里，方便您继续用文字咨询。</>,
    <>AI 建议不构成医疗诊断。突发严重不适请直接拨打 120。</>,
];

/** First-use notice: audio goes to a third-party speech provider and is not stored. */
const VoiceConsentNotice: FC<VoiceConsentNoticeProps> = ({ onAccept, onDecline, isElderMode }) => (
    <div className="flex-1 flex flex-col justify-end px-4 pt-[max(env(safe-area-inset-top),1rem)] pb-[max(env(safe-area-inset-bottom),1.25rem)]">
        <div className="flex-1 flex items-center justify-center">
            <VoiceOrb state="listening" muted={false} getLevel={NO_LEVEL} size={88} />
        </div>
        <div className="bg-white rounded-card p-5 space-y-4 shadow-floating">
            <h2 className={`font-semibold text-ink-900 ${isElderMode ? 'text-headline' : 'text-title'}`}>开始语音问诊前</h2>
            <ul className={`space-y-3 text-ink-700 ${isElderMode ? 'text-title' : 'text-body'}`}>
                {POINTS.map((point, idx) => (
                    <li key={idx} className="flex gap-2.5">
                        <ShieldCheck size={18} className="text-brand-700 shrink-0 mt-0.5" />
                        <span>{point}</span>
                    </li>
                ))}
            </ul>
            <p className={`text-ink-500 ${isElderMode ? 'text-body' : 'text-caption'}`}>点击"同意并开始"后，浏览器会请求使用麦克风。</p>
            <div className="grid grid-cols-[1fr_2fr] gap-3">
                <button
                    type="button"
                    onClick={onDecline}
                    className={`rounded-control bg-ink-100 font-semibold text-ink-700 hover:bg-ink-200 transition ${isElderMode ? 'h-14 text-title' : 'h-12 text-callout'}`}
                >
                    暂不使用
                </button>
                <button
                    type="button"
                    onClick={onAccept}
                    className={`rounded-control bg-brand-700 font-semibold text-white shadow-raised hover:bg-brand-800 active:scale-[0.99] transition ${isElderMode ? 'h-14 text-title' : 'h-12 text-callout'}`}
                >
                    同意并开始
                </button>
            </div>
        </div>
    </div>
);

export default VoiceConsentNotice;
