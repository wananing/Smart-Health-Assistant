import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { PointerEvent } from 'react';
import { ChevronUp, Send } from 'lucide-react';
import { useGlobalStore } from '../../store/GlobalContext';
import { USER_NAME } from '../../data/mockData';
import {
    VoiceCall, hasVoiceConsent, primeVoiceCall, releaseVoiceCall, rememberVoiceConsent,
    type SpokenSentence, type VoiceConnection, type VoiceLocalFailure,
} from '../../services/voiceService';
import type {
    ChatCardPayload, ChatMessage, ChatMode, ClinicRecommendationData, SymptomFactField, SymptomFacts,
    ThreadId, VoiceCaption, VoiceInterruptKind, VoiceServerState,
} from '../../types';
import { colors } from '../../design/tokens';
import VoiceOrb, { type CallVisualState } from '../../components/voice/VoiceOrb';
import CurrentCaption, { type CurrentUtterance } from '../../components/voice/CurrentCaption';
import SymptomFactsPanel from '../../components/voice/SymptomFactsPanel';
import ConclusionCard from '../../components/voice/ConclusionCard';
import TranscriptSheet from '../../components/voice/TranscriptSheet';
import CallControls from '../../components/voice/CallControls';
import FactEditSheet from '../../components/voice/FactEditSheet';
import EmergencyTakeover from '../../components/voice/EmergencyTakeover';
import VoiceConsentNotice from '../../components/voice/VoiceConsentNotice';
import { SYMPTOM_FACT_FIELDS, formatFactValue } from '../../components/voice/symptomFactLabels';

/** Backgrounded longer than this counts as hanging up (design: 会话、重连与结束). */
const BACKGROUND_HANGUP_MS = 30_000;

const FAILURE_TEXT: Record<VoiceLocalFailure, string> = {
    mic_denied: '没有麦克风权限，请在浏览器设置里允许后重试',
    mic_unavailable: '无法使用麦克风',
    network: '网络连接失败',
};

/** One status line per state; colour matches the orb (AA on the light background). */
const STATUS_TONE: Record<CallVisualState, string> = {
    connecting: 'text-ink-600',
    listening: 'text-brand-800',
    thinking: 'text-accent-700',
    speaking: 'text-info-800',
    error: 'text-danger-700',
};

/** A wash of the state colour behind the orb, cross-faded between states. */
const BACKDROP_TINT: Partial<Record<CallVisualState, string>> = {
    listening: colors.brand[100],
    thinking: colors.accent[100],
    speaking: colors.info[100],
    error: colors.danger[100],
};

