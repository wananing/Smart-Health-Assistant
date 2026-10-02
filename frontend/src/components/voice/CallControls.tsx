import type { FC, ReactNode } from 'react';
import { Hand, Keyboard, Mic, MicOff, PhoneOff } from 'lucide-react';

interface CallControlsProps {
    muted: boolean;
    /** Whether 说完了 does anything right now (always true in elder mode) */
    canEndTurn: boolean;
    /** Manual turn-end mode while listening: make 说完了 impossible to miss */
    emphasizeEndTurn: boolean;
    textInputOpen: boolean;
    disabled: boolean;
    onToggleMute: () => void;
    onEndTurn: () => void;
    onToggleText: () => void;
    onHangUp: () => void;
    isElderMode: boolean;
}

type Tone = 'neutral' | 'active' | 'primary' | 'danger';

const TONE: Record<Tone, string> = {
    neutral: 'bg-white text-ink-700 shadow-raised ring-1 ring-inset ring-ink-200/80',
    active: 'bg-ink-800 text-white shadow-raised',
    primary: 'bg-gradient-to-b from-brand-500 to-brand-700 text-white shadow-raised',
    danger: 'bg-gradient-to-b from-danger-500 to-danger-600 text-white shadow-raised',
};

// Disabled stays crisp: an outlined, empty button rather than a faded colour block.
const DISABLED = 'bg-ink-50 text-ink-400 ring-1 ring-inset ring-ink-200';

const RoundButton: FC<{
    label: string;
    tone: Tone;
    disabled?: boolean;
    pressed?: boolean;
    emphasized?: boolean;
    onClick: () => void;
    children: ReactNode;
    isElderMode: boolean;
}> = ({ label, tone, disabled = false, pressed, emphasized = false, onClick, children, isElderMode }) => (
    <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-pressed={pressed}
        data-emphasized={emphasized ? 'true' : 'false'}
        className="group flex flex-col items-center gap-1.5 w-[72px] disabled:cursor-not-allowed"
    >
        <span className={`rounded-full flex items-center justify-center transition-all duration-base group-active:scale-95 ${isElderMode ? 'w-[68px] h-[68px]' : 'w-[60px] h-[60px]'} ${disabled ? DISABLED : TONE[tone]} ${emphasized ? 'ring-4 ring-warning-300 animate-soft-pulse motion-reduce:animate-none' : ''}`}>
            {children}
        </span>
        <span className={`font-medium ${isElderMode ? 'text-callout' : 'text-caption'} ${disabled ? 'text-ink-600' : 'text-ink-700'}`}>{label}</span>
    </button>
);

/**
 * Call-style controls: four equal round buttons, each captioned. In elder mode
 * 说完了 becomes a full-width button above the others and is always enabled.
 */
const CallControls: FC<CallControlsProps> = ({
    muted, canEndTurn, emphasizeEndTurn, textInputOpen, disabled, onToggleMute, onEndTurn, onToggleText, onHangUp, isElderMode,
}) => {
    const iconSize = isElderMode ? 28 : 24;
    const endTurnDisabled = disabled || !canEndTurn;

    return (
        <div className="space-y-3">
            {isElderMode && (
                <button
                    type="button"
                    onClick={onEndTurn}
                    disabled={endTurnDisabled}
                    aria-label="说完了"
                    data-emphasized={emphasizeEndTurn ? 'true' : 'false'}
                    className={`w-full h-16 rounded-card flex items-center justify-center gap-2.5 text-headline font-bold transition-all duration-base active:scale-[0.99] ${endTurnDisabled ? DISABLED : TONE.primary} ${emphasizeEndTurn ? 'ring-4 ring-warning-300 animate-soft-pulse motion-reduce:animate-none' : ''}`}
                >
                    <Hand size={30} /> 说完了
                </button>
            )}
            <div className="flex items-start justify-between px-1">
                <RoundButton label={muted ? '取消静音' : '静音'} tone={muted ? 'active' : 'neutral'} pressed={muted} disabled={disabled} onClick={onToggleMute} isElderMode={isElderMode}>
                    {muted ? <MicOff size={iconSize} /> : <Mic size={iconSize} />}
                </RoundButton>
                {!isElderMode && (
                    <RoundButton label="说完了" tone="primary" disabled={endTurnDisabled} emphasized={emphasizeEndTurn} onClick={onEndTurn} isElderMode={isElderMode}>
                        <Hand size={iconSize} />
                    </RoundButton>
                )}
                <RoundButton label="打字" tone={textInputOpen ? 'active' : 'neutral'} pressed={textInputOpen} disabled={disabled} onClick={onToggleText} isElderMode={isElderMode}>
                    <Keyboard size={iconSize} />
                </RoundButton>
                <RoundButton label="挂断" tone="danger" onClick={onHangUp} isElderMode={isElderMode}>
                    <PhoneOff size={iconSize} />
                </RoundButton>
            </div>
        </div>
    );
};

export default CallControls;
