import type { FC } from 'react';
import { Lock } from 'lucide-react';

export interface CurrentUtterance {
    speaker: 'assistant' | 'user';
    text: string;
    /** User: ASR final received. Assistant lines are always final. */
    isFinal: boolean;
    /** Assistant line that cannot be interrupted (the emergency safety script) */
    locked?: boolean;
}

interface CurrentCaptionProps {
    utterance: CurrentUtterance | null;
    placeholder: string;
    isElderMode: boolean;
}

/** Shorter lines get a bigger type step (elder mode one step up), so long ones still fit. */
const sizeFor = (length: number, isElderMode: boolean) => {
    if (length <= 22) return isElderMode ? 'text-display' : 'text-headline';
    if (length <= 48) return isElderMode ? 'text-headline' : 'text-title';
    return isElderMode ? 'text-title' : 'text-callout';
};

/**
 * Only what is being said right now: the assistant's spoken sentence or the
 * user's live transcript. The full history lives in the transcript sheet.
 * The box takes the hero's remaining height and the text hangs from its top,
 * so changing text never moves anything else; very long text scrolls inside
 * it instead of being cut off.
 */
const CurrentCaption: FC<CurrentCaptionProps> = ({ utterance, placeholder, isElderMode }) => {
    const label = utterance?.speaker === 'user' ? '您' : '助手';

    return (
        <div className="flex-1 min-h-0 w-full overflow-y-auto overscroll-contain px-6 flex" data-testid="current-caption"
            data-speaker={utterance?.speaker ?? ''}
            data-final={utterance ? String(utterance.isFinal) : ''}
            aria-live="polite"
        >
            <div className="mx-auto mb-auto mt-[min(2vh,1rem)] max-w-[22rem] text-center">
                {utterance ? (
                    <>
                        <span className={`inline-flex items-center gap-1 mb-2 px-2.5 py-0.5 rounded-full font-semibold ${isElderMode ? 'text-body' : 'text-caption'} ${utterance.speaker === 'user'
                            ? 'bg-brand-50 text-brand-800'
                            : 'bg-white text-ink-600 shadow-raised'}`}
                        >
                            {label}
                            {utterance.locked && <><Lock size={11} /> 请听完</>}
                        </span>
                        <p
                            key={utterance.speaker}
                            className={`font-semibold transition-colors duration-base ${sizeFor(utterance.text.length, isElderMode)} ${utterance.speaker === 'user'
                                ? (utterance.isFinal ? 'text-ink-900' : 'text-ink-600')
                                : 'text-ink-800'}`}
                        >
                            {utterance.text}
                            {!utterance.isFinal && <span className="text-ink-500">…</span>}
                        </p>
                    </>
                ) : (
                    <p className={`text-ink-500 ${isElderMode ? 'text-title' : 'text-callout'}`}>{placeholder}</p>
                )}
            </div>
        </div>
    );
};

export default CurrentCaption;
