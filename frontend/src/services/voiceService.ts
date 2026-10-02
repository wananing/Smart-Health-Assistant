import type {
    ChatCardPayload, SymptomFactField, SymptomFacts, ThreadId, VoiceInterruptKind, VoiceServerState,
} from '../types';
import type { UserInfoPayload } from './chatService';
import { dispatchStreamEvent, type StreamEvent, type StreamEventHandlers } from './streamEvents';
import { PCM_CAPTURE_PROCESSOR, PCM_CAPTURE_WORKLET_SOURCE } from './pcmCaptureWorklet';

/**
 * Real-time voice clinic client for `/api/voice` (design: docs/voice-clinic.md).
 *
 * Text frames are JSON control messages; binary frames are audio.
 *   uplink:   8-byte LE header (u32 seq, u32 sample_offset) + PCM16 mono 16 kHz, 320 samples
 *   downlink: 12-byte LE header (u32 turn_id, u32 sentence_id, u32 seq) + PCM16 mono at the
 *             rate announced by the preceding `tts.sentence`
 *
 * Privacy: never log transcripts, model text or audio from here.
 */

// Same convention as chatService's hardcoded http://localhost:8000; overridable for the mock server.
export const VOICE_WS_URL: string =
    (import.meta.env.VITE_VOICE_WS_URL as string | undefined) || 'ws://localhost:8000/api/voice';

const UPLINK_RATE = 16000;
const UPLINK_FRAME_SAMPLES = 320;
const UPLINK_HEADER_BYTES = 8;
const DOWNLINK_HEADER_BYTES = 12;
const DEFAULT_TTS_RATE = 24000;
/** Cushion before the first chunk after an underrun; the server already paces 200–500 ms ahead. */
const PLAYBACK_LEAD_S = 0.06;
/** With no further audio for a sentence, it counts as ended this long after its audio drains. */
const SENTENCE_END_GRACE_MS = 250;
/** Drop mic frames instead of queueing seconds of stale audio on a stalled socket. */
const MAX_UPLINK_BUFFERED_BYTES = 128 * 1024;
const RECONNECT_DELAYS_MS = [500, 1500, 3000];
const SUMMARY_TIMEOUT_MS = 4000;
const CONSENT_KEY = 'bigh.voiceConsent.v1';

// ─── First-use consent ──────────────────────────────────────────────────────

export const hasVoiceConsent = (): boolean => {
    try {
        return localStorage.getItem(CONSENT_KEY) === '1';
    } catch {
        return false;
    }
};

export const rememberVoiceConsent = (): void => {
    try {
        localStorage.setItem(CONSENT_KEY, '1');
    } catch {
        // Private mode: the notice simply shows again next time.
    }
};

// ─── Gesture-bound audio unlock ─────────────────────────────────────────────

interface PrimedAudio {
    ctx: AudioContext;
    mic: Promise<MediaStream>;
    worklet?: Promise<void>;
}

let primed: PrimedAudio | null = null;

const MIC_CONSTRAINTS: MediaStreamConstraints = {
    audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
    },
};

/**
 * Unlock audio output and request the microphone. Mobile browsers only allow
 * both inside a user gesture, so call this synchronously from a click handler.
 * The resources stay alive until `releaseVoiceCall()`.
 */
export const primeVoiceCall = (): PrimedAudio => {
    if (primed && primed.ctx.state !== 'closed') return primed;

    const ctx = new AudioContext({ latencyHint: 'interactive' });
    void ctx.resume().catch(() => undefined);
    // iOS unlocks output only once a source is started inside the gesture.
    const silent = ctx.createBufferSource();
    silent.buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
    silent.connect(ctx.destination);
    silent.start();

    const mic = navigator.mediaDevices?.getUserMedia
        ? navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS)
        : Promise.reject(new Error('getUserMedia unavailable'));
    // The call awaits it later; mark it handled so a denial is not reported twice.
    mic.catch(() => undefined);

    primed = { ctx, mic };
    return primed;
};

/** Stop the microphone and close the audio context. Called when the call screen closes. */
export const releaseVoiceCall = (): void => {
    if (!primed) return;
    const { ctx, mic } = primed;
    primed = null;
    mic.then(stream => stream.getTracks().forEach(track => track.stop())).catch(() => undefined);
    void ctx.close().catch(() => undefined);
};

