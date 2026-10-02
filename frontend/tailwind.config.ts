import type { Config } from 'tailwindcss';
import { borderRadius, boxShadow, colors, fontFamily, fontSize, transitionDuration } from './src/design/tokens';

// Tokens live in src/design/tokens.ts (shared with runtime code); this file only wires them in.
export default {
    content: [
        './index.html',
        './src/**/*.{js,ts,jsx,tsx}',
    ],
    theme: {
        extend: {
            colors,
            fontSize,
            fontFamily,
            borderRadius,
            boxShadow,
            transitionDuration,
            // Voice call motion; every use pairs it with motion-reduce:animate-none.
            keyframes: {
                breathe: {
                    '0%, 100%': { transform: 'scale(1)', opacity: '0.55' },
                    '50%': { transform: 'scale(1.06)', opacity: '0.8' },
                },
                rise: {
                    '0%': { transform: 'translateY(12px)', opacity: '0' },
                    '100%': { transform: 'translateY(0)', opacity: '1' },
                },
                'soft-pulse': {
                    '0%, 100%': { boxShadow: `0 0 0 0 ${colors.warning[400]}80` },
                    '50%': { boxShadow: `0 0 0 8px ${colors.warning[400]}00` },
                },
            },
            animation: {
                breathe: 'breathe 3.2s ease-in-out infinite',
                rise: 'rise 300ms cubic-bezier(0.2, 0.8, 0.2, 1) both',
                'soft-pulse': 'soft-pulse 1.6s ease-in-out infinite',
                'spin-slow': 'spin 6s linear infinite',
            },
        },
    },
    plugins: [],
} satisfies Config;
