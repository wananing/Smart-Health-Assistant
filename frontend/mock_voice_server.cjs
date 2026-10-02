/*
 * Mock /api/voice server for developing the voice clinic UI without the backend.
 *
 *   node mock_voice_server.cjs                       # ws://localhost:8765/api/voice
 *   VITE_VOICE_WS_URL=ws://localhost:8765/api/voice npm run dev
 *
 * Plays a scripted call over the pinned protocol (docs/voice-clinic.md,
 * 客户端协议): session -> state -> stt -> facts -> followup interrupt ->
 * confirm interrupt -> text/card -> summary, with a synthesized tone as TTS.
 * All transcripts are synthetic.
 *
 * Scenarios (env MOCK_SCENARIO, or GET /scenario/<name> before the next call):
 *   normal     the happy path above
 *   emergency  the first answer trips the red-flag rule -> emergency takeover
 *   drop       the socket is cut after the first follow-up, to exercise reconnect
 *   ptt        after the opening, switches to manual turn-end (degraded + push_to_talk):
 *              the user's answer is committed only by 说完了
 *
 * Like the real gateway, every committed non-speech input (typed text, the
 * confirm tap, a fact edit) is echoed back as stt.final.
 * GET /stats returns uplink/receipt statistics for the latest call, plus every
 * contract violation seen since the server started (see contracts/voice-frames.json:
 * the browser client's frames and this mock's own frames are both checked).
 *
 * No dependencies: the WebSocket framing below is a minimal RFC 6455 server.
 */
const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// ── shared wire contract (same rules as backend/voice/contract.py) ──
const CONTRACT = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'contracts', 'voice-frames.json'), 'utf8'));
const TYPE_CHECKS = {
    string: v => typeof v === 'string',
    integer: v => Number.isInteger(v),
    number: v => typeof v === 'number',
    boolean: v => typeof v === 'boolean',
    object: v => v !== null && typeof v === 'object' && !Array.isArray(v),
    array: v => Array.isArray(v),
    null: v => v === null,
};
const contractViolations = [];
const checkContract = (frame, direction) => {
    const spec = CONTRACT[direction][frame && frame.type];
    if (!spec) {
        contractViolations.push(`${direction} frame type ${JSON.stringify(frame && frame.type)} is not in the contract`);
        return;
    }
    const fields = spec.fields || {};
    const optional = new Set(spec.optional || []);
    const enums = spec.enum || {};
    for (const [name, value] of Object.entries(frame)) {
        if (name === 'type') continue;
        if (!(name in fields)) { contractViolations.push(`${direction} ${frame.type}: unexpected field ${name}`); continue; }
        if (!fields[name].split('|').some(t => TYPE_CHECKS[t](value))) {
            contractViolations.push(`${direction} ${frame.type}.${name}: expected ${fields[name]}`);
        } else if (enums[name] && !enums[name].includes(value)) {
            contractViolations.push(`${direction} ${frame.type}.${name}: ${JSON.stringify(value)} not allowed`);
        }
    }
    for (const name of Object.keys(fields)) {
        if (!optional.has(name) && !(name in frame)) contractViolations.push(`${direction} ${frame.type}: missing field ${name}`);
    }
};

const PORT = Number(process.env.MOCK_VOICE_PORT || 8765);
const WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
const TTS_RATE = 24000;
const TTS_CHUNK_MS = 100;
const TTS_LEAD_CHUNKS = 3; // ~300 ms ahead of real time, like the real gateway
const UPLINK_FRAME_BYTES = 8 + 320 * 2;

let nextScenario = process.env.MOCK_SCENARIO || 'normal';
let lastStats = null;
/** thread_id -> { stage, facts, pendingQuestion } so a reconnect can resume */
const threads = new Map();

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// ─── WebSocket framing ───────────────────────────────────────────────────────

class WsConnection {
    constructor(socket, handlers) {
        this.socket = socket;
        this.handlers = handlers;
        this.buffer = Buffer.alloc(0);
        this.fragments = null;
        this.open = true;
        socket.on('data', chunk => this.onData(chunk));
        socket.on('close', () => this.onClosed());
        socket.on('error', () => this.onClosed());
    }

    onClosed() {
        if (!this.open) return;
        this.open = false;
        this.handlers.onClose();
    }

