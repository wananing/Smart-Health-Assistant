import { useEffect, useRef } from 'react';
import { useGlobalStore } from '../../store/GlobalContext';
import AgentStatusBubble from './AgentStatusBubble';
import ChatCardRenderer from './ChatCardRenderer';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const GlobalChatView = () => {
    const { isElderMode, messages } = useGlobalStore();
    const chatEndRef = useRef<HTMLDivElement>(null);

    // Auto-scroll to bottom on new messages
    useEffect(() => {
        chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    return (
        <div className="flex-1 p-4 space-y-4">
            {messages.map((msg) => {
                const hasTextOrGenerating = msg.text || msg.isGenerating;

                return (
                    <div key={msg.id} className="w-full flex flex-col space-y-2 animate-in slide-in-from-bottom-2">
                        {/* 1. Agent Status Steps (Left aligned) */}
                        {msg.role === 'assistant' && (msg.isGenerating || (msg.steps && msg.steps.length > 0)) && (
                            <div className="flex justify-start">
                                <div className="max-w-[85%]">
                                    <AgentStatusBubble
                                        steps={msg.steps || []}
                                        isGenerating={msg.isGenerating ?? false}
                                    />
                                </div>
                            </div>
                        )}

                        {/* 2. Action Cards (Always Centered) */}
                        {msg.cards && msg.cards.length > 0 && (
                            <div className={`flex flex-col items-center space-y-3 w-full pb-2`}>
                                {msg.cards.map((card, idx) => (
                                    <div key={idx} className="w-full max-w-sm">
                                        <ChatCardRenderer payload={card} />
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* 3. Message Text Bubble (User: Right, Assistant: Left) */}
                        {hasTextOrGenerating && (
                            <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                <div
                                    className={`max-w-[85%] p-4 rounded-2xl shadow-sm overflow-hidden ${msg.role === 'user'
                                        ? 'bg-teal-500 text-white rounded-tr-none'
                                        : 'bg-white text-slate-800 rounded-tl-none border border-slate-100'
                                        } ${isElderMode ? 'text-2xl leading-relaxed' : 'text-base leading-relaxed'}`}
                                >
                                    {msg.text ? (
                                        <ReactMarkdown
                                            remarkPlugins={[remarkGfm]}
                                            components={{
                                                p: ({ node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
                                                ul: ({ node, ...props }) => <ul className="list-disc pl-5 mb-2" {...props} />,
                                                ol: ({ node, ...props }) => <ol className="list-decimal pl-5 mb-2" {...props} />,
                                                li: ({ node, ...props }) => <li className="mb-1" {...props} />,
                                                strong: ({ node, ...props }) => <strong className="font-bold text-teal-700" {...props} />,
                                                h3: ({ node, ...props }) => <h3 className="font-bold text-lg mt-3 mb-1" {...props} />,
                                            }}
                                        >
                                            {msg.text}
                                        </ReactMarkdown>
                                    ) : (
                                        <span className="inline-flex gap-1 items-center text-slate-400">
                                            <span className="w-1.5 h-1.5 bg-slate-300 rounded-full animate-bounce [animation-delay:0ms]" />
                                            <span className="w-1.5 h-1.5 bg-slate-300 rounded-full animate-bounce [animation-delay:150ms]" />
                                            <span className="w-1.5 h-1.5 bg-slate-300 rounded-full animate-bounce [animation-delay:300ms]" />
                                        </span>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                );
            })}
            <div ref={chatEndRef} />
        </div>
    );
};

export default GlobalChatView;
