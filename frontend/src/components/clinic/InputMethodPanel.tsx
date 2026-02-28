import type { FC } from 'react';
import { Camera, Mic, Square } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';

interface InputMethodPanelProps {
    isRecording: boolean;
    onToggleRecording: () => void;
}

const InputMethodPanel: FC<InputMethodPanelProps> = ({ isRecording, onToggleRecording }) => {
    const { setChatMode } = useGlobalStore();

    return (
        <div className="animate-in fade-in slide-in-from-bottom-4 space-y-4">
            <p className="font-bold text-slate-800">请描述您的症状或上传报告：</p>
            <div className="grid grid-cols-2 gap-4">
                <button onClick={() => setChatMode('report')} className="h-36 rounded-3xl border-2 border-dashed border-slate-200 flex flex-col items-center justify-center gap-3 text-slate-500 hover:border-teal-400 hover:text-teal-500 hover:bg-teal-50 transition-all bg-white">
                    <Camera size={32} />
                    <span className="text-sm font-bold">拍化验单/报告</span>
                </button>
                <button
                    onClick={onToggleRecording}
                    className={`h-36 rounded-3xl border-2 border-dashed flex flex-col items-center justify-center gap-3 transition-all ${isRecording ? 'border-teal-500 text-teal-500 bg-teal-50 ring-4 ring-teal-100' : 'border-slate-200 text-slate-500 hover:border-teal-400 hover:text-teal-500 hover:bg-teal-50 bg-white'}`}
                >
                    {isRecording ? <Square size={32} className="animate-pulse" /> : <Mic size={32} />}
                    <span className="text-sm font-bold">{isRecording ? '正在聆听...点击结束' : '语音描述'}</span>
                </button>
            </div>
            <div className="text-center text-xs text-slate-400 pt-2">您可以说：“我最近两周总是失眠，白天没精神”</div>
        </div>
    );
};

export default InputMethodPanel;