    onData(chunk) {
        this.buffer = Buffer.concat([this.buffer, chunk]);
        while (this.buffer.length >= 2) {
            const b0 = this.buffer[0];
            const b1 = this.buffer[1];
            const fin = (b0 & 0x80) !== 0;
            const opcode = b0 & 0x0f;
            const masked = (b1 & 0x80) !== 0;
            let length = b1 & 0x7f;
            let offset = 2;
            if (length === 126) {
                if (this.buffer.length < 4) return;
                length = this.buffer.readUInt16BE(2);
                offset = 4;
            } else if (length === 127) {
                if (this.buffer.length < 10) return;
                length = Number(this.buffer.readBigUInt64BE(2));
                offset = 10;
            }
            const maskLength = masked ? 4 : 0;
            if (this.buffer.length < offset + maskLength + length) return;
            const mask = masked ? this.buffer.subarray(offset, offset + 4) : null;
            const payload = Buffer.from(this.buffer.subarray(offset + maskLength, offset + maskLength + length));
            if (mask) for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
            this.buffer = this.buffer.subarray(offset + maskLength + length);
            this.onFrame(fin, opcode, payload);
        }
    }

    onFrame(fin, opcode, payload) {
        if (opcode === 0x8) {
            this.close(payload.length >= 2 ? payload.readUInt16BE(0) : 1000);
            return;
        }
        if (opcode === 0x9) {
            this.sendFrame(0xa, payload);
            return;
        }
        if (opcode === 0xa) return;
        if (opcode === 0x0 && this.fragments) {
            this.fragments.parts.push(payload);
            if (!fin) return;
            const { op, parts } = this.fragments;
            this.fragments = null;
            this.deliver(op, Buffer.concat(parts));
            return;
        }
        if (!fin) {
            this.fragments = { op: opcode, parts: [payload] };
            return;
        }
        this.deliver(opcode, payload);
    }

    deliver(opcode, payload) {
        if (opcode === 0x1) this.handlers.onText(payload.toString('utf8'));
        else if (opcode === 0x2) this.handlers.onBinary(payload);
    }

    sendFrame(opcode, payload) {
        if (!this.open) return;
        let header;
        if (payload.length < 126) {
            header = Buffer.from([0x80 | opcode, payload.length]);
        } else if (payload.length < 65536) {
            header = Buffer.alloc(4);
            header[0] = 0x80 | opcode;
            header[1] = 126;
            header.writeUInt16BE(payload.length, 2);
        } else {
            header = Buffer.alloc(10);
            header[0] = 0x80 | opcode;
            header[1] = 127;
            header.writeBigUInt64BE(BigInt(payload.length), 2);
        }
        this.socket.write(Buffer.concat([header, payload]));
    }

    sendJson(obj) {
        checkContract(obj, 'downlink');
        this.sendFrame(0x1, Buffer.from(JSON.stringify(obj), 'utf8'));
    }

    sendBinary(buf) {
        this.sendFrame(0x2, buf);
    }

    close(code = 1000) {
        if (!this.open) return;
        const payload = Buffer.alloc(2);
        payload.writeUInt16BE(code, 0);
        this.sendFrame(0x8, payload);
        this.open = false;
        this.socket.end();
        this.handlers.onClose();
    }

    /** Cut the TCP connection without a close frame (the browser sees code 1006). */
    drop() {
        this.open = false;
        this.socket.destroy();
        this.handlers.onClose();
    }
}

// ─── TTS stand-in ────────────────────────────────────────────────────────────

/** A speech-like tone: two harmonics with a ~5 Hz syllable envelope. */
const synthesize = (text) => {
    const durationMs = Math.min(3200, 300 + text.length * 110);
    const samples = Math.round(TTS_RATE * durationMs / 1000);
    const pcm = Buffer.alloc(samples * 2);
    for (let i = 0; i < samples; i++) {
        const t = i / TTS_RATE;
        const syllable = 0.55 + 0.45 * Math.sin(2 * Math.PI * 5 * t);
        const fade = Math.min(1, i / 480, (samples - i) / 480);
        const v = (0.6 * Math.sin(2 * Math.PI * 220 * t) + 0.3 * Math.sin(2 * Math.PI * 440 * t)) * 0.25 * syllable * fade;
        pcm.writeInt16LE(Math.round(v * 32767), i * 2);
    }
    return pcm;
};