const loadCaptureWorklet = async (ctx: AudioContext) => {
    const url = URL.createObjectURL(new Blob([PCM_CAPTURE_WORKLET_SOURCE], { type: 'application/javascript' }));
    try {
        await ctx.audioWorklet.addModule(url);
    } finally {
        URL.revokeObjectURL(url);
    }
};

// ─── Call client ────────────────────────────────────────────────────────────

export type VoiceConnection = 'connecting' | 'open' | 'reconnecting' | 'closed';
export type VoiceErrorClass = 'fatal' | 'transient' | 'degraded' | 'benign';
export type VoiceLocalFailure = 'mic_denied' | 'mic_unavailable' | 'network';

export interface VoiceFactsUpdate {
    collected: Partial<SymptomFacts>;
    missing: SymptomFactField[];
    version: number;
}

export interface SpokenSentence {
    turnId: number;
    sentenceId: number;
    text: string;
    interruptible: boolean;
}

export interface VoiceCallOptions extends StreamEventHandlers {
    onConnection: (status: VoiceConnection) => void;
    onState: (state: VoiceServerState) => void;
    /** Live caption of the user's speech; partials replace each other until the final one */
    onTranscript: (turnId: number, text: string, isFinal: boolean) => void;
    onFacts: (facts: VoiceFactsUpdate) => void;
    /** The graph suspended on a question; `confirm` shows the [对，继续] [我要改] buttons */
    onPendingInterrupt: (kind: VoiceInterruptKind, question: string) => void;
    /** The sentence currently audible, or null once playback goes quiet or is flushed */
    onSpeaking: (sentence: SpokenSentence | null) => void;
    /**
     * `action` refines a class: `degraded` + `push_to_talk` means automatic
     * endpointing is off for the rest of the call (turns end only on 说完了);
     * `degraded` without an action means TTS is unavailable.
     */
    onServerError: (errorClass: VoiceErrorClass, content: string, action?: string) => void;
    onSummary: (card: ChatCardPayload) => void;
    /** The server closed the call itself (exit phrase, idle watchdog) with a normal close */
    onServerEnded: () => void;
    onFailure: (reason: VoiceLocalFailure) => void;
}

/** Downlink JSON frame; the shared SSE-shaped fields come from `StreamEvent`. */
interface VoiceFrame extends StreamEvent {
    value?: unknown;
    turn_id?: unknown;
    sentence_id?: unknown;
    text?: unknown;
    interruptible?: unknown;
    sample_rate?: unknown;
    collected?: unknown;
    missing?: unknown;
    version?: unknown;
    class?: unknown;
    action?: unknown;
    kind?: unknown;
    /** Set on pre-synthesized prompts (tts.sentence); not needed for playback */
    cue?: unknown;
}

interface PlaybackSentence {
    turnId: number;
    sentenceId: number;
    text: string;
    interruptible: boolean;
    sampleRate: number;
    chunks: { start: number; duration: number }[];
    sources: AudioBufferSourceNode[];
    started: boolean;
    finished: boolean;
    startTimer: number | null;
    endTimer: number | null;
}

const SERVER_STATES: readonly VoiceServerState[] = ['listening', 'thinking', 'speaking', 'emergency'];
const ERROR_CLASSES: readonly VoiceErrorClass[] = ['fatal', 'transient', 'degraded', 'benign'];

const asInt = (value: unknown): number | null =>
    typeof value === 'number' && Number.isInteger(value) ? value : null;

const sentenceKey = (turnId: number, sentenceId: number) => `${turnId}:${sentenceId}`;

export class VoiceCall {
    private readonly opts: VoiceCallOptions;
    private threadId: ThreadId | null = null;
    private userInfo: UserInfoPayload = {};

    private ws: WebSocket | null = null;
    private reconnectAttempt = 0;
    private reconnectTimer: number | null = null;
    private disposed = false;
    private hangingUp = false;
    private fatal = false;
    private summaryWaiter: (() => void) | null = null;

    // Capture
    private ctx: AudioContext | null = null;
    private stream: MediaStream | null = null;
    private source: MediaStreamAudioSourceNode | null = null;
    private worklet: AudioWorkletNode | null = null;
    private sink: GainNode | null = null;
    private aec = false;
    private muted = false;
    private seq = 0;
    private sampleOffset = 0;

