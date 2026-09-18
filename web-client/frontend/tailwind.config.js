/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Semantic tokens backed by CSS variables (see src/index.css),
        // so the same class works in both themes. The channel form
        // ("R G B", no rgb()/commas) is required for the `<alpha-value>`
        // placeholder to work with opacity modifiers like `bg-accent/10`.
        app: "rgb(var(--app) / <alpha-value>)",
        panel: "rgb(var(--panel) / <alpha-value>)",
        elevated: "rgb(var(--elevated) / <alpha-value>)",
        code: "rgb(var(--code) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        "line-strong": "rgb(var(--line-strong) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        "fg-soft": "rgb(var(--fg-soft) / <alpha-value>)",
        "fg-muted": "rgb(var(--fg-muted) / <alpha-value>)",
        "fg-subtle": "rgb(var(--fg-subtle) / <alpha-value>)",
        "fg-faint": "rgb(var(--fg-faint) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        "accent-hover": "rgb(var(--accent-hover) / <alpha-value>)",
        "accent-fg": "rgb(var(--accent-fg) / <alpha-value>)",
        "accent-text": "rgb(var(--accent-text) / <alpha-value>)",
        ok: "rgb(var(--ok) / <alpha-value>)",
        "ok-hover": "rgb(var(--ok-hover) / <alpha-value>)",
        "ok-text": "rgb(var(--ok-text) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        "danger-strong": "rgb(var(--danger-strong) / <alpha-value>)",
        "danger-hover": "rgb(var(--danger-hover) / <alpha-value>)",
        "danger-text": "rgb(var(--danger-text) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        "warn-text": "rgb(var(--warn-text) / <alpha-value>)",
        "warn-strong": "rgb(var(--warn-strong) / <alpha-value>)",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
        pulseDot: {
          "0%, 80%, 100%": { opacity: "0.25" },
          "40%": { opacity: "1" },
        },
      },
      animation: {
        shimmer: "shimmer 2.4s linear infinite",
        pulseDot: "pulseDot 1.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