// ─── One call ────────────────────────────────────────────────────────────────

const FIELD_LABELS = {
    chief_complaint: '主诉', location: '部位', duration: '持续时间', severity: '严重程度',
    associated_symptoms: '伴随症状', onset: '起病方式', triggers: '诱因',
};

const EMPTY_FACTS = {
    chief_complaint: '', location: '', duration: '', severity: '',
    associated_symptoms: [], onset: '', triggers: '',
};

class MockCall {
    constructor(socket, scenario) {
        this.scenario = scenario;
        this.conn = new WsConnection(socket, {
            onText: raw => this.onText(raw),
            onBinary: buf => this.onBinary(buf),
            onClose: () => this.onClose(),
        });
        this.turn = 0;
        this.sentence = 0;
        this.state = null;
        this.stoppedTurns = new Set();
        this.waiters = [];
        this.closed = false;
        this.thread = null;
        this.startedAt = new Date();
        this.manualCommit = false;
        this.stats = {
            scenario,
            hello: null,
            uplinkFrames: 0,
            uplinkBadSize: 0,
            uplinkSeqGaps: 0,
            uplinkOffsetErrors: 0,
            uplinkNonSilentFrames: 0,
            lastSeq: -1,
            receipts: [],
            controls: [],
            stops: [],
        };
        lastStats = this.stats;
    }

    // ── inbound ──

    onText(raw) {
        let msg;
        try {
            msg = JSON.parse(raw);
        } catch {
            contractViolations.push('uplink frame is not JSON');
            return;
        }
        checkContract(msg, 'uplink');
        if (msg.type.startsWith('playback.')) {
            this.stats.receipts.push({ type: msg.type, turn_id: msg.turn_id, sentence_id: msg.sentence_id, played_ms: msg.played_ms });
        } else if (msg.type === 'hello') {
            this.stats.hello = { thread_id: msg.thread_id, caps: msg.caps, user_info: msg.user_info };
            console.log(`[mock] hello thread=${msg.thread_id ?? 'new'} caps=${JSON.stringify(msg.caps)} scenario=${this.scenario}`);
            this.run(msg).catch(err => {
                if (!this.closed) console.error('[mock] script error', err);
            });
        } else {
            this.stats.controls.push(msg.type === 'ui.action' ? `ui.action:${msg.kind}` : msg.type);
            console.log(`[mock] <- ${msg.type}${msg.kind ? `:${msg.kind}` : ''}`);
        }
        if (msg.type === 'bye') this.onBye();
        this.echoCommittedInput(msg);
        this.waiters = this.waiters.filter(waiter => !waiter(msg));
    }

    /** The gateway commits typed text, the confirm tap and fact edits as user turns, echoed as stt.final. */
    echoCommittedInput(msg) {
        let text = null;
        if (msg.type === 'input.text') text = msg.text;
        else if (msg.type === 'ui.action' && msg.kind === 'confirm') text = '对';
        else if (msg.type === 'ui.action' && msg.kind === 'edit_fact') {
            const value = Array.isArray(msg.value) ? msg.value.join('、') : msg.value;
            text = `更正一下，${FIELD_LABELS[msg.field] || msg.field}是${value}`;
        }
        if (text) {
            this.turn += 1;
            this.send({ type: 'stt.final', turn_id: this.turn, text });
        }
    }

    onBinary(buf) {
        const s = this.stats;
        s.uplinkFrames += 1;
        if (buf.length !== UPLINK_FRAME_BYTES) s.uplinkBadSize += 1;
        const seq = buf.readUInt32LE(0);
        const offset = buf.readUInt32LE(4);
        if (seq !== s.lastSeq + 1) s.uplinkSeqGaps += 1;
        if (offset !== seq * 320) s.uplinkOffsetErrors += 1;
        s.lastSeq = seq;
        let peak = 0;
        for (let i = 8; i + 1 < buf.length; i += 2) peak = Math.max(peak, Math.abs(buf.readInt16LE(i)));
        if (peak > 200) s.uplinkNonSilentFrames += 1;
    }