    // Playback
    private sentences = new Map<string, PlaybackSentence>();
    private lastAnnounced: { turnId: number; sentenceId: number } | null = null;
    private audible: PlaybackSentence | null = null;
    private playhead = 0;
    /** Newest turn the server stopped; audio at or below it is stale and dropped. */
    private stoppedTurn = -1;

    // Levels for the call screen's orb (never logged or sent anywhere)
    private micLevel = 0;
    private micLevelAt = 0;
    private playbackBus: GainNode | null = null;
    private analyser: AnalyserNode | null = null;
    private analyserBuffer: Float32Array<ArrayBuffer> | null = null;

    private wakeLock: WakeLockSentinel | null = null;

    constructor(options: VoiceCallOptions) {
        this.opts = options;
    }

    /** Wait for the microphone, start capture and open the socket. */
    async start(threadId: ThreadId | null, userInfo: UserInfoPayload): Promise<void> {
        this.threadId = threadId;
        this.userInfo = userInfo;
        const audio = primed ?? primeVoiceCall();

        let stream: MediaStream;
        try {
            stream = await audio.mic;
        } catch (err) {
            if (this.disposed) return;
            const denied = err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
            this.opts.onFailure(denied ? 'mic_denied' : 'mic_unavailable');
            return;
        }
        if (this.disposed) return;

        try {
            audio.worklet ??= loadCaptureWorklet(audio.ctx);
            await audio.worklet;
        } catch {
            if (!this.disposed) this.opts.onFailure('mic_unavailable');
            return;
        }
        if (this.disposed) return;

        this.setupCapture(audio.ctx, stream);
        document.addEventListener('visibilitychange', this.handleVisibility);
        void this.acquireWakeLock();
        this.connect();
    }

    setMuted(muted: boolean): void {
        this.muted = muted;
        // Also silence the track itself, so nothing is captured while muted.
        this.stream?.getAudioTracks().forEach(track => { track.enabled = !muted; });
    }

    /** 说完了: end the user's turn immediately. */
    endTurn(): void {
        this.sendJson({ type: 'turn.end', source: 'button' });
    }

    sendText(text: string): void {
        this.sendJson({ type: 'input.text', text });
    }

    confirm(): void {
        this.sendJson({ type: 'ui.action', kind: 'confirm' });
    }

    editFact(field: SymptomFactField, value: string | string[]): void {
        this.sendJson({ type: 'ui.action', kind: 'edit_fact', field, value });
    }

    dismissEmergency(): void {
        this.sendJson({ type: 'ui.action', kind: 'emergency_dismiss' });
    }

    /** Send `bye`, wait briefly for the summary card, then tear down. */
    async hangUp(): Promise<void> {
        this.hangingUp = true;
        this.clearReconnect();
        this.flushPlayback();
        const ws = this.ws;
        if (ws && ws.readyState === WebSocket.OPEN) {
            await new Promise<void>(resolve => {
                const timer = window.setTimeout(resolve, SUMMARY_TIMEOUT_MS);
                this.summaryWaiter = () => {
                    window.clearTimeout(timer);
                    resolve();
                };
                this.sendJson({ type: 'bye' });
            });
            this.summaryWaiter = null;
        }
        this.dispose();
    }

    /** Close the socket and detach audio nodes. The mic itself is released by `releaseVoiceCall()`. */
    dispose(): void {
        if (this.disposed) return;
        this.disposed = true;
        this.clearReconnect();
        document.removeEventListener('visibilitychange', this.handleVisibility);
        void this.wakeLock?.release().catch(() => undefined);
        this.wakeLock = null;

        const ws = this.ws;
        this.ws = null;
        if (ws) {
            ws.onopen = null;
            ws.onmessage = null;
            ws.onclose = null;
            ws.onerror = null;
            if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close(1000);
        }

        this.flushPlayback();
        if (this.worklet) this.worklet.port.onmessage = null;
        this.source?.disconnect();
        this.worklet?.disconnect();
        this.sink?.disconnect();
        this.playbackBus?.disconnect();
        this.analyser?.disconnect();
        this.playbackBus = null;
        this.analyser = null;
        this.source = null;
        this.worklet = null;
        this.sink = null;
        this.stream?.getAudioTracks().forEach(track => { track.enabled = true; });
    }

