import React from 'react';
import { useGlobalStore } from '../../store/GlobalContext';

interface SuggestionScrollerProps {
    onSend: (text: string) => void;
}

const MODE_SUGGESTIONS: Record<string, string[]> = {
    general: [
        '想开点中药调理身体挂什么科？',
        '我最近总是失眠怎么办？',
        '帮我查一下医保余额',
        '扫码查一下这个感冒药真伪',
    ],
    insurance: [
        '查一下我的医保余额',
        '查近期消费明细',
        '看一下我的缴费记录',
        '查异地就医备案情况',
        '医保报销比例是多少？',
    ],
    clinic: [
        '我最近头很痛',
        '发烧了有什么建议',
        '喉咙痛，要去哪个科',
        '肚子疼挂什么号',
    ],
    report: [
        '帮我分析这个血常规',
        '什么是CRP指标',
        '尿酸偏高怎么回事',
    ],
    pharmacy: [
        '这个药能和阿司匹林一起吃吗',
        '布洛芬的用量是多少',
        '这个感冒药成分查询',
    ],
};

const SuggestionScroller: React.FC<SuggestionScrollerProps> = ({ onSend }) => {
    const { chatMode } = useGlobalStore();
    const suggestions = MODE_SUGGESTIONS[chatMode] ?? MODE_SUGGESTIONS.general;

    return (
        <div className="flex gap-2 overflow-x-auto pb-4 scrollbar-hide px-1">
            {suggestions.map((text, i) => (
                <button
                    key={i}
                    onClick={() => onSend(text)}
                    className="whitespace-nowrap px-4 py-2 bg-slate-50 hover:bg-teal-50 text-slate-600 hover:text-teal-700 rounded-2xl text-xs font-bold border border-slate-100 transition-colors shadow-sm"
                >
                    {text}
                </button>
            ))}
        </div>
    );
};

export default SuggestionScroller;