    onClose() {
        if (this.closed) return;
        this.closed = true;
        const s = this.stats;
        console.log(`[mock] closed: uplink frames=${s.uplinkFrames} badSize=${s.uplinkBadSize} seqGaps=${s.uplinkSeqGaps} offsetErrors=${s.uplinkOffsetErrors} nonSilent=${s.uplinkNonSilentFrames} receipts=${s.receipts.length}`);
        this.waiters.forEach(waiter => waiter(null));
        this.waiters = [];
    }

    /** Resolve with the first inbound control frame matching `predicate`, or null on timeout/close. */
    waitFor(predicate, timeoutMs) {
        return new Promise(resolve => {
            const timer = setTimeout(() => {
                this.waiters = this.waiters.filter(waiter => waiter !== check);
                resolve(null);
            }, timeoutMs);
            const check = (msg) => {
                if (msg !== null && !predicate(msg)) return false;
                clearTimeout(timer);
                resolve(msg);
                return true;
            };
            this.waiters.push(check);
        });
    }

    // ── outbound ──

    send(obj) {
        if (!this.closed) this.conn.sendJson(obj);
    }

    setState(value) {
        this.state = value;
        this.send({ type: 'state', value });
    }

    ensureAlive() {
        if (this.closed) throw new Error('closed');
    }

    /**
     * Speak one sentence: announce it, stream paced audio, then wait for the
     * client's playback.ended. Any user input while an interruptible sentence
     * plays triggers the barge-in path: tts.stop and a playback.interrupted.
     */
    async speak(text, { interruptible = true } = {}) {
        this.ensureAlive();
        const turn = this.turn;
        const sentenceId = ++this.sentence;
        this.send({ type: 'tts.sentence', turn_id: turn, sentence_id: sentenceId, text, interruptible, cue: false, sample_rate: TTS_RATE });
        const pcm = synthesize(text);
        const chunkBytes = TTS_RATE * TTS_CHUNK_MS / 1000 * 2;
        let seq = 0;
        let bargedIn = false;
        const barge = interruptible
            ? this.waitFor(msg => msg.type === 'turn.end' || msg.type === 'input.text' || msg.type === 'ui.action', 60_000)
                .then(msg => { if (msg) bargedIn = msg; })
            : null;

        for (let pos = 0; pos < pcm.length; pos += chunkBytes) {
            if (this.closed || bargedIn || this.stoppedTurns.has(turn)) break;
            const header = Buffer.alloc(12);
            header.writeUInt32LE(turn, 0);
            header.writeUInt32LE(sentenceId, 4);
            header.writeUInt32LE(seq++, 8);
            this.conn.sendBinary(Buffer.concat([header, pcm.subarray(pos, pos + chunkBytes)]));
            if (seq > TTS_LEAD_CHUNKS) await sleep(TTS_CHUNK_MS);
        }

        if (!bargedIn) {
            const ended = await Promise.race([
                this.waitFor(msg => msg.type === 'playback.ended' && msg.turn_id === turn && msg.sentence_id === sentenceId, 5000),
                barge ? barge.then(() => null) : new Promise(() => undefined),
            ]);
            if (ended) return { interrupted: false };
        }
        if (!bargedIn) return { interrupted: false };

        // Barge-in: stop this turn, then expect the client's receipt.
        this.stoppedTurns.add(turn);
        const receipt = this.waitFor(msg => msg.type === 'playback.interrupted' && msg.turn_id === turn, 2000);
        this.send({ type: 'tts.stop', turn_id: turn });
        const got = await receipt;
        this.stats.stops.push({ turn_id: turn, receipt: got && { sentence_id: got.sentence_id, played_ms: got.played_ms } });
        // A late chunk from the stopped turn: the client must drop it.
        const late = Buffer.alloc(12 + chunkBytes);
        late.writeUInt32LE(turn, 0);
        late.writeUInt32LE(sentenceId, 4);
        late.writeUInt32LE(9999, 8);
        this.conn.sendBinary(late);
        return { interrupted: true, by: bargedIn };
    }

    /** Assistant turn: text on screen, then spoken; ends in listening. */
    async say(text, { speakText = text, interrupt = null } = {}) {
        this.turn += 1;
        this.send({ type: 'text', content: text });
        if (interrupt) this.send({ type: 'interrupt', content: text, kind: interrupt });
        this.setState('speaking');
        const result = await this.speak(speakText);
        this.setState('listening');
        return result;
    }

