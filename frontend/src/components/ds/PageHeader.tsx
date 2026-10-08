import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { cx } from "./cx";

/** Lien de retour discret (cible tactile 44 px). */
export function BackLink({ href, children, className = "" }: { href: string; children: ReactNode; className?: string }) {
  return (
    <Link
      href={href}
      className={cx(
        "-ml-2 inline-flex min-h-[44px] items-center gap-1.5 rounded-xl px-2 text-sm font-semibold text-ash transition hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        className,
      )}
    >
      <ArrowLeft aria-hidden className="h-4 w-4" />
      {children}
    </Link>
  );
}

/**
 * En-tête de page connectée : <h1> unique, chapô et actions.
 * (Le bandeau supérieur de l'AppShell n'est pas un titre de page.)
 */
export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
  back,
  className = "",
}: {
  title: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
  className?: string;
}) {
  return (
    <header className={cx("mb-6 sm:mb-8", className)}>
      {back ? <BackLink href={back.href}>{back.label}</BackLink> : null}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 max-w-2xl">
          {eyebrow ? (
            <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-primaryDark">{eyebrow}</p>
          ) : null}
          <h1 className="font-display text-2xl font-extrabold leading-tight tracking-tight text-ink [text-wrap:balance] sm:text-[2rem]">
            {title}
          </h1>
          {description ? <p className="mt-2 text-sm leading-relaxed text-ash sm:text-base">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
      </div>
    </header>
  );
}
