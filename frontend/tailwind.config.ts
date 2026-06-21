import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: "#2e8b57",
        primaryDark: "#1f6a41",
        primarySoft: "#e8f6ee",
        accent: "#F6C90E",
        accentSoft: "#FFF8D6",
        ink: "#0f172a",
        ash: "#6b7280",
      },
      boxShadow: {
        soft: "0 8px 24px rgba(15,23,42,.08)",
        strong: "0 16px 48px rgba(15,23,42,.12)",
      },
    },
  },
  plugins: [],
};
export default config;
