import { useEffect, useRef } from 'react';
import type { FC, PointerEvent } from 'react';
import { X } from 'lucide-react';
import type { VoiceCaption } from '../../types';
import LiveCaptions from './LiveCaptions';

interface TranscriptSheetProps {
    open: boolean;
    onClose: () => void;
    captions: VoiceCaption[];
    isElderMode: boolean;
}

/**
 * Pull-up sheet with the full transcript and cards. It stays mounted while
 * closed (moved off screen and hidden) so the record keeps building up.
 */
const TranscriptSheet: FC<TranscriptSheetProps> = ({ open, onClose, captions, isElderMode }) => {
    const scrollRef = useRef<HTMLDivElement>(null);
    const dragStart = useRef<number | null>(null);

    // Follow the newest line while open; scroll only the sheet, never the page.
    useEffect(() => {
        const el = scrollRef.current;
        if (open && el) el.scrollTop = el.scrollHeight;
    }, [captions, open]);

    const onPointerDown = (event: PointerEvent) => { dragStart.current = event.clientY; };
    const onPointerUp = (event: PointerEvent) => {
        if (dragStart.current !== null && event.clientY - dragStart.current > 40) onClose();
        dragStart.current = null;
    };

    return (
        <>
            <div
                className={`absolute inset-0 z-30 bg-ink-900/25 backdrop-blur-sm transition-opacity duration-slow ${open ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
                onClick={onClose}
                aria-hidden="true"
            />
            <section
                role="dialog"
                aria-label="通话记录"
                aria-hidden={!open}
                data-testid="transcript-sheet"
                data-open={open ? 'true' : 'false'}
                className={`absolute inset-x-0 bottom-0 z-30 flex flex-col max-h-[85%] h-[85%] rounded-t-card bg-white shadow-floating transition-[transform,visibility] duration-slow ease-out ${open ? 'translate-y-0 visible' : 'translate-y-full invisible'}`}
            >
                <header
                    className="shrink-0 px-5 pt-2.5 pb-3 border-b border-ink-100 touch-none"
                    onPointerDown={onPointerDown}
                    onPointerUp={onPointerUp}
                >
                    <div className="w-10 h-1.5 rounded-full bg-ink-200 mx-auto mb-2.5" />
                    <div className="flex items-center justify-between">
                        <h2 className={`font-semibold text-ink-900 ${isElderMode ? 'text-title' : 'text-callout'}`}>通话记录</h2>
                        <button
                            type="button"
                            onClick={onClose}
                            aria-label="收起通话记录"
                            className="w-9 h-9 rounded-full bg-ink-100 text-ink-600 flex items-center justify-center hover:bg-ink-200 transition"
                        >
                            <X size={18} />
                        </button>
                    </div>
                </header>
                <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-5 py-4 pb-[max(env(safe-area-inset-bottom),1.25rem)]">
                    <LiveCaptions captions={captions} isElderMode={isElderMode} />
                </div>
            </section>
        </>
    );
};

export default TranscriptSheet;