    /**
     * The user's turn. Scripted ASR fires after ~1.5 s of listening (the mock
     * cannot understand the fake mic), or immediately on 说完了 / typed text.
     */
    async listen(partials, finalText, bargeIn = null) {
        this.ensureAlive();
        this.turn += 1;
        const turn = this.turn;
        // Manual mode: no endpointing, wait for 说完了 however long it takes.
        const early = bargeIn && (bargeIn.type === 'turn.end' || bargeIn.type === 'input.text')
            ? bargeIn
            : await this.waitFor(msg => msg.type === 'turn.end' || msg.type === 'input.text', this.manualCommit ? 120_000 : 1500);
        this.ensureAlive();
        // Typed text was already echoed as stt.final by echoCommittedInput.
        if (early && early.type === 'input.text') return early.text;
        for (const partial of partials) {
            this.send({ type: 'stt.partial', turn_id: turn, text: partial });
            await sleep(350);
        }
        this.send({ type: 'stt.final', turn_id: turn, text: finalText });
        return finalText;
    }

    sendFacts(missing) {
        const t = this.thread;
        t.factsVersion += 1;
        this.send({ type: 'facts', collected: t.facts, missing, version: t.factsVersion });
    }

    async think(label, ms = 700) {
        this.setState('thinking');
        this.send({ type: 'node_start', node: 'clinic_node', content: label });
        await sleep(ms);
    }

    // ── script ──

    async run(hello) {
        const resumed = hello.thread_id && threads.get(hello.thread_id);
        const threadId = resumed ? hello.thread_id : `mock-${crypto.randomUUID()}`;
        if (!resumed) {
            threads.set(threadId, { stage: 0, facts: { ...EMPTY_FACTS }, factsVersion: 0, pendingQuestion: null, dropped: false, concluded: false, recommendation: null });
        }
        this.thread = threads.get(threadId);
        this.threadId = threadId;
        this.send({ type: 'session', thread_id: threadId });
        const t = this.thread;

        if (resumed && t.pendingQuestion) {
            // Reconnect: the checkpointer still holds the interrupt; say it again (speech only).
            this.sendFacts(missingOf(t.facts));
            this.turn += 1;
            this.send({ type: 'interrupt', content: t.pendingQuestion.text, kind: t.pendingQuestion.kind });
            this.setState('speaking');
            await this.speak(t.pendingQuestion.text);
            this.setState('listening');
        }

        if (t.stage === 0) {
            await this.say('您好，请说说哪里不舒服。');
            if (this.scenario === 'emergency') return this.emergencyPath();
            if (this.scenario === 'ptt') {
                this.manualCommit = true;
                this.send({ type: 'error', class: 'degraded', action: 'push_to_talk', content: '识别不太顺利，您说完后请点一下“说完了”按钮' });
            }
            await this.listen(['我头', '我头疼，已经'], '我头疼，已经三天了');
            await this.think('正在整理症状要点…');
            Object.assign(t.facts, { chief_complaint: '头疼', duration: '三天' });
            this.sendFacts(missingOf(t.facts));
            this.send({ type: 'node_end', node: 'clinic_node' });
            const question = '疼得厉害吗？是一跳一跳地疼，还是一直胀着疼？';
            t.pendingQuestion = { text: question, kind: 'followup' };
            t.stage = 1;
            const asked = await this.say(question, { interrupt: 'followup' });
            this.bargeIn = asked.interrupted ? asked.by : null;
            if (this.scenario === 'drop' && !t.dropped) {
                t.dropped = true;
                await sleep(400);
                console.log('[mock] dropping the socket to exercise reconnect');
                this.conn.drop();
                return;
            }
        }

        if (t.stage === 1) {
            await this.listen(['挺厉害的', '挺厉害的，一跳一跳的'], '挺厉害的，一跳一跳的，还有点恶心', this.bargeIn);
            this.bargeIn = null;
            await this.think('正在整理症状要点…');
            Object.assign(t.facts, { severity: '严重', associated_symptoms: ['恶心'] });
            this.sendFacts(missingOf(t.facts));
            this.send({ type: 'node_end', node: 'clinic_node' });
            const recap = '我确认一下：头疼，三天了，比较严重，还有恶心，对吗？';
            t.pendingQuestion = { text: recap, kind: 'confirm' };
            t.stage = 2;
            const asked = await this.say(recap, { interrupt: 'confirm' });
            this.bargeIn = asked.interrupted ? asked.by : null;
        }

        if (t.stage === 2) {
            // Wait for [对，继续]; edits update the panel and keep waiting.
            for (;;) {
                const msg = this.bargeIn
                    ?? await this.waitFor(m => m.type === 'ui.action' || m.type === 'turn.end' || m.type === 'input.text', 60_000);
                this.bargeIn = null;
                this.ensureAlive();
                if (!msg || msg.kind === 'confirm' || msg.type !== 'ui.action') break;
                if (msg.kind === 'edit_fact' && msg.field in t.facts) {
                    // The gateway merges the edit, echoes it as stt.final and feeds it to
                    // the graph as a correction, which re-extracts and confirms again.
                    t.facts[msg.field] = msg.value;
                    this.sendFacts(missingOf(t.facts));
                    await this.think('正在整理症状要点…', 400);
                    this.send({ type: 'node_end', node: 'clinic_node' });
                    const recap = `我再确认一下：${recapOf(t.facts)}，对吗？`;
                    t.pendingQuestion = { text: recap, kind: 'confirm' };
                    const asked = await this.say(recap, { interrupt: 'confirm' });
                    this.bargeIn = asked.interrupted ? asked.by : null;
                }
            }
            t.pendingQuestion = null;
            await this.conclude();
        }
    }

