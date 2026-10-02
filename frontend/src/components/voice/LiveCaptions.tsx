import type { FC } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { VoiceCaption } from '../../types';
import ChatCardRenderer from '../chat/ChatCardRenderer';

interface LiveCaptionsProps {
    captions: VoiceCaption[];
    isElderMode: boolean;
}

/** The call's full record as a log: who spoke, what was said, and any cards. */
const LiveCaptions: FC<LiveCaptionsProps> = ({ captions, isElderMode }) => {
    if (captions.length === 0) {
        return (
            <p className={`text-center text-ink-500 py-8 ${isElderMode ? 'text-title' : 'text-body'}`}>
                通话内容会记录在这里
            </p>
        );
    }

    return (
        <ol className="space-y-4">
            {captions.map(caption => (
                <li key={caption.id} className="space-y-2">
                    {caption.text && (
                        <div
                            data-caption-role={caption.role}
                            data-caption-final={caption.isFinal ? 'true' : 'false'}
                            className={`relative pl-3.5 before:absolute before:left-0 before:top-1 before:bottom-1 before:w-[3px] before:rounded-full ${caption.role === 'user' ? 'before:bg-brand-400' : 'before:bg-ink-200'}`}
                        >
                            <div className={`font-semibold mb-0.5 ${isElderMode ? 'text-body' : 'text-caption'} ${caption.role === 'user' ? 'text-brand-800' : 'text-ink-500'}`}>
                                {caption.role === 'user' ? '您' : '助手'}
                            </div>
                            <div className={`${isElderMode ? 'text-title' : 'text-body'} ${caption.role === 'user' && !caption.isFinal ? 'text-ink-600' : 'text-ink-900'}`}>
                                {caption.role === 'assistant' ? (
                                    <ReactMarkdown
                                        remarkPlugins={[remarkGfm]}
                                        components={{
                                            p: ({ children }) => <p className="mb-1.5 last:mb-0">{children}</p>,
                                            ul: ({ children }) => <ul className="list-disc pl-5 mb-1.5">{children}</ul>,
                                            ol: ({ children }) => <ol className="list-decimal pl-5 mb-1.5">{children}</ol>,
                                            strong: ({ children }) => <strong className="font-semibold text-brand-800">{children}</strong>,
                                        }}
                                    >
                                        {caption.text}
                                    </ReactMarkdown>
                                ) : (
                                    <>
                                        {caption.text}
                                        {!caption.isFinal && <span className="text-ink-500">…</span>}
                                    </>
                                )}
                            </div>
                        </div>
                    )}
                    {caption.cards?.map((card, idx) => (
                        <div key={idx} className="w-full">
                            <ChatCardRenderer payload={card} />
                        </div>
                    ))}
                </li>
            ))}
        </ol>
    );
};

export default LiveCaptions;
