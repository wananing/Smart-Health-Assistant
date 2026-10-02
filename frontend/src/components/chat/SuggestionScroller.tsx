import React from 'react';
import { useGlobalStore } from '../../store/GlobalContext';

interface SuggestionScrollerProps {
    onSend: (text: string) => void;
}

// Starter questions for an empty conversation. Each mode's own starters live in
// its welcome card (ModeContextCards), so they are not repeated here.
const STARTER_QUESTIONS = [
    '想开点中药调理身体挂什么科？',
    '我最近总是失眠怎么办？',
    '帮我查一下医保余额',
    '降压药能停吗？',
    '扫码查一下这个感冒药真伪',
];

const SuggestionScroller: React.FC<SuggestionScrollerProps> = ({ onSend }) => {
    const { isElderMode } = useGlobalStore();

    return (
        <div className="flex gap-2 overflow-x-auto scrollbar-hide px-4 py-1">
            {STARTER_QUESTIONS.map((text) => (
                <button
                    key={text}
                    onClick={() => onSend(text)}
                    className={`shrink-0 whitespace-nowrap rounded-full bg-white px-3.5 text-ink-700 ring-1 ring-inset ring-ink-200 hover:bg-brand-50 hover:text-brand-800 hover:ring-brand-200 active:scale-[0.98] transition duration-fast ${isElderMode ? 'h-11 text-callout' : 'h-9 text-body'}`}
                >
                    {text}
                </button>
            ))}
        </div>
    );
};

export default SuggestionScroller;
