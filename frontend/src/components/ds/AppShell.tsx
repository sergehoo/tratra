"use client";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Circle, Ellipsis, Globe, LogOut, type LucideIcon } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Avatar } from "./Avatar";
import { Alert } from "./Alert";
import { Badge } from "./Badge";
import { BrandWordmark } from "./BrandWordmark";
import { ButtonLink } from "./Button";
import { cx } from "./cx";
import { Modal } from "./Modal";

export interface NavItem {
  href: string;
  label: string;
  /** Libellé court pour la barre de navigation mobile (sinon `label`). */
  short?: string;
  /** Icône lucide (indispensable pour la barre de navigation mobile). */
  icon?: LucideIcon;
  /** Compteur réel (non lus…) — affiché seulement s'il est > 0. */
  badge?: number;
  /** Mobile : fait partie des onglets du bas ; les autres vont dans « Plus » (si plus de 5 entrées). */
  primary?: boolean;
}

const ROLE_LABEL: Record<string, string> = {
  client: "Client",
  employeur: "Employeur",
  handyman: "Artisan",
  entreprise: "Entreprise",
  admin: "Administrateur",
};

const RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";

/** L'entrée active est la plus longue dont l'URL est un préfixe (limite de segment) du chemin courant. */
function activeHref(items: NavItem[], pathname: string): string | null {
  let best: string | null = null;
  for (const it of items) {
    const h = it.href.split(/[?#]/)[0];
    const hit = pathname === h || pathname.startsWith(h.endsWith("/") ? h : `${h}/`);
    if (hit && (!best || h.length > best.split(/[?#]/)[0].length)) best = it.href;
  }
  return best;
}

function BrandMark({ className = "" }: { className?: string }) {
  return (
    <span className={cx("grid place-items-center rounded-xl bg-white shadow-hair ring-1 ring-black/5", className)}>
      <Image src="/tratra_logo.webp" alt="" width={28} height={28} className="h-7 w-7" />
    </span>
  );
}

function UserMenu({ onLogout }: { onLogout: () => void }) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  if (!user) return null;
  const name = [user.first_name, user.last_name].filter(Boolean).join(" ") || user.phone || user.username;
  const role = ROLE_LABEL[user.user_type] ?? user.user_type;

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`Menu du compte de ${name}`}
        className={cx(
          "flex min-h-[44px] items-center gap-2.5 rounded-full border border-line bg-white py-1 pl-1 pr-3 transition hover:border-primary/40 sm:pr-3.5",
          RING,
        )}
      >
        <Avatar name={name} size={36} />
        <span className="hidden min-w-0 text-left sm:block">
          <span className="block max-w-[10rem] truncate text-sm font-semibold leading-tight text-ink">{name}</span>
          <span className="block text-[11px] font-medium leading-tight text-ash">{role}</span>
        </span>
        <ChevronDown aria-hidden className={cx("h-4 w-4 text-ash transition-transform duration-200", open && "rotate-180")} />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-overlay mt-2 w-72 origin-top-right animate-scaleIn rounded-panel border border-lineSoft bg-white p-2 shadow-strong"
        >
          <div className="flex items-center gap-3 px-3 py-3">
            <Avatar name={name} size={44} />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-ink">{name}</p>
              {user.email || user.phone ? <p className="truncate text-xs text-ash">{user.email || user.phone}</p> : null}
              <Badge tone="primary" className="mt-1.5">
                {role}
              </Badge>
            </div>
          </div>
          <div className="my-1 border-t border-lineSoft" />
          <Link
            href="/"
            role="menuitem"
            onClick={() => setOpen(false)}
            className={cx("flex min-h-[44px] items-center gap-3 rounded-xl px-3 text-sm font-medium text-inkSoft transition hover:bg-canvas hover:text-ink", RING)}
          >
            <Globe aria-hidden className="h-4 w-4" />
            Voir le site
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={onLogout}
            className={cx("flex min-h-[44px] w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium text-dangerInk transition hover:bg-dangerSoft", RING)}
          >
            <LogOut aria-hidden className="h-4 w-4" />
            Déconnexion
          </button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Coquille des espaces connectés (client, artisan, entreprise, back-office) :
 * barre latérale ≥ lg, barre supérieure + navigation basse en mobile.
 * L'unique <h1> d'une page est fourni par <PageHeader /> dans le contenu.
 */
export function AppShell({ title, nav, children }: { title: string; nav: NavItem[]; children: ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  // Numéro enregistré mais non vérifié : rappel discret vers la vérification par code.
  const needsPhoneCheck = Boolean(user?.phone) && user?.is_verified === false;
  const active = activeHref(nav, pathname);
  // Mobile : > 5 entrées -> 4 onglets « primary » + « Plus » (feuille avec le reste).
  const primaryItems = nav.filter((n) => n.primary).slice(0, 4);
  const useMore = nav.length > 5 && primaryItems.length > 0;
  const bottomItems = useMore ? primaryItems : nav;
  const moreItems = useMore ? nav.filter((n) => !primaryItems.includes(n)) : [];
  const scrollableBottom = !useMore && nav.length > 5;
  const [moreOpen, setMoreOpen] = useState(false);
  useEffect(() => setMoreOpen(false), [pathname]);
  const moreActive = moreItems.some((n) => n.href === active);
  const moreBadge = moreItems.reduce((sum, n) => sum + (n.badge ?? 0), 0);

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <a href="#contenu" className="skip-link">
        Aller au contenu
      </a>

      {/* Barre latérale (bureau) */}
      <aside className="fixed inset-y-0 left-0 z-header hidden w-64 flex-col border-r border-lineSoft bg-white lg:flex">
        <div className="px-5 pb-4 pt-6">
          <Link href="/" aria-label="Tratra — retour au site" className={cx("flex items-center gap-2.5 rounded-2xl", RING)}>
            <BrandMark className="h-11 w-11" />
            <BrandWordmark />
          </Link>
        </div>
        <p className="mx-5 mb-3 mt-2 inline-flex w-fit items-center gap-2 rounded-full bg-accentSoft px-3 py-1 text-[11px] font-bold uppercase tracking-[0.14em] text-ink ring-1 ring-inset ring-accent/40">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accentDark" />
          {title}
        </p>
        <nav aria-label={`Navigation — ${title}`} className="flex-1 overflow-y-auto px-3">
          <ul className="space-y-1">
            {nav.map((n) => {
              const isActive = n.href === active;
              const Icon = n.icon ?? Circle;
              return (
                <li key={n.href}>
                  <Link
                    href={n.href}
                    aria-current={isActive ? "page" : undefined}
                    className={cx(
                      "group relative flex min-h-[44px] items-center gap-3 rounded-xl px-3 text-sm font-semibold transition duration-200",
                      RING,
                      isActive ? "bg-primarySoft text-primaryDark" : "text-inkSoft hover:bg-canvas hover:text-ink",
                    )}
                  >
                    {isActive ? <span aria-hidden className="absolute -left-3 h-6 w-1 rounded-r-full bg-accent" /> : null}
                    <Icon aria-hidden className={cx("h-[18px] w-[18px] shrink-0", isActive ? "text-primary" : "text-ash group-hover:text-ink")} />
                    {n.label}
                    {n.badge ? (
                      <span className="ml-auto rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold leading-none text-ink">
                        {n.badge > 99 ? "99+" : n.badge}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="border-t border-lineSoft p-3">
          <Link
            href="/"
            className={cx("flex min-h-[44px] items-center gap-3 rounded-xl px-3 text-sm font-medium text-ash transition hover:bg-canvas hover:text-ink", RING)}
          >
            <Globe aria-hidden className="h-[18px] w-[18px]" />
            Voir le site
          </Link>
          <button
            type="button"
            onClick={() => void logout()}
            className={cx("flex min-h-[44px] w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium text-ash transition hover:bg-dangerSoft hover:text-dangerInk", RING)}
          >
            <LogOut aria-hidden className="h-[18px] w-[18px]" />
            Déconnexion
          </button>
        </div>
      </aside>

      <div className="lg:pl-64">
        {/* Barre supérieure */}
        <header className="safe-top sticky top-0 z-header border-b border-lineSoft bg-white/90 backdrop-blur-md">
          <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <Link href="/" aria-label="Tratra — retour au site" className={cx("rounded-xl lg:hidden", RING)}>
                <BrandMark className="h-10 w-10" />
              </Link>
              <p className="truncate font-display text-base font-bold text-ink">{title}</p>
            </div>
            <UserMenu onLogout={() => void logout()} />
          </div>
        </header>

        <div className="relative">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-gradient-to-b from-primarySoft/70 to-transparent"
          />
          <main
            id="contenu"
            className="relative mx-auto w-full max-w-6xl animate-fadeIn px-4 pb-28 pt-6 sm:px-6 lg:px-8 lg:pb-14 lg:pt-8"
          >
            {needsPhoneCheck ? (
              <Alert
                tone="warning"
                title="Vérifiez votre numéro de téléphone"
                className="mb-6"
                action={
                  <ButtonLink href={`/verify-phone?next=${encodeURIComponent(pathname)}`} size="sm" variant="outline">
                    Vérifier maintenant
                  </ButtonLink>
                }
              >
                Un code vous sera envoyé par SMS pour sécuriser votre compte.
              </Alert>
            ) : null}
            {children}
          </main>
        </div>
      </div>

      {/* Navigation basse (mobile / tablette) */}
      <nav
        aria-label={`Navigation — ${title}`}
        className="safe-bottom fixed inset-x-0 bottom-0 z-header border-t border-lineSoft bg-white/90 backdrop-blur-md lg:hidden"
      >
        <ul
          className={cx("mx-auto flex max-w-xl", scrollableBottom ? "scrollbar-none overflow-x-auto" : "")}
          style={scrollableBottom ? undefined : { display: "grid", gridTemplateColumns: `repeat(${bottomItems.length + (useMore ? 1 : 0)}, minmax(0, 1fr))` }}
        >
          {bottomItems.map((n) => {
            const isActive = n.href === active;
            const Icon = n.icon ?? Circle;
            return (
              <li key={n.href} className={scrollableBottom ? "min-w-[84px] flex-1" : undefined}>
                <Link
                  href={n.href}
                  aria-current={isActive ? "page" : undefined}
                  className={cx(
                    "relative flex min-h-[64px] flex-col items-center justify-center gap-1 px-1 pb-1.5 pt-2 text-[11px] font-semibold transition-colors duration-200",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary",
                    isActive ? "text-primaryDark" : "text-ash",
                  )}
                >
                  {isActive ? <span aria-hidden className="absolute top-0 h-[3px] w-9 rounded-b-full bg-accent" /> : null}
                  <span
                    aria-hidden
                    className={cx(
                      "grid h-8 w-14 place-items-center rounded-full transition-colors duration-200",
                      isActive ? "bg-primarySoft" : "bg-transparent",
                    )}
                  >
                    <Icon className="h-5 w-5" />
                    {n.badge ? <span className="absolute right-3 top-1.5 h-2.5 w-2.5 rounded-full bg-accent ring-2 ring-white" /> : null}
                  </span>
                  <span className="max-w-full truncate">{n.short ?? n.label}</span>
                </Link>
              </li>
            );
          })}
          {useMore ? (
            <li>
              <button
                type="button"
                onClick={() => setMoreOpen(true)}
                aria-haspopup="dialog"
                className={cx(
                  "relative flex min-h-[64px] w-full flex-col items-center justify-center gap-1 px-1 pb-1.5 pt-2 text-[11px] font-semibold transition-colors duration-200",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary",
                  moreActive ? "text-primaryDark" : "text-ash",
                )}
              >
                {moreActive ? <span aria-hidden className="absolute top-0 h-[3px] w-9 rounded-b-full bg-accent" /> : null}
                <span aria-hidden className={cx("relative grid h-8 w-14 place-items-center rounded-full", moreActive ? "bg-primarySoft" : "bg-transparent")}>
                  <Ellipsis className="h-5 w-5" />
                  {moreBadge ? <span className="absolute right-3 top-1.5 h-2.5 w-2.5 rounded-full bg-accent ring-2 ring-white" /> : null}
                </span>
                <span>Plus</span>
              </button>
            </li>
          ) : null}
        </ul>
      </nav>

      {useMore ? (
        <Modal open={moreOpen} onClose={() => setMoreOpen(false)} title="Plus" size="sm">
          <ul className="grid grid-cols-1 gap-1 pb-2">
            {moreItems.map((n) => {
              const Icon = n.icon ?? Circle;
              const isActive = n.href === active;
              return (
                <li key={n.href}>
                  <Link
                    href={n.href}
                    aria-current={isActive ? "page" : undefined}
                    className={cx(
                      "flex min-h-[48px] items-center gap-3 rounded-xl px-3 text-[15px] font-semibold transition",
                      RING,
                      isActive ? "bg-primarySoft text-primaryDark" : "text-inkSoft hover:bg-canvas hover:text-ink",
                    )}
                  >
                    <Icon aria-hidden className={cx("h-5 w-5 shrink-0", isActive ? "text-primary" : "text-ash")} />
                    {n.label}
                    {n.badge ? (
                      <span className="ml-auto rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold leading-none text-ink">
                        {n.badge > 99 ? "99+" : n.badge}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </Modal>
      ) : null}
    </div>
  );
}
