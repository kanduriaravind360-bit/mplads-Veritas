import type { Config } from "tailwindcss";

// Colours are CSS variables (src/styles/globals.css) so light and dark themes
// share one set of class names. Values are "R G B" triplets for alpha support.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    // 8px grid: spacing steps are multiples of 4px, layouts use the even ones.
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        raised: token("raised"),
        line: token("line"),
        ink: token("ink"),
        muted: token("muted"),
        faint: token("faint"),
        navy: { DEFAULT: "#0B1F3A", 900: "#07142A", 800: "#0B1F3A", 700: "#12305A" },
        saffron: { DEFAULT: "#C55A11", strong: token("saffron-strong"), text: token("saffron-text") },
        band: {
          low: token("band-low"),
          medium: token("band-medium"),
          high: token("band-high"),
          critical: token("band-critical"),
        },
        ok: token("ok"),
        warn: token("warn"),
        danger: token("danger"),
        info: token("info"),
      },
      borderRadius: { lg: "12px", md: "8px", sm: "6px" },
      fontFamily: {
        sans: ['"Inter Variable"', '"Noto Sans Devanagari"', "system-ui", "sans-serif"],
        display: ['"Space Grotesk"', '"Inter Variable"', '"Noto Sans Devanagari"', "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "Consolas", "monospace"],
      },
      fontSize: { "2xs": ["11px", "16px"] },
      boxShadow: {
        card: "0 1px 0 rgb(255 255 255 / 0.03) inset, 0 8px 24px -12px rgb(0 0 0 / 0.45)",
        pop: "0 24px 64px -16px rgb(0 0 0 / 0.55)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "slide-in": { from: { transform: "translateX(24px)", opacity: "0" }, to: { transform: "none", opacity: "1" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
        "slide-in": "slide-in 180ms ease-out",
        "fade-in": "fade-in 160ms ease-out",
      },
    },
  },
  plugins: [],
} satisfies Config;
