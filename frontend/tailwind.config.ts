import type { Config } from "tailwindcss";
import tokens from "./design-system/tokens.json";

/**
 * Thème Tailwind dérivé de design-system/tokens.json (source unique, partagée
 * avec l'app Flutter). Ne pas y écrire de valeur de marque en dur : modifier
 * tokens.json puis `npm run ds:build`.
 */
const colors: Record<string, string> = Object.assign({}, ...Object.values(tokens.color));

const hexToRgb = (hex: string) => [0, 2, 4].map((i) => parseInt(hex.slice(i + 1, i + 3), 16));
const boxShadow = Object.fromEntries(
  Object.entries(tokens.shadow).map(([name, s]) => {
    const [r, g, b] = hexToRgb(s.color);
    return [name, `${s.x}px ${s.y}px ${s.blur}px ${s.spread}px rgba(${r},${g},${b},${s.alpha})`];
  }),
);

const borderRadius = Object.fromEntries(
  Object.entries(tokens.radius)
    .filter(([name]) => name !== "pill" && name !== "sm")
    .map(([name, px]) => [name, `${px}px`]),
);

const fontSize: Record<string, [string, { lineHeight: string; letterSpacing: string; fontWeight: string }]> = {};
for (const [name, t] of Object.entries(tokens.type)) {
  // displayXl -> text-display-xl
  fontSize[name.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase()] = [
    `${t.size / 16}rem`,
    { lineHeight: String(t.line), letterSpacing: `${t.tracking}em`, fontWeight: String(t.weight) },
  ];
}

const [easeEmphasized, easeStandard] = [tokens.motion.easing.emphasized, tokens.motion.easing.standard].map(
  (c) => `cubic-bezier(${c.join(",")})`,
);

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors,
      fontFamily: {
        sans: ["var(--font-body)", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        display: ["var(--font-display)", "var(--font-body)", "system-ui", "sans-serif"],
        brand: ["Bonskin", "var(--font-display)", "cursive"],
      },
      fontSize,
      borderRadius,
      boxShadow,
      transitionTimingFunction: { emphasized: easeEmphasized, standard: easeStandard },
      transitionDuration: {
        fast: `${tokens.motion.duration.fast}ms`,
        base: `${tokens.motion.duration.base}ms`,
        slow: `${tokens.motion.duration.slow}ms`,
      },
      zIndex: Object.fromEntries(Object.entries(tokens.zIndex).map(([k, v]) => [k, String(v)])),
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        pulseDot: {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: ".55", transform: "scale(1.35)" },
        },
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        rise: {
          from: { opacity: "0", transform: "translate3d(0,14px,0)" },
          to: { opacity: "1", transform: "none" },
        },
        scaleIn: {
          from: { opacity: "0", transform: "scale(.96)" },
          to: { opacity: "1", transform: "none" },
        },
        sheetUp: {
          from: { opacity: "0", transform: "translate3d(0,32px,0)" },
          to: { opacity: "1", transform: "none" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
        pulseDot: "pulseDot 1.8s ease-in-out infinite",
        fadeIn: `fadeIn ${tokens.motion.duration.base}ms ${easeEmphasized} both`,
        rise: `rise ${tokens.motion.duration.slow}ms ${easeEmphasized} both`,
        scaleIn: `scaleIn ${tokens.motion.duration.base}ms ${easeEmphasized} both`,
        sheetUp: `sheetUp ${tokens.motion.duration.slow}ms ${easeEmphasized} both`,
      },
    },
  },
  plugins: [],
};
export default config;
