import React from 'react';
import { Mic, Plus, Send } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';

interface InputBarProps {
    inputValue: string;
    setInputValue: (val: string) => void;
    onSend: () => void;
}

const InputBar: React.FC<InputBarProps> = ({ inputValue, setInputValue, onSend }) => {
    const { isElderMode } = useGlobalStore();

    return (
        <div className="flex items-center gap-3">
            <button className="w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center text-slate-500 hover:bg-teal-100 hover:text-teal-600 transition-all shadow-inner">
                <Mic size={20} />
            </button>
            <div className="flex-1 relative">
                <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && onSend()}
                    placeholder={isElderMode ? "按住说话或发消息..." : "描述症状、问医保、查报告..."}
                    className={`w-full bg-slate-100 rounded-full py-3.5 pl-5 pr-12 focus:outline-none focus:ring-2 focus:ring-teal-500 transition-all font-medium placeholder-slate-400 text-slate-800 ${isElderMode ? 'text-xl h-14' : 'text-sm'}`}
                />
                <button
                    onClick={onSend}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 w-9 h-9 bg-teal-500 hover:bg-teal-600 rounded-full flex items-center justify-center text-white shadow-md shadow-teal-200 transition-colors"
                >
                    <Send size={16} />
                </button>
            </div>
            <button className="w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center text-slate-500 hover:bg-slate-200 transition-colors">
                <Plus size={24} />
            </button>
        </div>
    );
};

export default InputBar;
