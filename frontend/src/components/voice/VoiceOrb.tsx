import { useEffect, useRef } from 'react';
import type { FC } from 'react';
import { AudioLines, CircleAlert, Mic, MicOff } from 'lucide-react';
import { colors } from '../../design/tokens';

/** The four call states from the design, plus the brief connecting phase */
export type CallVisualState = 'connecting' | 'listening' | 'thinking' | 'speaking' | 'error';

interface VoiceOrbProps {
    state: CallVisualState;
    muted: boolean;
    /** Live loudness 0..1 (mic while listening, playback while speaking); polled every frame */
    getLevel: () => number;
    /** Diameter in px of the orb core */
    size: number;
}

/** `#rrggbb` + alpha → rgba(), so the orb's light effects come from the same tokens. */
const alpha = (hex: string, a: number) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
};

const sphere = (light: string, mid: string, deep: string) =>
    `radial-gradient(circle at 35% 30%, ${light} 0%, ${mid} 42%, ${deep} 100%)`;

// Colour carries the state together with motion: brand breathes with the mic,
// info pulses with playback, the accent turns slowly while thinking.
const CORE: Record<CallVisualState, string> = {
    connecting: sphere(colors.ink[100], colors.ink[300], colors.ink[400]),
    listening: sphere(colors.brand[100], colors.brand[400], colors.brand[600]),
    thinking: sphere(colors.accent[100], colors.accent[400], colors.accent[700]),
    speaking: sphere(colors.info[100], colors.info[400], colors.info[700]),
    error: sphere(colors.danger[100], colors.danger[400], colors.danger[700]),
};

const GLOW: Record<CallVisualState, string> = {
    connecting: alpha(colors.ink[400], 0.35),
    listening: alpha(colors.brand[500], 0.45),
    thinking: alpha(colors.accent[500], 0.45),
    speaking: alpha(colors.info[500], 0.45),
    error: alpha(colors.danger[500], 0.35),
};

const prefersReducedMotion = () =>
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** A soft light sphere that reacts to the real audio level of whoever is talking. */
const VoiceOrb: FC<VoiceOrbProps> = ({ state, muted, getLevel, size }) => {
    const haloRef = useRef<HTMLDivElement>(null);
    const coreRef = useRef<HTMLDivElement>(null);
    const reactive = (state === 'listening' && !muted) || state === 'speaking';

    // Drive transform/opacity directly from a rAF loop: no React render per frame.
    useEffect(() => {
        const halo = haloRef.current;
        const core = coreRef.current;
        if (!halo || !core) return;
        if (!reactive || prefersReducedMotion()) {
            halo.style.transform = '';
            halo.style.opacity = '';
            core.style.transform = '';
            return;
        }
        let frame = 0;
        let smooth = 0;
        const tick = () => {
            const level = Math.max(0, Math.min(1, getLevel()));
            // Fast attack, slow release reads as "alive" without jitter.
            smooth = level > smooth ? smooth + (level - smooth) * 0.5 : smooth * 0.9;
            halo.style.transform = `scale(${1 + smooth * 0.28})`;
            halo.style.opacity = String(0.45 + smooth * 0.5);
            core.style.transform = `scale(${1 + smooth * 0.06})`;
            frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(frame);
    }, [reactive, getLevel]);

    const iconSize = Math.round(size * 0.3);
    const quiet = state === 'listening' && muted;

    return (
        <div
            className="relative flex items-center justify-center shrink-0"
            style={{ width: size * 1.3, height: size * 1.3 }}
            aria-hidden="true"
        >
            {/* Halo: stays inside the orb's own box so it never reaches the header */}
            {/* The wrapper breathes (CSS); the inner halo follows the level (rAF). Transforms compose. */}
            <div
                className={`absolute flex items-center justify-center ${state === 'listening' && !quiet ? 'animate-breathe motion-reduce:animate-none' : ''}`}
                style={{ width: size, height: size }}
            >
                <div
                    ref={haloRef}
                    className="w-full h-full rounded-full transition-[background-color] duration-slow"
                    style={{
                        backgroundColor: quiet ? alpha(colors.ink[400], 0.3) : GLOW[state],
                        filter: 'blur(14px)',
                    }}
                />
            </div>
            {/* Thinking: a slow violet conic sweep instead of audio motion */}
            {state === 'thinking' && (
                <div
                    className="absolute rounded-full animate-spin-slow motion-reduce:animate-none"
                    style={{
                        width: size * 1.14,
                        height: size * 1.14,
                        background: `conic-gradient(from 0deg, ${alpha(colors.accent[500], 0)} 0deg, ${alpha(colors.accent[500], 0.55)} 120deg, ${alpha(colors.accent[500], 0)} 240deg)`,
                        filter: 'blur(4px)',
                    }}
                />
            )}
            <div
                ref={coreRef}
                className="relative rounded-full flex items-center justify-center text-white transition-[background] duration-slow"
                style={{
                    width: size,
                    height: size,
                    background: quiet ? CORE.connecting : CORE[state],
                    boxShadow: `0 18px 40px -12px ${GLOW[state]}, 0 4px 12px -4px ${alpha(colors.ink[900], 0.18)}, inset 0 -10px 24px ${alpha(colors.ink[900], 0.12)}, inset 0 10px 22px rgba(255, 255, 255, 0.45)`,
                }}
            >
                {state === 'connecting' && (
                    <span className="flex gap-1.5">
                        {[0, 200, 400].map(delay => (
                            <span key={delay} className="w-2 h-2 rounded-full bg-white/90 animate-pulse motion-reduce:animate-none" style={{ animationDelay: `${delay}ms` }} />
                        ))}
                    </span>
                )}
                {state === 'listening' && (muted ? <MicOff size={iconSize} strokeWidth={2.2} /> : <Mic size={iconSize} strokeWidth={2.2} />)}
                {state === 'thinking' && (
                    <span className="flex gap-1.5">
                        {[0, 160, 320].map(delay => (
                            <span key={delay} className="w-2 h-2 rounded-full bg-white animate-bounce motion-reduce:animate-none" style={{ animationDelay: `${delay}ms` }} />
                        ))}
                    </span>
                )}
                {state === 'speaking' && <AudioLines size={iconSize} strokeWidth={2.2} />}
                {state === 'error' && <CircleAlert size={iconSize} strokeWidth={2.2} />}
            </div>
        </div>
    );
};

export default VoiceOrb;
