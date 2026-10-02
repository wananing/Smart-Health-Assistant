/**
 * AudioWorklet that turns the microphone into PCM16 mono frames at 16 kHz.
 *
 * Kept as a source string and loaded through a Blob URL so it needs no extra
 * Vite worker configuration. It downmixes to mono, decimates from the
 * context rate (usually 48 kHz or 44.1 kHz) by averaging each output
 * sample's input window (a cheap anti-alias box filter), and posts one
 * transferable `ArrayBuffer` per `frameSamples` samples (320 = 20 ms).
 */
export const PCM_CAPTURE_PROCESSOR = 'pcm16-capture';

export const PCM_CAPTURE_WORKLET_SOURCE = `
class Pcm16CaptureProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        const opts = (options && options.processorOptions) || {};
        this.frameSamples = opts.frameSamples || 320;
        // Input samples per output sample; 3 for 48 kHz, 2.75625 for 44.1 kHz.
        this.step = Math.max(1, sampleRate / (opts.targetRate || 16000));
        this.pos = 0;
        this.acc = 0;
        this.count = 0;
        this.frame = new Int16Array(this.frameSamples);
        this.fill = 0;
    }

    process(inputs) {
        const input = inputs[0];
        if (!input || input.length === 0) return true;
        const channels = input.length;
        const length = input[0].length;
        for (let i = 0; i < length; i++) {
            let v = 0;
            for (let c = 0; c < channels; c++) v += input[c][i];
            this.acc += v / channels;
            this.count += 1;
            this.pos += 1;
            if (this.pos >= this.step) {
                this.pos -= this.step;
                let s = this.acc / this.count;
                this.acc = 0;
                this.count = 0;
                s = s > 1 ? 1 : s < -1 ? -1 : s;
                this.frame[this.fill++] = s < 0 ? s * 0x8000 : s * 0x7fff;
                if (this.fill === this.frameSamples) {
                    this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
                    this.frame = new Int16Array(this.frameSamples);
                    this.fill = 0;
                }
            }
        }
        return true;
    }
}

registerProcessor('${PCM_CAPTURE_PROCESSOR}', Pcm16CaptureProcessor);
`;
