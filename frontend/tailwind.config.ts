import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Identité Tratra : vert de marque dominant + accents jaune et noir.
        primary: "#2e8b57",
        primaryDark: "#1f6a41",
        primarySoft: "#e8f6ee",
        accent: "#F6C90E",
        accentDark: "#d4aa00",
        accentSoft: "#FFF8D6",
        night: "#0b1210",
        nightSoft: "#15201b",
        ink: "#0f172a",
        ash: "#6b7280",
      },
      fontFamily: {
        sans: ["var(--font-body)", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        display: ["var(--font-display)", "var(--font-body)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        soft: "0 8px 24px rgba(15,23,42,.08)",
        strong: "0 16px 48px rgba(15,23,42,.12)",
        glow: "0 12px 40px rgba(46,139,87,.35)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        pulseDot: {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: ".55", transform: "scale(1.35)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
        pulseDot: "pulseDot 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
export default config;