    /**
     * Like the gateway after the latency work: the first sentence of the body is
     * spoken while the body is still streaming, and the structured card follows
     * a few seconds later (~6 s on the real backend; shortened here).
     */
    async conclude() {
        const t = this.thread;
        this.turn += 1;
        await this.think('正在生成分诊建议…', 500);
        const body = [
            '根据您的描述，**头疼三天、程度较重并伴有恶心**，建议尽快到**神经内科**就诊。\n\n',
            '就诊前可以注意：\n\n- 记录头疼发作的时间和诱因\n',
            '- 保证休息，避免熬夜\n',
            '- 如果出现剧烈头疼、呕吐不止或肢体无力，请立即就医',
        ];
        const startedAt = Date.now();
        this.send({ type: 'text', content: body[0] });
        this.setState('speaking');
        const firstSentence = this.speak('根据您的描述，建议尽快到神经内科就诊。');
        for (const chunk of body.slice(1)) {
            await sleep(400);
            this.send({ type: 'text', content: chunk });
        }
        const first = await firstSentence;
        await sleep(Math.max(0, 2500 - (Date.now() - startedAt)));
        t.recommendation = {
            summary: '头疼三天、程度较重伴恶心，建议尽快到神经内科就诊。',
            departments: ['神经内科'],
            urgency: 'soon',
            severity: 'medium',
            notes: ['记录头疼发作的时间和诱因', '出现剧烈头疼或呕吐不止请立即就医'],
        };
        this.send({ type: 'card', payload: { type: 'clinic_recommendation', data: t.recommendation } });
        this.send({ type: 'node_end', node: 'clinic_node' });
        t.concluded = true;
        t.stage = 3;
        if (!first.interrupted) {
            for (const sentence of ['详细建议在屏幕上。', '以上仅供参考，不能代替医生诊断。']) {
                const result = await this.speak(sentence);
                if (result.interrupted) break;
            }
        }
        this.setState('listening');
    }

