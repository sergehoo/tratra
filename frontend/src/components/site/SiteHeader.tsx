"use client";
import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, m } from "framer-motion";
import {
  Building2,
  ChevronRight,
  HardHat,
  LayoutDashboard,
  LayoutGrid,
  LogIn,
  Menu,
  Search,
  Siren,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { registerHref, spaceHref } from "@/lib/links";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** Ancres des sections de la landing + recherche (routes réelles). */
const NAV: NavItem[] = [
  { href: "/#metiers", label: "Métiers", icon: LayoutGrid },
  { href: "/#urgences", label: "Urgences", icon: Siren },
  { href: "/#artisans", label: "Artisans", icon: Users },
  { href: "/#entreprises", label: "Entreprises", icon: Building2 },
];
const SEARCH_ITEM: NavItem = { href: "/search", label: "Rechercher", icon: Search };

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

/**
 * En-tête du site public.
 * - `overlay` : transparent sur le hero, puis fond blanc flouté + ombre après 24 px.
 * - `solid` : toujours blanc (pages internes comme /search).
 */
export default function SiteHeader({ variant = "overlay" }: { variant?: "overlay" | "solid" }) {
  const { user, loading } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const transparent = variant === "overlay" && !scrolled && !open;
  const space = spaceHref(user);

  // Passage transparent -> blanc au défilement (rAF, écouteur passif).
  useEffect(() => {
    if (variant !== "overlay") return;
    let raf = 0;
    const update = () => {
      raf = 0;
      setScrolled(window.scrollY > 24);
    };
    const onScroll = () => {
      if (!raf) raf = window.requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [variant]);

  const close = useCallback((restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) toggleRef.current?.focus();
  }, []);

  // Menu mobile ouvert : Échap, clic extérieur, verrouillage du défilement,
  // fermeture automatique au passage en affichage bureau, focus dans le panneau.
  // Piège de focus : Tab / Maj+Tab bouclent entre le bouton bascule (pour
  // pouvoir refermer) et les liens du panneau, jamais sous le voile.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close(true);
        return;
      }
      const panel = panelRef.current;
      const toggle = toggleRef.current;
      if (e.key !== "Tab" || !panel || !toggle) return;
      const nodes = Array.from(panel.querySelectorAll<HTMLElement>("a[href], button:not([disabled])"));
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (!first || !last) return;
      const active = document.activeElement;
      if (!e.shiftKey && active === last) {
        e.preventDefault();
        toggle.focus();
      } else if (e.shiftKey && active === toggle) {
        e.preventDefault();
        last.focus();
      } else if (active !== toggle && !(active instanceof Node && panel.contains(active))) {
        // Focus hors du cycle (ex. clic sur une zone non focalisable) : on y revient.
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      }
      // Les autres cas (bascule -> 1er lien, 1er lien -> bascule) suivent
      // l'ordre du DOM : #menu-mobile vient juste après le bouton bascule.
    };
    const onPointer = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target) return;
      if (panelRef.current?.contains(target) || toggleRef.current?.contains(target)) return;
      close();
    };
    const mq = window.matchMedia("(min-width: 1024px)");
    const onMq = (e: MediaQueryListEvent) => {
      if (e.matches) close();
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    mq.addEventListener("change", onMq);
    panelRef.current?.querySelector<HTMLElement>("a[href], button")?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
      mq.removeEventListener("change", onMq);
    };
  }, [open, close]);

  const linkTone = transparent
    ? "text-white/85 hover:bg-white/10 hover:text-white"
    : "text-slate-600 hover:bg-slate-100 hover:text-ink";

  return (
    <>
      <a href="#contenu" className="skip-link">
        Aller au contenu
      </a>

      <header
        className={`${variant === "overlay" ? "fixed" : "sticky"} inset-x-0 top-0 z-50 transition-[background-color,box-shadow] duration-300 ${
          transparent
            ? "bg-transparent"
            : "bg-white/90 shadow-[0_1px_0_rgba(15,23,42,0.06),0_12px_32px_-16px_rgba(15,23,42,0.22)] backdrop-blur-md"
        }`}
      >
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:h-20">
          <Link href="/" className={`flex shrink-0 items-center gap-2.5 rounded-2xl ${FOCUS}`}>
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-white shadow-sm ring-1 ring-black/5 lg:h-11 lg:w-11">
              <Image
                src="/tratra_logo.webp"
                alt="Tratra"
                width={30}
                height={30}
                priority
                className="h-[30px] w-[30px]"
              />
            </span>
            <span
              aria-hidden
              className={`font-display text-xl font-extrabold tracking-tight transition-colors duration-300 lg:text-[1.35rem] ${
                transparent ? "text-white" : "text-ink"
              }`}
            >
              Tra<span className={transparent ? "text-accent" : "text-primary"}>tra</span>
            </span>
          </Link>

          <nav aria-label="Navigation principale" className="hidden lg:block">
            <ul className="flex items-center gap-0.5 xl:gap-1">
              {NAV.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={`inline-flex min-h-[44px] items-center whitespace-nowrap rounded-full px-3 text-sm font-semibold transition-colors xl:px-4 ${linkTone} ${FOCUS}`}
                  >
                    {item.label}
                  </Link>
                </li>
              ))}
              <li>
                <Link
                  href={SEARCH_ITEM.href}
                  className={`inline-flex min-h-[44px] items-center gap-2 whitespace-nowrap rounded-full px-3 text-sm font-semibold transition-colors xl:px-4 ${linkTone} ${FOCUS}`}
                >
                  <Search aria-hidden className="h-4 w-4" />
                  {SEARCH_ITEM.label}
                </Link>
              </li>
            </ul>
          </nav>

          <div className="flex items-center gap-2">
            <div className="hidden items-center gap-2 sm:flex">
              {loading ? (
                <span
                  aria-hidden
                  className={`h-11 w-44 rounded-full ${transparent ? "bg-white/10" : "bg-slate-100"}`}
                />
              ) : space ? (
                <Link
                  href={space}
                  className={`inline-flex min-h-[44px] items-center gap-2 whitespace-nowrap rounded-full bg-primaryDark px-5 text-sm font-semibold text-white shadow-glow transition hover:-translate-y-0.5 hover:bg-[#185736] ${FOCUS} focus-visible:ring-offset-2`}
                >
                  <LayoutDashboard aria-hidden className="h-4 w-4" />
                  Mon espace
                </Link>
              ) : (
                <>
                  <Link
                    href="/login"
                    className={`inline-flex min-h-[44px] items-center gap-2 whitespace-nowrap rounded-full px-3 text-sm font-semibold transition-colors xl:px-4 ${linkTone} ${FOCUS}`}
                  >
                    <LogIn aria-hidden className="h-4 w-4" />
                    Connexion
                  </Link>
                  <Link
                    href={registerHref("handyman")}
                    className={`inline-flex min-h-[44px] items-center gap-2 whitespace-nowrap rounded-full bg-accent px-5 text-sm font-bold text-ink shadow-[0_10px_28px_-10px_rgba(246,201,14,.7)] transition hover:-translate-y-0.5 hover:bg-[#ffd42e] ${FOCUS} focus-visible:ring-offset-2 ${
                      transparent
                        ? "focus-visible:ring-white focus-visible:ring-offset-night"
                        : "focus-visible:ring-night"
                    }`}
                  >
                    <HardHat aria-hidden className="h-4 w-4" />
                    Devenir artisan
                  </Link>
                </>
              )}
            </div>

            <button
              ref={toggleRef}
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              aria-controls="menu-mobile"
              aria-label={open ? "Fermer le menu" : "Ouvrir le menu"}
              className={`grid h-11 w-11 place-items-center rounded-full transition-colors lg:hidden ${FOCUS} ${
                transparent
                  ? "bg-white/10 text-white ring-1 ring-inset ring-white/20 hover:bg-white/20"
                  : "bg-slate-100 text-ink hover:bg-slate-200"
              }`}
            >
              {open ? <X aria-hidden className="h-5 w-5" /> : <Menu aria-hidden className="h-5 w-5" />}
            </button>
          </div>
        </div>
      </header>

      {/* Hors du <header> : son backdrop-filter créerait sinon un bloc conteneur
          pour les éléments `fixed` (panneau limité à la hauteur de l'en-tête). */}
      <div id="menu-mobile" className="lg:hidden">
        <AnimatePresence>
          {open ? (
            <>
              <m.div
                key="menu-backdrop"
                aria-hidden
                className="fixed inset-0 top-16 z-40 bg-night/55 backdrop-blur-[2px]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
              />
              <m.div
                key="menu-panel"
                ref={panelRef}
                className="fixed inset-x-0 top-16 z-40 max-h-[calc(100dvh-4rem)] overflow-y-auto rounded-b-[1.75rem] bg-white px-4 pb-6 pt-3 shadow-strong sm:px-6"
                initial={{ opacity: 0, y: -16 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                transition={{ duration: 0.28, ease: EASE }}
              >
                <nav aria-label="Navigation mobile">
                  <ul className="space-y-1">
                    {[...NAV, SEARCH_ITEM].map((item) => (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          onClick={() => close()}
                          className={`group flex min-h-[52px] items-center gap-3 rounded-2xl px-2 text-base font-semibold text-ink transition-colors hover:bg-slate-50 ${FOCUS}`}
                        >
                          <span className="grid h-10 w-10 place-items-center rounded-xl bg-primarySoft text-primaryDark transition-colors group-hover:bg-accent group-hover:text-ink">
                            <item.icon aria-hidden className="h-5 w-5" />
                          </span>
                          {item.label}
                          <ChevronRight aria-hidden className="ml-auto h-5 w-5 text-slate-300" />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </nav>

                <div className="mt-4 grid gap-3 border-t border-slate-100 pt-5">
                  {loading ? (
                    <span aria-hidden className="h-12 w-full rounded-full bg-slate-100" />
                  ) : space ? (
                    <Link
                      href={space}
                      onClick={() => close()}
                      className={`inline-flex min-h-[52px] items-center justify-center gap-2 rounded-full bg-primaryDark px-5 font-semibold text-white ${FOCUS} focus-visible:ring-offset-2`}
                    >
                      <LayoutDashboard aria-hidden className="h-5 w-5" />
                      Mon espace
                    </Link>
                  ) : (
                    <>
                      <Link
                        href={registerHref("handyman")}
                        onClick={() => close()}
                        className="inline-flex min-h-[52px] items-center justify-center gap-2 rounded-full bg-accent px-5 font-bold text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-night focus-visible:ring-offset-2"
                      >
                        <HardHat aria-hidden className="h-5 w-5" />
                        Devenir artisan
                      </Link>
                      <Link
                        href="/login"
                        onClick={() => close()}
                        className={`inline-flex min-h-[52px] items-center justify-center gap-2 rounded-full border border-slate-200 px-5 font-semibold text-ink hover:border-primary/50 hover:text-primaryDark ${FOCUS}`}
                      >
                        <LogIn aria-hidden className="h-5 w-5" />
                        Connexion
                      </Link>
                    </>
                  )}
                </div>
              </m.div>
            </>
          ) : null}
        </AnimatePresence>
      </div>
    </>
  );
}
