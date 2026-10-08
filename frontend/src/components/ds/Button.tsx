import Link from "next/link";
import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cx } from "./cx";
import { Spinner } from "./Spinner";

export type ButtonVariant =
  | "primary"
  | "accent"
  | "night"
  | "soft"
  | "outline"
  | "ghost"
  | "danger"
  | "outlineLight"
  | "outlineNight";
export type ButtonSize = "sm" | "md" | "lg";

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-full font-semibold whitespace-nowrap transition duration-200 ease-emphasized " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 active:scale-[0.98] " +
  "disabled:cursor-not-allowed disabled:opacity-60 disabled:translate-y-0 disabled:active:scale-100 aria-disabled:cursor-not-allowed aria-disabled:opacity-60";

/**
 * Variantes (identité de la landing). Le texte blanc est posé sur `primaryDark`
 * (contraste AA ≥ 4.5:1) ; le vert `primary` reste réservé aux grands titres,
 * icônes et surfaces décoratives.
 *  - primary / soft / outline / ghost / danger : surfaces claires
 *  - accent / outlineLight : surfaces sombres (night)
 *  - night / outlineNight : surfaces jaunes (accent) ou claires
 */
const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-primaryDark text-white shadow-glow hover:-translate-y-0.5 hover:bg-primaryDeep focus-visible:ring-primary focus-visible:ring-offset-white",
  accent:
    "bg-accent text-ink shadow-glowAccent hover:-translate-y-0.5 hover:bg-accentBright focus-visible:ring-white focus-visible:ring-offset-night",
  night:
    "bg-night text-white shadow-strong hover:-translate-y-0.5 hover:bg-nightSoft focus-visible:ring-night focus-visible:ring-offset-accent",
  soft: "bg-primarySoft text-primaryDark hover:bg-primary/15 focus-visible:ring-primary focus-visible:ring-offset-white",
  outline:
    "border border-line bg-white text-ink hover:border-primary/50 hover:text-primaryDark focus-visible:ring-primary focus-visible:ring-offset-white",
  ghost:
    "text-inkSoft hover:bg-lineSoft hover:text-ink focus-visible:ring-primary focus-visible:ring-offset-white",
  danger:
    "bg-danger text-white shadow-hair hover:bg-dangerInk focus-visible:ring-danger focus-visible:ring-offset-white",
  outlineLight:
    "border border-white/25 bg-white/5 text-white backdrop-blur hover:border-white/50 hover:bg-white/10 focus-visible:ring-accent focus-visible:ring-offset-night",
  outlineNight:
    "border-2 border-night/80 text-night hover:bg-night hover:text-white focus-visible:ring-night focus-visible:ring-offset-accent",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "min-h-[40px] px-4 py-2 text-[13px]",
  md: "min-h-[44px] px-5 py-2.5 text-sm",
  lg: "min-h-[52px] px-6 py-3.5 text-[15px] sm:text-base",
};

/** Classes d'un bouton — utilisable sur un <a>, un <Link> ou tout élément. */
export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md", extra = ""): string {
  return cx(BASE, VARIANTS[variant], SIZES[size], extra);
}

interface CommonProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Occupe toute la largeur disponible. */
  block?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  CommonProps & {
    /** Affiche un spinner et désactive le bouton (action asynchrone en cours). */
    loading?: boolean;
  };

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", block, loading, leftIcon, rightIcon, className = "", disabled, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={buttonClass(variant, size, cx(block && "w-full", className))}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Spinner /> : leftIcon}
      {children}
      {!loading ? rightIcon : null}
    </button>
  );
});

export type ButtonLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> &
  CommonProps & { href: string };

/** Lien-bouton : <Link> pour une route interne, <a> pour un lien externe/tel:/mailto:. */
export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  block,
  leftIcon,
  rightIcon,
  className = "",
  children,
  ...props
}: ButtonLinkProps) {
  const cls = buttonClass(variant, size, cx(block && "w-full", className));
  const content = (
    <>
      {leftIcon}
      {children}
      {rightIcon}
    </>
  );
  if (/^(https?:|mailto:|tel:)/i.test(href) || props.target === "_blank") {
    return (
      <a href={href} className={cls} {...props} rel={props.rel ?? "noopener noreferrer"}>
        {content}
      </a>
    );
  }
  return (
    <Link href={href} className={cls} {...props}>
      {content}
    </Link>
  );
}