    // ── capture ─────────────────────────────────────────────────────────────

    private setupCapture(ctx: AudioContext, stream: MediaStream) {
        this.ctx = ctx;
        this.stream = stream;
        // Report AEC only when the browser actually applied it to the granted track.
        this.aec = stream.getAudioTracks()[0]?.getSettings().echoCancellation === true;

        this.source = ctx.createMediaStreamSource(stream);
        this.worklet = new AudioWorkletNode(ctx, PCM_CAPTURE_PROCESSOR, {
            numberOfInputs: 1,
            numberOfOutputs: 1,
            outputChannelCount: [1],
            processorOptions: { targetRate: UPLINK_RATE, frameSamples: UPLINK_FRAME_SAMPLES },
        });
        this.worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
            this.meterMic(event.data);
            this.sendAudio(event.data);
        };
        // A muted sink keeps the worklet pulled by the graph without playing the mic back.
        this.sink = ctx.createGain();
        this.sink.gain.value = 0;
        this.source.connect(this.worklet);
        this.worklet.connect(this.sink);
        this.sink.connect(ctx.destination);
        // All TTS goes through one bus with an analyser, so the orb can follow playback.
        this.playbackBus = ctx.createGain();
        this.analyser = ctx.createAnalyser();
        this.analyser.fftSize = 512;
        this.analyserBuffer = new Float32Array(this.analyser.fftSize);
        this.playbackBus.connect(this.analyser);
        this.analyser.connect(ctx.destination);
        this.setMuted(this.muted);
    }

    /**
     * Current loudness in 0..1 for the call screen: the microphone while the
     * user talks, or TTS playback while the assistant speaks.
     */
    getLevel(source: 'mic' | 'playback'): number {
        if (source === 'mic') {
            // Frames arrive every 20 ms; fade out if they stop (muted, suspended).
            const age = performance.now() - this.micLevelAt;
            return age > 200 ? 0 : this.micLevel;
        }
        const analyser = this.analyser;
        const buffer = this.analyserBuffer;
        if (!analyser || !buffer) return 0;
        analyser.getFloatTimeDomainData(buffer);
        let sum = 0;
        for (let i = 0; i < buffer.length; i++) sum += buffer[i] * buffer[i];
        return Math.min(1, Math.sqrt(sum / buffer.length) * 5);
    }

    private meterMic(pcm: ArrayBuffer) {
        const samples = new Int16Array(pcm);
        let sum = 0;
        for (let i = 0; i < samples.length; i++) {
            const v = samples[i] / 0x8000;
            sum += v * v;
        }
        // Perceptual-ish curve: quiet speech still moves the orb.
        const level = Math.min(1, Math.sqrt(Math.sqrt(sum / samples.length) * 6));
        this.micLevel = this.muted ? 0 : Math.max(level, this.micLevel * 0.8);
        this.micLevelAt = performance.now();
    }

    private sendAudio(pcm: ArrayBuffer) {
        const ws = this.ws;
        if (this.muted || this.hangingUp || !ws || ws.readyState !== WebSocket.OPEN) return;
        if (ws.bufferedAmount > MAX_UPLINK_BUFFERED_BYTES) return;
        const frame = new ArrayBuffer(UPLINK_HEADER_BYTES + pcm.byteLength);
        const view = new DataView(frame);
        view.setUint32(0, this.seq >>> 0, true);
        view.setUint32(4, this.sampleOffset >>> 0, true);
        new Uint8Array(frame, UPLINK_HEADER_BYTES).set(new Uint8Array(pcm));
        ws.send(frame);
        this.seq += 1;
        this.sampleOffset += pcm.byteLength / 2;
    }

    // ── socket ──────────────────────────────────────────────────────────────

    private connect() {
        if (this.disposed) return;
        this.reconnectTimer = null;
        this.opts.onConnection(this.reconnectAttempt > 0 ? 'reconnecting' : 'connecting');
        // Sequence counters, the stale-turn guard and the playback queue are per connection.
        this.seq = 0;
        this.sampleOffset = 0;
        this.stoppedTurn = -1;
        this.lastAnnounced = null;
        this.flushPlayback();

        let ws: WebSocket;
        try {
            ws = new WebSocket(VOICE_WS_URL);
        } catch {
            this.scheduleReconnect();
            return;
        }
        ws.binaryType = 'arraybuffer';
        this.ws = ws;

        ws.onopen = () => {
            this.sendJson({
                type: 'hello',
                thread_id: this.threadId,
                user_info: this.userInfo,
                caps: { aec: this.aec, sample_rate: UPLINK_RATE, playback_receipts: true },
            });
        };
        ws.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
            if (ws !== this.ws) return;
            if (typeof event.data === 'string') this.handleControl(event.data);
            else if (event.data instanceof ArrayBuffer) this.handleAudio(event.data);
        };
        ws.onclose = (event) => this.handleClose(ws, event);
    }

    private handleClose(ws: WebSocket, event: CloseEvent) {
        if (ws !== this.ws) return;
        this.ws = null;
        this.flushPlayback();
        if (this.disposed) return;
        if (this.hangingUp) {
            this.summaryWaiter?.();
            return;
        }
        if (this.fatal) {
            this.opts.onConnection('closed');
            return;
        }
        if (event.code === 1000) {
            this.opts.onConnection('closed');
            this.opts.onServerEnded();
            return;
        }
        this.scheduleReconnect();
    }

    private scheduleReconnect() {
        if (this.disposed) return;
        if (this.reconnectAttempt >= RECONNECT_DELAYS_MS.length) {
            this.opts.onConnection('closed');
            this.opts.onFailure('network');
            return;
        }
        this.opts.onConnection('reconnecting');
        const delay = RECONNECT_DELAYS_MS[this.reconnectAttempt];
        this.reconnectAttempt += 1;
        this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
    }

    private clearReconnect() {
        if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
    }

    private sendJson(frame: Record<string, unknown>) {
        const ws = this.ws;
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(frame));
    }

    private handleControl(raw: string) {
        let msg: VoiceFrame;
        try {
            msg = JSON.parse(raw) as VoiceFrame;
        } catch {
            return;
        }
        if (!msg || typeof msg.type !== 'string') return;

        switch (msg.type) {
            case 'session':
                if (typeof msg.thread_id === 'string') this.threadId = msg.thread_id;
                this.reconnectAttempt = 0;
                this.opts.onConnection('open');
                dispatchStreamEvent(msg, this.opts);
                break;

            case 'state':
                if (SERVER_STATES.includes(msg.value as VoiceServerState)) {
                    this.opts.onState(msg.value as VoiceServerState);
                }
                break;

            case 'stt.partial':
            case 'stt.final': {
                const turnId = asInt(msg.turn_id);
                if (turnId !== null && typeof msg.text === 'string') {
                    this.opts.onTranscript(turnId, msg.text, msg.type === 'stt.final');
                }
                break;
            }

            case 'facts':
                this.opts.onFacts({
                    collected: (msg.collected && typeof msg.collected === 'object' ? msg.collected : {}) as Partial<SymptomFacts>,
                    missing: (Array.isArray(msg.missing) ? msg.missing : []) as SymptomFactField[],
                    version: asInt(msg.version) ?? 0,
                });
                break;

            case 'interrupt':
                dispatchStreamEvent(msg, this.opts);
                this.opts.onPendingInterrupt(msg.kind === 'confirm' ? 'confirm' : 'followup', msg.content ?? '');
                break;

            case 'tts.sentence':
                this.announceSentence(msg);
                break;

            case 'tts.stop': {
                const turnId = asInt(msg.turn_id);
                if (turnId !== null) this.stopTurn(turnId);
                break;
            }

            case 'error': {
                const errorClass = ERROR_CLASSES.includes(msg.class as VoiceErrorClass)
                    ? msg.class as VoiceErrorClass
                    : 'transient';
                if (errorClass === 'fatal') this.fatal = true;
                this.opts.onServerError(errorClass, msg.content ?? '', typeof msg.action === 'string' ? msg.action : undefined);
                break;
            }

            case 'summary':
                if (msg.payload && typeof msg.payload === 'object') {
                    this.opts.onSummary(msg.payload as ChatCardPayload);
                }
                this.summaryWaiter?.();
                break;

            default:
                dispatchStreamEvent(msg, this.opts);
        }
    }

    // ── playback ────────────────────────────────────────────────────────────

    private announceSentence(msg: VoiceFrame) {
        const turnId = asInt(msg.turn_id);
        const sentenceId = asInt(msg.sentence_id);
        if (turnId === null || sentenceId === null || turnId <= this.stoppedTurn) return;
        const sampleRate = asInt(msg.sample_rate) ?? DEFAULT_TTS_RATE;
        const existing = this.sentences.get(sentenceKey(turnId, sentenceId));
        if (existing) {
            existing.text = typeof msg.text === 'string' ? msg.text : existing.text;
            return;
        }
        this.createSentence(turnId, sentenceId, {
            text: typeof msg.text === 'string' ? msg.text : '',
            interruptible: msg.interruptible !== false,
            sampleRate,
        });
    }

    private createSentence(
        turnId: number,
        sentenceId: number,
        info: { text: string; interruptible: boolean; sampleRate: number },
    ): PlaybackSentence {
        const sentence: PlaybackSentence = {
            turnId,
            sentenceId,
            ...info,
            chunks: [],
            sources: [],
            started: false,
            finished: false,
            startTimer: null,
            endTimer: null,
        };
        this.sentences.set(sentenceKey(turnId, sentenceId), sentence);
        this.lastAnnounced = { turnId, sentenceId };
        return sentence;
    }

    private handleAudio(buffer: ArrayBuffer) {
        const ctx = this.ctx;
        if (!ctx || this.hangingUp || buffer.byteLength <= DOWNLINK_HEADER_BYTES) return;
        const view = new DataView(buffer);
        const turnId = view.getUint32(0, true);
        const sentenceId = view.getUint32(4, true);
        // Stale-generation guard: late audio from a stopped turn is dropped, never queued.
        if (turnId <= this.stoppedTurn) return;

        const sentence = this.sentences.get(sentenceKey(turnId, sentenceId))
            ?? this.createSentence(turnId, sentenceId, { text: '', interruptible: true, sampleRate: DEFAULT_TTS_RATE });
        if (sentence.finished) return;

        const samples = new Int16Array(buffer, DOWNLINK_HEADER_BYTES, (buffer.byteLength - DOWNLINK_HEADER_BYTES) >> 1);
        if (samples.length === 0) return;
        const audioBuffer = ctx.createBuffer(1, samples.length, sentence.sampleRate);
        const channel = audioBuffer.getChannelData(0);
        for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 0x8000;

        const node = ctx.createBufferSource();
        node.buffer = audioBuffer;
        node.connect(this.playbackBus ?? ctx.destination);
        const now = ctx.currentTime;
        const startAt = Math.max(this.playhead, now + PLAYBACK_LEAD_S);
        node.start(startAt);
        this.playhead = startAt + audioBuffer.duration;
        sentence.chunks.push({ start: startAt, duration: audioBuffer.duration });
        sentence.sources.push(node);

        if (!sentence.started && sentence.startTimer === null) {
            sentence.startTimer = window.setTimeout(() => this.markStarted(sentence), (startAt - now) * 1000);
        }
        // Audio for a newer sentence means the earlier ones end exactly when they drain.
        for (const other of this.sentences.values()) {
            if (other !== sentence && !other.finished && other.chunks.length > 0) this.scheduleEnd(other, 0);
        }
        this.scheduleEnd(sentence, SENTENCE_END_GRACE_MS);
    }

    private markStarted(sentence: PlaybackSentence) {
        sentence.startTimer = null;
        if (sentence.finished) return;
        sentence.started = true;
        this.audible = sentence;
        this.sendReceipt('playback.started', sentence, 0);
        this.opts.onSpeaking({
            turnId: sentence.turnId,
            sentenceId: sentence.sentenceId,
            text: sentence.text,
            interruptible: sentence.interruptible,
        });
    }

    private scheduleEnd(sentence: PlaybackSentence, graceMs: number) {
        const ctx = this.ctx;
        if (!ctx) return;
        if (sentence.endTimer !== null) window.clearTimeout(sentence.endTimer);
        const last = sentence.chunks[sentence.chunks.length - 1];
        const drainMs = Math.max(0, (last.start + last.duration - ctx.currentTime) * 1000);
        sentence.endTimer = window.setTimeout(() => this.finishSentence(sentence), drainMs + graceMs);
    }

    private finishSentence(sentence: PlaybackSentence) {
        if (sentence.finished) return;
        if (!sentence.started) this.markStarted(sentence);
        sentence.finished = true;
        this.clearSentenceTimers(sentence);
        this.sentences.delete(sentenceKey(sentence.turnId, sentence.sentenceId));
        this.sendReceipt('playback.ended', sentence, this.playedMs(sentence));
        if (this.audible === sentence) {
            this.audible = null;
            this.opts.onSpeaking(null);
        }
    }

    /** `tts.stop`: flush this turn (and older) now and report how much was heard. */
    private stopTurn(turnId: number) {
        this.stoppedTurn = Math.max(this.stoppedTurn, turnId);
        let heard: PlaybackSentence | null = null;
        let heardMs = 0;
        let lastOfTurn: number | null =
            this.lastAnnounced && this.lastAnnounced.turnId === turnId ? this.lastAnnounced.sentenceId : null;

        for (const sentence of [...this.sentences.values()]) {
            if (sentence.turnId > this.stoppedTurn) continue;
            const played = this.playedMs(sentence);
            this.silence(sentence);
            if (sentence.turnId === turnId) {
                lastOfTurn = Math.max(lastOfTurn ?? sentence.sentenceId, sentence.sentenceId);
                if ((sentence.started || played > 0) && (!heard || sentence.sentenceId > heard.sentenceId)) {
                    heard = sentence;
                    heardMs = played;
                }
            }
        }

        if (this.ctx) this.playhead = this.ctx.currentTime;
        if (this.audible && this.audible.turnId <= this.stoppedTurn) {
            this.audible = null;
            this.opts.onSpeaking(null);
        }
        this.sendJson({
            type: 'playback.interrupted',
            turn_id: turnId,
            sentence_id: heard ? heard.sentenceId : lastOfTurn ?? 0,
            played_ms: heard ? heardMs : 0,
        });
    }

    /** Stop everything locally without receipts (socket gone, hang-up, reconnect). */
    private flushPlayback() {
        for (const sentence of [...this.sentences.values()]) this.silence(sentence);
        this.playhead = 0;
        if (this.audible) {
            this.audible = null;
            this.opts.onSpeaking(null);
        }
    }

    private silence(sentence: PlaybackSentence) {
        for (const node of sentence.sources) {
            try {
                node.stop();
            } catch {
                // Already stopped.
            }
        }
        sentence.finished = true;
        this.clearSentenceTimers(sentence);
        this.sentences.delete(sentenceKey(sentence.turnId, sentence.sentenceId));
    }

    private clearSentenceTimers(sentence: PlaybackSentence) {
        if (sentence.startTimer !== null) window.clearTimeout(sentence.startTimer);
        if (sentence.endTimer !== null) window.clearTimeout(sentence.endTimer);
        sentence.startTimer = null;
        sentence.endTimer = null;
    }

    private playedMs(sentence: PlaybackSentence): number {
        const now = this.ctx?.currentTime ?? 0;
        let seconds = 0;
        for (const chunk of sentence.chunks) {
            seconds += Math.min(chunk.duration, Math.max(0, now - chunk.start));
        }
        return Math.round(seconds * 1000);
    }

    private sendReceipt(type: 'playback.started' | 'playback.ended', sentence: PlaybackSentence, playedMs: number) {
        this.sendJson({ type, turn_id: sentence.turnId, sentence_id: sentence.sentenceId, played_ms: playedMs });
    }

    // ── screen wake ─────────────────────────────────────────────────────────

    private async acquireWakeLock() {
        if (this.disposed || document.visibilityState !== 'visible' || !('wakeLock' in navigator)) return;
        try {
            const lock = await navigator.wakeLock.request('screen');
            if (this.disposed) void lock.release();
            else this.wakeLock = lock;
        } catch {
            // Battery saver or unsupported: the call still works, the screen may dim.
        }
    }

    private handleVisibility = () => {
        if (document.visibilityState !== 'visible') return;
        // iOS suspends the context in the background; the lock is dropped on hide.
        void this.ctx?.resume().catch(() => undefined);
        if (!this.wakeLock || this.wakeLock.released) void this.acquireWakeLock();
    };
}