    async emergencyPath() {
        const t = this.thread;
        await this.listen(['我胸口', '我胸口剧痛'], '我胸口剧痛，喘不上气');
        t.emergencyFlags = ['胸痛', '呼吸困难'];
        this.turn += 1;
        this.setState('emergency');
        t.facts.chief_complaint = '胸口剧痛';
        t.facts.associated_symptoms = ['呼吸困难'];
        this.sendFacts(missingOf(t.facts));
        t.recommendation = {
            summary: '胸口剧痛伴呼吸困难，可能是危及生命的急症。',
            departments: ['急诊科'],
            urgency: 'emergency',
            severity: 'high',
            notes: ['立即拨打 120', '不要自行驾车前往医院', '保持安静，尽量让身边的人陪同'],
        };
        this.send({ type: 'card', payload: { type: 'clinic_recommendation', data: t.recommendation } });
        // Listen for the dismiss tap from now on: it may come while the safety script still plays.
        const dismissal = this.waitFor(m => m.type === 'ui.action' && m.kind === 'emergency_dismiss', 120_000);
        await this.speak('您描述的情况可能很危险，请立即拨打120，或者马上去最近的急诊。', { interruptible: false });
        t.stage = 3;
        const dismissed = await dismissal;
        if (!dismissed) return;
        await this.say('好的，我们继续。请问除了胸口疼，还有哪里不舒服吗？');
    }

    /** Same shape as build_clinic_summary in backend/voice/gateway.py. */
    onBye() {
        const t = this.thread;
        const rec = t && t.recommendation;
        const facts = t ? Object.entries(FIELD_LABELS)
            .map(([field, label]) => {
                const value = t.facts[field];
                return { field, label, value: Array.isArray(value) ? value.join('、') : value };
            })
            .filter(fact => fact.value) : [];
        const endedAt = new Date();
        const iso = (d) => d.toISOString().replace(/\.\d{3}Z$/, '+00:00');
        this.send({
            type: 'summary',
            payload: {
                type: 'clinic_summary',
                data: {
                    status: rec ? 'completed' : 'incomplete',
                    consultant: (this.stats.hello && this.stats.hello.user_info && this.stats.hello.user_info.name) || '用户',
                    started_at: iso(this.startedAt),
                    ended_at: iso(endedAt),
                    duration_seconds: Math.max(0, Math.floor((endedAt - this.startedAt) / 1000)),
                    chief_complaint: t ? t.facts.chief_complaint : '',
                    facts,
                    departments: rec ? rec.departments : [],
                    urgency: rec ? rec.urgency : null,
                    summary: rec ? rec.summary : '',
                    notes: rec ? rec.notes : [],
                    emergency_flags: (t && t.emergencyFlags) || [],
                    disclaimer: '以上为 AI 预问诊整理，仅供就医参考，不能代替医生诊断。',
                },
            },
        });
        setTimeout(() => this.conn.close(1000), 50);
    }
}

const recapOf = (facts) => Object.keys(FIELD_LABELS)
    .map(field => (Array.isArray(facts[field]) ? facts[field].join('、') : facts[field]))
    .filter(Boolean)
    .join('，');

const missingOf = (facts) => ['chief_complaint', 'location', 'duration', 'severity', 'associated_symptoms']
    .filter(field => (Array.isArray(facts[field]) ? facts[field].length === 0 : !facts[field]));

// ─── HTTP + upgrade ──────────────────────────────────────────────────────────

const server = http.createServer((req, res) => {
    const headers = { 'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/json' };
    const scenario = req.url.match(/^\/scenario\/(\w+)$/);
    if (scenario) {
        nextScenario = scenario[1];
        res.writeHead(200, headers);
        res.end(JSON.stringify({ scenario: nextScenario }));
        return;
    }
    if (req.url === '/stats') {
        res.writeHead(200, headers);
        res.end(JSON.stringify({ ...lastStats, contractViolations }));
        return;
    }
    res.writeHead(404, headers);
    res.end('{}');
});

server.on('upgrade', (req, socket) => {
    if (req.url !== '/api/voice' || !req.headers['sec-websocket-key']) {
        socket.destroy();
        return;
    }
    const accept = crypto.createHash('sha1').update(req.headers['sec-websocket-key'] + WS_GUID).digest('base64');
    socket.write([
        'HTTP/1.1 101 Switching Protocols',
        'Upgrade: websocket',
        'Connection: Upgrade',
        `Sec-WebSocket-Accept: ${accept}`,
        '', '',
    ].join('\r\n'));
    socket.setNoDelay(true);
    console.log(`[mock] connection from origin ${req.headers.origin}`);
    new MockCall(socket, nextScenario);
});

server.listen(PORT, () => {
    console.log(`[mock] voice server on ws://localhost:${PORT}/api/voice (scenario: ${nextScenario})`);
});
