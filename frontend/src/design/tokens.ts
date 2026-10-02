/**
 * Design tokens: the single source for `tailwind.config.ts` and for the few
 * places that need raw values at runtime (the voice orb's gradients).
 *
 * The voice call screen is the first consumer; the rest of the app moves onto
 * these tokens in later rounds. Use the semantic names (`brand`, `ink`, …),
 * never a raw Tailwind colour family, in code that has adopted them.
 */

/** Teal: the brand. Primary actions, listening state, filled facts. */
const brand = {
    50: '#f0fdfa', 100: '#ccfbf1', 200: '#99f6e4', 300: '#5eead4', 400: '#2dd4bf',
    500: '#14b8a6', 600: '#0d9488', 700: '#0f766e', 800: '#115e59', 900: '#134e4a',
} as const;

/** Slate: text, surfaces, hairlines. 500 is the lightest text allowed on white (AA). */
const ink = {
    50: '#f8fafc', 100: '#f1f5f9', 200: '#e2e8f0', 300: '#cbd5e1', 400: '#94a3b8',
    500: '#64748b', 600: '#475569', 700: '#334155', 800: '#1e293b', 900: '#0f172a',
} as const;

/** Violet: the one accent, reserved for "the assistant is thinking". */
const accent = {
    50: '#f5f3ff', 100: '#ede9fe', 200: '#ddd6fe', 300: '#c4b5fd', 400: '#a78bfa',
    500: '#8b5cf6', 600: '#7c3aed', 700: '#6d28d9', 800: '#5b21b6',
} as const;

/** Sky: system information and "the assistant is speaking" (audio playback). */
const info = {
    50: '#f0f9ff', 100: '#e0f2fe', 200: '#bae6fd', 300: '#7dd3fc', 400: '#38bdf8',
    500: '#0ea5e9', 600: '#0284c7', 700: '#0369a1', 800: '#075985',
} as const;

const success = { 50: '#f0fdf4', 100: '#dcfce7', 500: '#22c55e', 600: '#16a34a', 700: '#15803d', 800: '#166534' } as const;

/** Amber: needs attention but not dangerous (confirm, push-to-talk, missing facts). */
const warning = {
    50: '#fffbeb', 100: '#fef3c7', 200: '#fde68a', 300: '#fcd34d', 400: '#fbbf24',
    500: '#f59e0b', 600: '#d97706', 700: '#b45309', 800: '#92400e',
} as const;

/** Rose: hang-up, emergency, errors only. */
const danger = {
    50: '#fff1f2', 100: '#ffe4e6', 200: '#fecdd3', 300: '#fda4af', 400: '#fb7185',
    500: '#f43f5e', 600: '#e11d48', 700: '#be123c', 800: '#9f1239',
} as const;

export const colors = { brand, ink, accent, info, success, warning, danger } as const;

/**
 * Type scale (size / line height). Nothing below 12px; body copy is 14px+.
 * Elder mode moves text one step up.
 */
export const fontSize = {
    caption: ['12px', { lineHeight: '16px' }],
    body: ['14px', { lineHeight: '22px' }],
    callout: ['16px', { lineHeight: '24px' }],
    title: ['18px', { lineHeight: '26px' }],
    headline: ['22px', { lineHeight: '31px' }],
    display: ['28px', { lineHeight: '38px' }],
} satisfies Record<string, [string, { lineHeight: string }]>;

/** System Chinese fonts only; nothing is downloaded. */
export const fontFamily = {
    cn: ['"PingFang SC"', '"HarmonyOS Sans SC"', '"Noto Sans SC"', 'system-ui', 'sans-serif'],
};

/** card: cards and sheets; control: buttons and inputs; full (built in): chips and round buttons. */
export const borderRadius = {
    card: '24px',
    control: '16px',
} as const;

/**
 * raised: resting cards and buttons; floating: sheets, overlays, the primary
 * call-to-action; docked: surfaces pinned to the bottom edge (the shadow falls upward).
 */
export const boxShadow = {
    raised: '0 1px 2px rgba(15, 23, 42, 0.05), 0 8px 24px -12px rgba(15, 23, 42, 0.20)',
    floating: '0 2px 6px rgba(15, 23, 42, 0.06), 0 24px 48px -18px rgba(15, 23, 42, 0.32)',
    docked: '0 -1px 2px rgba(15, 23, 42, 0.04), 0 -12px 32px -16px rgba(15, 23, 42, 0.18)',
} as const;

/** fast: press feedback; base: colour/state changes; slow: sheets and entrances. */
export const transitionDuration = {
    fast: '150ms',
    base: '200ms',
    slow: '300ms',
} as const;
