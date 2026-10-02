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
        chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }, [messages]);

    return (
        <div className="flex-1 px-4 pt-3 pb-4 space-y-4">
            {messages.map((msg) => {
                const hasTextOrGenerating = msg.text || msg.isGenerating;

                return (
                    <div key={msg.id} className="w-full flex flex-col space-y-2 animate-rise motion-reduce:animate-none">
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
                                    className={`max-w-[85%] px-4 py-3 rounded-card overflow-hidden shadow-raised ${msg.role === 'user'
                                        ? 'bg-brand-700 text-white rounded-tr-control'
                                        : 'bg-white text-ink-800 rounded-tl-control'
                                        } ${isElderMode ? 'text-headline' : 'text-callout'}`}
                                >
                                    {msg.text ? (
                                        <ReactMarkdown
                                            remarkPlugins={[remarkGfm]}
                                            components={{
                                                p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                                                ul: ({ children }) => <ul className="list-disc pl-5 mb-2">{children}</ul>,
                                                ol: ({ children }) => <ol className="list-decimal pl-5 mb-2">{children}</ol>,
                                                li: ({ children }) => <li className="mb-1">{children}</li>,
                                                strong: ({ children }) => <strong className={`font-semibold ${msg.role === 'user' ? 'text-white' : 'text-brand-800'}`}>{children}</strong>,
                                                h3: ({ children }) => <h3 className="font-semibold text-title mt-3 mb-1">{children}</h3>,
                                            }}
                                        >
                                            {msg.text}
                                        </ReactMarkdown>
                                    ) : (
                                        <span className="inline-flex gap-1 items-center h-6" aria-label="正在输入">
                                            <span className="w-1.5 h-1.5 bg-ink-300 rounded-full animate-bounce motion-reduce:animate-none [animation-delay:0ms]" />
                                            <span className="w-1.5 h-1.5 bg-ink-300 rounded-full animate-bounce motion-reduce:animate-none [animation-delay:150ms]" />
                                            <span className="w-1.5 h-1.5 bg-ink-300 rounded-full animate-bounce motion-reduce:animate-none [animation-delay:300ms]" />
                                        </span>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                );
            })}
            {/* Spacer that keeps the newest message clear of the docked input bar */}
            <div ref={chatEndRef} className="h-12" aria-hidden />
        </div>
    );
};

export default GlobalChatView;
