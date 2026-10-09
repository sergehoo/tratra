"use client";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
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
import { ButtonLink } from "@/components/ds/Button";
import { DURATION, EASE } from "@/components/ds/motion";
import { CONTAINER } from "@/components/ds/layout";
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

/**
 * En-tête du site public.
 * - `overlay` : transparent sur le hero, puis fond blanc flouté + ombre après 24 px.
 * - `solid` : toujours blanc (pages internes comme /search).
 */
export default function SiteHeader({ variant = "overlay" }: { variant?: "overlay" | "solid" }) {
  const { user, loading } = useAuth();
  const onSearch = usePathname() === SEARCH_ITEM.href;
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
    : "text-inkSoft hover:bg-lineSoft hover:text-ink";

  return (
    <>
      <a href="#contenu" className="skip-link">
        Aller au contenu
      </a>

      <header
        className={`${variant === "overlay" ? "fixed" : "sticky"} inset-x-0 top-0 z-header border-b transition-[background-color,box-shadow,border-color] duration-base ease-emphasized ${
          transparent ? "border-transparent bg-transparent" : "border-lineSoft bg-white/90 shadow-soft backdrop-blur-md"
        }`}
      >
        <div className={`flex h-16 items-center justify-between gap-3 lg:h-20 ${CONTAINER}`}>
          <Link href="/" className={`flex shrink-0 items-center gap-2.5 rounded-panel ${FOCUS}`}>
            <span className="grid h-10 w-10 place-items-center rounded-control bg-white shadow-hair ring-1 ring-line lg:h-11 lg:w-11">
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
              className={`font-display text-xl font-extrabold tracking-tight transition-colors duration-base lg:text-[1.35rem] ${
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
                  aria-current={onSearch ? "page" : undefined}
                  className={`inline-flex min-h-[44px] items-center gap-2 whitespace-nowrap rounded-full px-3 text-sm font-semibold transition-colors xl:px-4 ${
                    onSearch ? (transparent ? "bg-white/15 text-white" : "bg-primarySoft text-primaryDark") : linkTone
                  } ${FOCUS}`}
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
                  className={`h-11 w-44 rounded-full ${transparent ? "bg-white/10" : "bg-lineSoft"}`}
                />
              ) : space ? (
                <ButtonLink href={space} variant="primary" leftIcon={<LayoutDashboard aria-hidden className="h-4 w-4" />}>
                  Mon espace
                </ButtonLink>
              ) : (
                <>
                  <Link
                    href="/login"
                    className={`inline-flex min-h-[44px] items-center gap-2 whitespace-nowrap rounded-full px-3 text-sm font-semibold transition-colors xl:px-4 ${linkTone} ${FOCUS}`}
                  >
                    <LogIn aria-hidden className="h-4 w-4" />
                    Connexion
                  </Link>
                  <ButtonLink
                    href={registerHref("handyman")}
                    variant="accent"
                    leftIcon={<HardHat aria-hidden className="h-4 w-4" />}
                  >
                    Devenir artisan
                  </ButtonLink>
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
                  : "bg-lineSoft text-ink hover:bg-line"
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
                transition={{ duration: DURATION.base }}
              />
              <m.div
                key="menu-panel"
                ref={panelRef}
                className="fixed inset-x-0 top-16 z-40 max-h-[calc(100dvh-4rem)] overflow-y-auto rounded-b-sheet bg-white px-4 pb-6 pt-3 shadow-strong sm:px-6"
                initial={{ opacity: 0, y: -16 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                transition={{ duration: DURATION.base, ease: EASE }}
              >
                <nav aria-label="Navigation mobile">
                  <ul className="space-y-1">
                    {[...NAV, SEARCH_ITEM].map((item) => (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          onClick={() => close()}
                          aria-current={onSearch && item.href === SEARCH_ITEM.href ? "page" : undefined}
                          className={`group flex min-h-[52px] items-center gap-3 rounded-panel px-2 text-base font-semibold text-ink transition-colors hover:bg-canvas ${FOCUS}`}
                        >
                          <span className="grid h-10 w-10 place-items-center rounded-control bg-primarySoft text-primaryDark transition-colors group-hover:bg-accent group-hover:text-ink">
                            <item.icon aria-hidden className="h-5 w-5" />
                          </span>
                          {item.label}
                          <ChevronRight aria-hidden className="ml-auto h-5 w-5 text-fog" />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </nav>

                <div className="mt-4 grid gap-3 border-t border-lineSoft pt-5">
                  {loading ? (
                    <span aria-hidden className="h-12 w-full rounded-full bg-lineSoft" />
                  ) : space ? (
                    <ButtonLink
                      href={space}
                      size="lg"
                      block
                      onClick={() => close()}
                      leftIcon={<LayoutDashboard aria-hidden className="h-5 w-5" />}
                    >
                      Mon espace
                    </ButtonLink>
                  ) : (
                    <>
                      <ButtonLink
                        href={registerHref("handyman")}
                        variant="accent"
                        size="lg"
                        block
                        onClick={() => close()}
                        leftIcon={<HardHat aria-hidden className="h-5 w-5" />}
                      >
                        Devenir artisan
                      </ButtonLink>
                      <ButtonLink
                        href="/login"
                        variant="outline"
                        size="lg"
                        block
                        onClick={() => close()}
                        leftIcon={<LogIn aria-hidden className="h-5 w-5" />}
                      >
                        Connexion
                      </ButtonLink>
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