const formatElapsed = (seconds: number) =>
    `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;

/** Close the newest assistant caption so the next text starts a new entry. */
const closeAssistant = (captions: VoiceCaption[]): VoiceCaption[] => {
    const last = captions[captions.length - 1];
    if (!last || last.role !== 'assistant' || last.isFinal) return captions;
    return [...captions.slice(0, -1), { ...last, isFinal: true }];
};

/** Apply `update` to the open assistant caption, creating one if needed. */
const withOpenAssistant = (captions: VoiceCaption[], update: (caption: VoiceCaption) => VoiceCaption): VoiceCaption[] => {
    const last = captions[captions.length - 1];
    if (last && last.role === 'assistant' && !last.isFinal) {
        return [...captions.slice(0, -1), update(last)];
    }
    const now = Date.now();
    return [...captions, update({ id: `a-${now}-${captions.length}`, role: 'assistant', text: '', isFinal: false, timestamp: now })];
};

const isRecommendation = (card: ChatCardPayload): card is Extract<ChatCardPayload, { type: 'clinic_recommendation' }> =>
    card.type === 'clinic_recommendation';

// Viewport height drives the orb size, so short phones keep room for content.
const subscribeResize = (onChange: () => void) => {
    window.addEventListener('resize', onChange);
    return () => window.removeEventListener('resize', onChange);
};
const useViewportHeight = () => useSyncExternalStore(subscribeResize, () => window.innerHeight, () => 800);

const VoiceCallScreen = () => {
    const { isElderMode, chatMode, threadId, closeVoiceCall } = useGlobalStore();

    // Captured once: a call continues the clinic text thread it was started from.
    const [initial] = useState(() => ({
        threadId: chatMode === 'clinic' ? threadId : null,
        userInfo: { elder_mode: isElderMode },
    }));
    const [consented, setConsented] = useState(hasVoiceConsent);
    const [attempt, setAttempt] = useState(0);

    const [connection, setConnection] = useState<VoiceConnection>('connecting');
    const [serverState, setServerState] = useState<VoiceServerState | null>(null);
    const [failure, setFailure] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [degraded, setDegraded] = useState(false);
    /** Server turned off automatic endpointing: only 说完了 commits a turn */
    const [pushToTalk, setPushToTalk] = useState<string | null>(null);
    const [connectedAt, setConnectedAt] = useState<number | null>(null);
    const [elapsed, setElapsed] = useState(0);

    const [captions, setCaptions] = useState<VoiceCaption[]>([]);
    const [current, setCurrent] = useState<CurrentUtterance | null>(null);
    const [facts, setFacts] = useState<Partial<SymptomFacts>>({});
    const [missing, setMissing] = useState<SymptomFactField[]>([]);
    const [pending, setPending] = useState<{ kind: VoiceInterruptKind; question: string } | null>(null);
    const [speaking, setSpeaking] = useState<SpokenSentence | null>(null);
    const [thinkingLabel, setThinkingLabel] = useState('');
    const [recommendation, setRecommendation] = useState<ClinicRecommendationData | null>(null);
    const [emergency, setEmergency] = useState(false);
    const [emergencyCard, setEmergencyCard] = useState<ClinicRecommendationData | null>(null);

    const [muted, setMuted] = useState(false);
    const [textOpen, setTextOpen] = useState(false);
    const [textDraft, setTextDraft] = useState('');
    const [editing, setEditing] = useState<SymptomFactField | null>(null);
    const [sheetOpen, setSheetOpen] = useState(false);
    const [unseen, setUnseen] = useState(false);
    const [ending, setEnding] = useState(false);

    const callRef = useRef<VoiceCall | null>(null);
    const captionsRef = useRef<VoiceCaption[]>([]);
    const summaryRef = useRef<ChatCardPayload | null>(null);
    const threadRef = useRef<ThreadId | null>(initial.threadId);
    const modeRef = useRef<ChatMode>('clinic');
    const factsVersionRef = useRef(-1);
    const endingRef = useRef(false);
    /** Bumped on every `session` frame: turn ids restart per connection, caption ids must not. */
    const sessionGenRef = useRef(0);
    const sheetOpenRef = useRef(false);
    const heroRef = useRef<HTMLElement>(null);
    const [heroHeight, setHeroHeight] = useState(0);
    const handleDragStart = useRef<number | null>(null);

    useEffect(() => {
        captionsRef.current = captions;
    }, [captions]);

    useEffect(() => {
        sheetOpenRef.current = sheetOpen;
    }, [sheetOpen]);

    // The orb is sized from the room the hero actually gets, so it yields first.
    useEffect(() => {
        const el = heroRef.current;
        if (!el) return;
        const observer = new ResizeObserver(([entry]) => setHeroHeight(entry.contentRect.height));
        observer.observe(el);
        return () => observer.disconnect();
    }, [consented]);

    /** Merge the call into the chat (captions, cards, summary) and close the screen. */
    const finishCall = useCallback(() => {
        const now = Date.now();
        const messages: ChatMessage[] = [];
        captionsRef.current.forEach((caption, idx) => {
            // An unfinished partial was never committed as a turn, so it is not history.
            if (caption.role === 'user' && !caption.isFinal) return;
            if (!caption.text && !caption.cards?.length) return;
            messages.push({
                id: `voice-${now}-${idx}`,
                role: caption.role,
                text: caption.text,
                timestamp: caption.timestamp,
                cards: caption.cards,
            });
        });
        if (summaryRef.current) {
            messages.push({ id: `voice-${now}-summary`, role: 'assistant', text: '', timestamp: now, cards: [summaryRef.current] });
        }
        closeVoiceCall({ messages, threadId: threadRef.current, mode: modeRef.current });
    }, [closeVoiceCall]);

    const hangUp = useCallback(async () => {
        if (endingRef.current) return;
        endingRef.current = true;
        setEnding(true);
        await callRef.current?.hangUp();
        finishCall();
    }, [finishCall]);

    // One VoiceCall per consent/retry. Under StrictMode the first instance is
    // disposed before its mic promise resolves, so it never opens a socket.
    useEffect(() => {
        if (!consented) return;
        const markUnseen = () => { if (!sheetOpenRef.current) setUnseen(true); };
        const call = new VoiceCall({
            onSession: (id) => {
                threadRef.current = id;
                sessionGenRef.current += 1;
                // A reconnect may resend facts from version 0.
                factsVersionRef.current = -1;
                setConnectedAt(prev => prev ?? Date.now());
            },
            onConnection: (status) => {
                setConnection(status);
                if (status === 'open') setFailure(null);
            },
            onState: (state) => {
                setServerState(state);
                if (state === 'emergency') setEmergency(true);
                if (state === 'thinking') {
                    setPending(null);
                    setThinkingLabel('');
                }
            },
            onTranscript: (turnId, text, isFinal) => {
                setCaptions(prev => {
                    const id = `u-${sessionGenRef.current}-${turnId}`;
                    const existing = prev.findIndex(caption => caption.id === id);
                    if (existing >= 0) {
                        const next = [...prev];
                        next[existing] = { ...next[existing], text, isFinal };
                        return next;
                    }
                    return [...closeAssistant(prev), { id, role: 'user', text, isFinal, timestamp: Date.now() }];
                });
                setCurrent({ speaker: 'user', text, isFinal });
                if (isFinal) setPending(null);
            },
            onChunk: (chunk) => {
                setCaptions(prev => withOpenAssistant(prev, caption => ({ ...caption, text: caption.text + chunk })));
                markUnseen();
            },
            onStep: (step) => setThinkingLabel(step.content),
            onStepFinish: () => undefined,
            onModeChange: (mode) => { modeRef.current = mode; },
            onCard: (card) => {
                setCaptions(prev => withOpenAssistant(prev, caption => ({ ...caption, cards: [...(caption.cards ?? []), card] })));
                markUnseen();
                if (isRecommendation(card)) {
                    if (card.data.urgency === 'emergency') {
                        setEmergency(true);
                        setEmergencyCard(card.data);
                    } else {
                        setRecommendation(card.data);
                    }
                }
            },
            onPendingInterrupt: (kind, question) => {
                setPending({ kind, question });
                setCaptions(closeAssistant);
                // The question stays up as the current line while the user answers.
                setCurrent({ speaker: 'assistant', text: question, isFinal: true });
            },
            onFacts: (update) => {
                if (update.version < factsVersionRef.current) return;
                factsVersionRef.current = update.version;
                setFacts(update.collected);
                setMissing(update.missing);
            },
            onSpeaking: (sentence) => {
                setSpeaking(sentence);
                // When playback stops, the last sentence stays as the current line.
                if (sentence?.text) {
                    setCurrent({ speaker: 'assistant', text: sentence.text, isFinal: true, locked: !sentence.interruptible });
                }
            },
            onServerError: (errorClass, content, action) => {
                if (errorClass === 'fatal') setFailure(content || '语音服务暂不可用，请改用文字问诊');
                else if (errorClass === 'degraded' && action === 'push_to_talk') {
                    // Persistent for the rest of the call, in the server's own words.
                    setPushToTalk(content || '识别不太顺利，您说完后请点一下“说完了”按钮');
                } else if (errorClass === 'degraded') {
                    setDegraded(true);
                    setNotice(content || '语音播报暂不可用，请看屏幕文字');
                } else if (errorClass === 'transient') setNotice(content || '网络有波动，正在重试…');
            },
            onSummary: (card) => { summaryRef.current = card; },
            onServerEnded: () => {
                if (endingRef.current) return;
                endingRef.current = true;
                finishCall();
            },
            onFailure: (reason) => setFailure(FAILURE_TEXT[reason]),
        });
        callRef.current = call;
        void call.start(initial.threadId, initial.userInfo);
        return () => {
            call.dispose();
            if (callRef.current === call) callRef.current = null;
        };
    }, [consented, attempt, initial, finishCall]);

    // Call timer, from the first `session` frame.
    useEffect(() => {
        if (connectedAt === null) return;
        const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - connectedAt) / 1000)), 1000);
        return () => window.clearInterval(timer);
    }, [connectedAt]);

    useEffect(() => {
        if (!notice) return;
        const timer = window.setTimeout(() => setNotice(null), 3500);
        return () => window.clearTimeout(timer);
    }, [notice]);

    // More than 30 s in the background ends the call.
    useEffect(() => {
        let timer: number | undefined;
        const onVisibility = () => {
            window.clearTimeout(timer);
            if (document.visibilityState === 'hidden') {
                timer = window.setTimeout(() => void hangUp(), BACKGROUND_HANGUP_MS);
            }
        };
        document.addEventListener('visibilitychange', onVisibility);
        return () => {
            window.clearTimeout(timer);
            document.removeEventListener('visibilitychange', onVisibility);
        };
    }, [hangUp]);

    const reconnecting = connection === 'reconnecting';
    const visual: CallVisualState = failure || reconnecting
        ? 'error'
        : ending || connection === 'connecting' || serverState === null
            ? 'connecting'
            : serverState === 'emergency' ? 'speaking' : serverState;

    // The orb follows the mic while listening and the playback while speaking.
    const getLevel = useCallback(
        () => callRef.current?.getLevel(visual === 'speaking' ? 'playback' : 'mic') ?? 0,
        [visual],
    );
    const viewportHeight = useViewportHeight();

    const handleAccept = () => {
        // This tap is the user gesture: unlock playback and ask for the mic now.
        primeVoiceCall();
        rememberVoiceConsent();
        setConsented(true);
    };

    const handleRetry = () => {
        // A fresh gesture, so a denied or failed mic request can be asked again.
        releaseVoiceCall();
        primeVoiceCall();
        setFailure(null);
        setConnection('connecting');
        setAttempt(n => n + 1);
    };

    const handleToggleMute = () => {
        const next = !muted;
        setMuted(next);
        callRef.current?.setMuted(next);
    };

    const handleSendText = () => {
        const text = textDraft.trim();
        if (!text) return;
        // No local caption: the gateway echoes every committed input as `stt.final`.
        callRef.current?.sendText(text);
        setTextDraft('');
        setPending(null);
    };

    const handleConfirm = () => {
        callRef.current?.confirm();
        setPending(null);
    };

    /** 我要改: straight into the editor, on the first filled fact. */
    const handleWantEdit = () => {
        const first = SYMPTOM_FACT_FIELDS.find(({ field }) => formatFactValue(facts, field));
        setEditing(first?.field ?? 'chief_complaint');
    };

    const handleSaveFact = (field: SymptomFactField, raw: string) => {
        const value: string | string[] = field === 'associated_symptoms'
            ? raw.split(/[，,、；;\s]+/).map(item => item.trim()).filter(Boolean)
            : raw;
        callRef.current?.editFact(field, value);
        // Optimistic; the next `facts` frame from the server is authoritative.
        setFacts(prev => ({ ...prev, [field]: value }));
        setEditing(null);
    };

    const handleDismissEmergency = () => {
        callRef.current?.dismissEmergency();
        setEmergency(false);
    };

    const openSheet = () => {
        setSheetOpen(true);
        setUnseen(false);
    };

    // The handle opens on tap or on an upward swipe.
    const onHandlePointerDown = (event: PointerEvent) => { handleDragStart.current = event.clientY; };
    const onHandlePointerUp = (event: PointerEvent) => {
        if (handleDragStart.current !== null && handleDragStart.current - event.clientY > 30) openSheet();
        handleDragStart.current = null;
    };

    if (!consented) {
        return (
            <div className="absolute inset-0 z-50 flex flex-col font-cn bg-gradient-to-b from-brand-50 via-white to-ink-50">
                <VoiceConsentNotice onAccept={handleAccept} onDecline={() => closeVoiceCall()} isElderMode={isElderMode} />
            </div>
        );
    }

    const status = failure
        ?? (reconnecting ? '网络中断，正在重连…'
            : ending ? '正在生成问诊小结…'
                : visual === 'connecting' ? '正在接通…'
                    : visual === 'listening' ? (muted ? '已静音' : '正在听…')
                        : visual === 'thinking' ? (thinkingLabel || '正在思考…')
                            : '正在说…');
    const live = connection === 'open' && !failure && !ending;
    const canEndTurn = live && (isElderMode || serverState === 'listening');
    const emphasizeEndTurn = live && pushToTalk !== null && serverState === 'listening';
    // The orb takes what the hero can spare after the status line and two caption lines.
    const statusHeight = isElderMode ? 36 : 30;
    const captionReserve = isElderMode ? 120 : 96;
    const orbSize = Math.round(Math.max(56, Math.min(
        108,
        viewportHeight * (recommendation ? 0.085 : 0.115),
        heroHeight > 0 ? (heroHeight - statusHeight - captionReserve) / 1.3 : 56,
    )));
    // Hard floor for the hero: smallest orb, status and a little caption; cards shrink below this.
    const heroMinHeight = Math.round(56 * 1.3) + statusHeight + (isElderMode ? 84 : 64);
    const connectionDot = connection === 'open' ? 'bg-success-500' : reconnecting || connection === 'connecting' ? 'bg-warning-500' : 'bg-danger-500';
    const connectionLabel = connection === 'open' ? '已连接' : reconnecting ? '重连中' : connection === 'connecting' ? '连接中' : '已断开';

    return (
        // overflow-clip (not hidden): focusing an input must never scroll the call screen itself
        <div className="absolute inset-0 z-50 flex flex-col overflow-hidden supports-[overflow:clip]:overflow-clip font-cn bg-ink-50" data-testid="voice-call">
            {/* Light, layered backdrop: a soft top wash plus a state tint behind the orb */}
            <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
                <div className="absolute inset-0 bg-gradient-to-b from-white to-ink-50" />
                {(Object.keys(BACKDROP_TINT) as CallVisualState[]).map(state => (
                    <div
                        key={state}
                        className={`absolute left-1/2 top-[22%] w-[150%] aspect-square -translate-x-1/2 -translate-y-1/2 rounded-full transition-opacity duration-slow ${visual === state ? 'opacity-100' : 'opacity-0'}`}
                        style={{ background: `radial-gradient(closest-side, ${BACKDROP_TINT[state]}, transparent)` }}
                    />
                ))}
            </div>

            {/* Header: never overlapped by the orb */}
            <header className="relative z-10 shrink-0 flex items-start justify-between gap-3 px-5 pt-[max(env(safe-area-inset-top),0.875rem)] pb-2">
                <div className="min-w-0">
                    <h1 className={`font-semibold text-ink-900 ${isElderMode ? 'text-headline' : 'text-title'}`}>语音问诊</h1>
                    <p className={`text-ink-600 truncate ${isElderMode ? 'text-callout' : 'text-body'}`}>咨询人 · {USER_NAME}</p>
                </div>
                <div className="shrink-0 flex items-center gap-2 rounded-full bg-white/90 pl-3 pr-2.5 py-1.5 shadow-raised">
                    <span className={`font-semibold tabular-nums text-ink-800 ${isElderMode ? 'text-callout' : 'text-body'}`}>{formatElapsed(elapsed)}</span>
                    <span className="flex items-center gap-1" title={connectionLabel}>
                        <span className={`w-2 h-2 rounded-full ${connectionDot} ${connection === 'open' ? '' : 'animate-pulse motion-reduce:animate-none'}`} />
                        <span className={`text-ink-600 ${isElderMode ? 'text-body' : 'text-caption'}`}>{connectionLabel}</span>
                    </span>
                </div>
            </header>

            {/* Hero: orb, one status line, and only the current utterance. Its minimum
                height is reserved, so the cards below shrink (and scroll) before it does. */}
            <main ref={heroRef} className="relative z-10 flex-1 flex flex-col items-center overflow-hidden" style={{ minHeight: heroMinHeight }}>
                <div data-call-state={visual} className="shrink-0">
                    <VoiceOrb state={visual} muted={muted} getLevel={getLevel} size={orbSize} />
                </div>
                <p className={`shrink-0 font-semibold transition-colors duration-base ${STATUS_TONE[visual]} ${isElderMode ? 'text-title' : 'text-callout'}`} role="status">
                    {status}
                </p>
                {(pushToTalk || degraded || notice) && (
                    <div className="shrink-0 flex flex-col items-center gap-1.5 mt-1.5 px-4 text-center">
                        {notice && (
                            <span role="status" className={`rounded-full bg-ink-800 text-white px-3 py-1 shadow-raised animate-rise motion-reduce:animate-none ${isElderMode ? 'text-body' : 'text-caption'}`}>
                                {notice}
                            </span>
                        )}
                        {pushToTalk && (
                            <span className={`rounded-full bg-warning-50 text-warning-800 ring-1 ring-inset ring-warning-200 px-3 py-1 ${isElderMode ? 'text-body' : 'text-caption'}`} data-testid="push-to-talk-hint">
                                {pushToTalk}
                            </span>
                        )}
                        {degraded && (
                            <span className={`rounded-full bg-warning-50 text-warning-800 ring-1 ring-inset ring-warning-200 px-2.5 py-0.5 ${isElderMode ? 'text-body' : 'text-caption'}`}>
                                语音播报暂不可用，请看屏幕文字
                            </span>
                        )}
                    </div>
                )}
                {failure ? (
                    <div className="flex-1 flex items-center gap-2">
                        <button type="button" onClick={handleRetry} className="h-11 px-5 rounded-full bg-white text-ink-800 font-semibold text-body shadow-raised ring-1 ring-inset ring-ink-200">重试</button>
                        <button type="button" onClick={finishCall} className="h-11 px-5 rounded-full bg-brand-700 text-white font-semibold text-body shadow-raised">改用文字问诊</button>
                    </div>
                ) : (
                    <div className="flex-1 min-h-0 w-full flex pt-2">
                        <CurrentCaption
                            utterance={current}
                            placeholder={visual === 'connecting' ? '接通后，直接说出哪里不舒服' : '请说出哪里不舒服'}
                            isElderMode={isElderMode}
                        />
                    </div>
                )}
            </main>

            {/* Pinned: conclusion (once it arrives) and the facts card */}
            <div className="relative z-10 shrink min-h-0 overflow-y-auto overscroll-contain px-4 pt-1 pb-1 space-y-2.5" data-testid="pinned-cards">
                {recommendation && (
                    <ConclusionCard recommendation={recommendation} onOpenDetails={openSheet} isElderMode={isElderMode} />
                )}
                <SymptomFactsPanel
                    facts={facts}
                    missing={missing}
                    confirmPending={pending?.kind === 'confirm'}
                    onEdit={setEditing}
                    compact={recommendation !== null || isElderMode}
                    isElderMode={isElderMode}
                />
            </div>

            {/* Recap answers sit outside the scroll area so they can never scroll away */}
            {pending?.kind === 'confirm' && (
                <div className="relative z-10 shrink-0 grid grid-cols-2 gap-2.5 px-4 pt-2 animate-rise motion-reduce:animate-none">
                    <button
                        type="button"
                        onClick={handleWantEdit}
                        className={`rounded-control bg-white font-semibold text-warning-800 shadow-raised ring-1 ring-inset ring-warning-300 hover:bg-warning-50 active:scale-[0.98] transition duration-fast ${isElderMode ? 'h-14 text-title' : 'h-12 text-callout'}`}
                    >
                        我要改
                    </button>
                    <button
                        type="button"
                        onClick={handleConfirm}
                        className={`rounded-control bg-brand-700 font-semibold text-white shadow-raised hover:bg-brand-800 active:scale-[0.98] transition duration-fast ${isElderMode ? 'h-14 text-title' : 'h-12 text-callout'}`}
                    >
                        对，继续
                    </button>
                </div>
            )}

            <button
                type="button"
                onClick={openSheet}
                onPointerDown={onHandlePointerDown}
                onPointerUp={onHandlePointerUp}
                data-testid="open-transcript"
                className={`relative z-10 shrink-0 mx-auto mt-1 flex items-center gap-1 rounded-full px-3 py-1 text-ink-600 hover:text-ink-800 transition-colors duration-base touch-none ${isElderMode ? 'text-callout' : 'text-body'}`}
            >
                <ChevronUp size={16} />
                通话记录
                {unseen && <span className="w-2 h-2 rounded-full bg-brand-500" aria-label="有新内容" />}
            </button>

            {textOpen && (
                <div className="relative z-10 shrink-0 px-4 pt-2 flex gap-2">
                    <input
                        type="text"
                        value={textDraft}
                        onChange={event => setTextDraft(event.target.value)}
                        onKeyDown={event => event.key === 'Enter' && handleSendText()}
                        placeholder="打字描述症状…"
                        className={`flex-1 min-w-0 rounded-full bg-white px-4 text-ink-900 shadow-raised ring-1 ring-inset ring-ink-200 placeholder:text-ink-500 focus:outline-none focus:ring-2 focus:ring-brand-600 ${isElderMode ? 'h-14 text-title' : 'h-11 text-callout'}`}
                    />
                    <button
                        type="button"
                        onClick={handleSendText}
                        disabled={!live || !textDraft.trim()}
                        aria-label="发送"
                        className={`shrink-0 rounded-full bg-brand-700 text-white flex items-center justify-center shadow-raised disabled:bg-ink-100 disabled:text-ink-400 disabled:shadow-none transition-colors duration-base ${isElderMode ? 'w-14 h-14' : 'w-11 h-11'}`}
                    >
                        <Send size={18} />
                    </button>
                </div>
            )}

            <footer className="relative z-10 shrink-0 px-4 pt-3 pb-[max(env(safe-area-inset-bottom),1rem)]">
                <CallControls
                    muted={muted}
                    canEndTurn={canEndTurn}
                    emphasizeEndTurn={emphasizeEndTurn}
                    textInputOpen={textOpen}
                    disabled={!live}
                    onToggleMute={handleToggleMute}
                    onEndTurn={() => callRef.current?.endTurn()}
                    onToggleText={() => setTextOpen(open => !open)}
                    onHangUp={() => void hangUp()}
                    isElderMode={isElderMode}
                />
            </footer>

            <TranscriptSheet open={sheetOpen} onClose={() => setSheetOpen(false)} captions={captions} isElderMode={isElderMode} />

            {editing && (
                <FactEditSheet
                    initialField={editing}
                    facts={facts}
                    onSave={handleSaveFact}
                    onCancel={() => setEditing(null)}
                    isElderMode={isElderMode}
                />
            )}

            {emergency && (
                <EmergencyTakeover
                    recommendation={emergencyCard}
                    spokenText={speaking?.text ?? null}
                    onDismiss={handleDismissEmergency}
                    onHangUp={() => void hangUp()}
                    isElderMode={isElderMode}
                />
            )}
        </div>
    );
};

export default VoiceCallScreen;
