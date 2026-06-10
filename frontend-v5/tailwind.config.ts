import type { Config } from "tailwindcss";

/**
 * Nivesh design tokens — production.
 *
 * Semantic names map to neutral CSS variables defined in src/index.css.
 * Light & dark themes set the variable values; classes stay the same.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ['"Instrument Serif"', "Georgia", "serif"],
        sans: ['"Inter Tight"', "Inter", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        // surfaces
        bg: "rgb(var(--bg) / <alpha-value>)",
        "surface-1": "rgb(var(--surface-1) / <alpha-value>)",
        "surface-2": "rgb(var(--surface-2) / <alpha-value>)",
        "surface-3": "rgb(var(--surface-3) / <alpha-value>)",
        // ink
        ink: "rgb(var(--ink) / <alpha-value>)",
        "ink-2": "rgb(var(--ink-2) / <alpha-value>)",
        "ink-3": "rgb(var(--ink-3) / <alpha-value>)",
        "ink-4": "rgb(var(--ink-4) / <alpha-value>)",
        // accent
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          fg: "rgb(var(--accent-fg) / <alpha-value>)",
          soft: "rgb(var(--accent-soft) / <alpha-value>)",
        },
        // status — used sparingly, semantic
        pos: "rgb(var(--pos) / <alpha-value>)",
        neg: "rgb(var(--neg) / <alpha-value>)",
        warm: "rgb(var(--warm) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
      },
      borderColor: { DEFAULT: "rgb(var(--line) / 1)" },
      borderRadius: {
        sm: "8px",
        DEFAULT: "12px",
        md: "14px",
        lg: "18px",
        xl: "22px",
      },
      boxShadow: {
        card: "0 1px 0 rgb(255 255 255 / 0.04) inset, 0 24px 48px -24px rgb(0 0 0 / 0.6)",
        pop: "0 1px 0 rgb(255 255 255 / 0.06) inset, 0 40px 80px -32px rgb(0 0 0 / 0.7), 0 0 0 1px rgb(255 255 255 / 0.04)",
      },
      letterSpacing: { tightish: "-0.02em" },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "widget-in": {
          "0%": { opacity: "0", transform: "translateY(8px) scale(0.985)" },
          "100%": { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        caret: {
          "0%, 49%": { opacity: "1" },
          "50%, 100%": { opacity: "0" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s linear infinite",
        "widget-in": "widget-in 0.35s cubic-bezier(0.22, 1, 0.36, 1)",
        caret: "caret 1s step-start infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
