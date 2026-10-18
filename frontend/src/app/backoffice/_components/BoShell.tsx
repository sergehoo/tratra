"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Globe, Home, LogOut, Menu, Search, ShieldCheck, X } from "lucide-react";
import { Avatar, Badge, cx } from "@/components/ds";
import { useAuth } from "@/lib/auth";
import { breadcrumb, buildNav, activeModule } from "@/lib/boNavModel";
import type { BoMe } from "@/lib/bo";
import { BoSidebar } from "./BoSidebar";
import { GlobalSearch } from "./GlobalSearch";
import { TratraAI } from "./assistant/TratraAI";
import { ROLE_LABEL } from "./boIcons";
import { BoCrumbProvider, useCrumbLabel } from "./crumbs";

const STORE = "tratra.bo.nav";
const RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";

interface Saved {
  collapsed: boolean;
  open: string[];
}

function loadSaved(): Saved {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORE) ?? "{}") as Partial<Saved>;
    return { collapsed: raw.collapsed === true, open: Array.isArray(raw.open) ? raw.open.filter((x): x is string => typeof x === "string") : [] };
  } catch {
    return { collapsed: false, open: [] };
  }
}

function persist(state: Saved) {
  try {
    window.localStorage.setItem(STORE, JSON.stringify(state));
  } catch {
    /* stockage indisponible (navigation privée) : la préférence n'est simplement pas gardée */
  }
}

function UserMenu({ me }: { me: BoMe }) {
  const { logout } = useAuth();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    const onPointer = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  const roles = me.roles.map((r) => ROLE_LABEL[r] ?? r);
  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`Menu du compte de ${me.user.name}`}
        className={cx("flex min-h-[44px] items-center gap-2.5 rounded-full border border-line bg-white py-1 pl-1 pr-2.5 transition hover:border-primary/40 sm:pr-3.5", RING)}
      >
        <Avatar name={me.user.name} size={34} />
        <span className="hidden min-w-0 text-left lg:block">
          <span className="block max-w-[11rem] truncate text-sm font-semibold leading-tight text-ink">{me.user.name}</span>
          <span className="block max-w-[11rem] truncate text-[11px] font-medium leading-tight text-ash">{roles.join(" · ") || "Personnel"}</span>
        </span>
        <ChevronDown aria-hidden className={cx("h-4 w-4 text-ash transition-transform duration-200", open && "rotate-180")} />
      </button>
      {open ? (
        <div role="menu" className="absolute right-0 top-full z-overlay mt-2 w-72 origin-top-right animate-scaleIn rounded-panel border border-lineSoft bg-white p-2 shadow-strong">
          <div className="flex items-center gap-3 px-3 py-3">
            <Avatar name={me.user.name} size={44} />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-ink">{me.user.name}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {roles.map((r) => <Badge key={r} tone="primary">{r}</Badge>)}
              </div>
            </div>
          </div>
          {me.mfa.required ? (
            <p className="mx-3 mb-2 flex items-center gap-2 rounded-xl bg-successSoft px-3 py-2 text-xs font-semibold text-successInk">
              <ShieldCheck aria-hidden className="h-4 w-4" />
              Double authentification vérifiée
            </p>
          ) : (
            <p className="mx-3 mb-2 rounded-xl bg-warningSoft px-3 py-2 text-xs font-semibold text-warningInk">Double authentification non exigée sur cet environnement.</p>
          )}
          <div className="my-1 border-t border-lineSoft" />
          {[
            { href: "/dashboard", label: "Mon espace", icon: Home },
            { href: "/", label: "Voir le site", icon: Globe },
          ].map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} role="menuitem" onClick={() => setOpen(false)} className={cx("flex min-h-[44px] items-center gap-3 rounded-xl px-3 text-sm font-medium text-inkSoft transition hover:bg-canvas hover:text-ink", RING)}>
              <Icon aria-hidden className="h-4 w-4" />
              {label}
            </Link>
          ))}
          <button type="button" role="menuitem" onClick={() => void logout()} className={cx("flex min-h-[44px] w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium text-dangerInk transition hover:bg-dangerSoft", RING)}>
            <LogOut aria-hidden className="h-4 w-4" />
            Déconnexion
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Fil d'Ariane : `Back-Office › Rubrique › Module › onglet | fiche`. Sur mobile, seul le dernier maillon reste visible (le titre de la page prend le relais). */
function Breadcrumbs({ nav }: { nav: ReturnType<typeof buildNav> }) {
  const pathname = usePathname();
  const tab = useSearchParams().get("tab");
  const detail = useCrumbLabel();
  const crumbs = useMemo(() => breadcrumb(nav, pathname, tab, detail), [nav, pathname, tab, detail]);
  return (
    <nav aria-label="Fil d’Ariane" className="min-w-0">
      <ol className="flex min-w-0 items-center gap-1 text-sm">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          // Mobile : dernier maillon seulement ; tablette : deux derniers ; grand écran : tous. Seul le dernier maillon se tronque.
          const visibility = last ? "" : i === crumbs.length - 2 ? "hidden md:flex" : "hidden xl:flex";
          return (
            <li key={`${i}-${c.label}`} className={cx("items-center gap-1", last ? "flex min-w-0" : "shrink-0", visibility)}>
              {i > 0 ? <ChevronRight aria-hidden className={cx("h-3.5 w-3.5 shrink-0 text-fog", last && "hidden md:block")} /> : null}
              {c.href && !last ? (
                <Link href={c.href} className={cx("whitespace-nowrap rounded font-medium text-ash hover:text-ink", RING)}>{c.label}</Link>
              ) : (
                <span aria-current={last ? "page" : undefined} className={cx(last ? "truncate font-bold text-ink" : "whitespace-nowrap font-medium text-ash")}>{c.label}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/**
 * Coque du Back-Office : barre latérale sombre à 7 rubriques dépliables (rétractable, défilement indépendant), barre supérieure
 * (fil d'Ariane, recherche globale Ctrl/Cmd+K, compte), tiroir de navigation en mobile. Les modules affichés sont ceux que le serveur
 * autorise pour le rôle ; les routes existantes sont inchangées.
 */
export function BoShell({ me, children }: { me: BoMe; children: ReactNode }) {
  const nav = useMemo(() => buildNav(me.modules), [me.modules]);
  const pathname = usePathname();
  const tab = useSearchParams().get("tab");
  const hit = activeModule(nav, pathname);
  const activeGroup = hit?.group.id;

  const [collapsed, setCollapsed] = useState(false);
  const [open, setOpen] = useState<string[]>([]);
  const [drawer, setDrawer] = useState(false);
  const [searching, setSearching] = useState(false);
  const loaded = useRef(false);

  // Préférences (réduit / rubriques ouvertes) : lues après le montage, jamais pendant le rendu serveur.
  useEffect(() => {
    const saved = loadSaved();
    setCollapsed(saved.collapsed);
    setOpen(saved.open);
    loaded.current = true;
  }, []);
  useEffect(() => {
    if (loaded.current) persist({ collapsed, open });
  }, [collapsed, open]);

  // La rubrique de la page courante est toujours dépliée.
  useEffect(() => {
    if (activeGroup) setOpen((o) => (o.includes(activeGroup) ? o : [...o, activeGroup]));
  }, [activeGroup]);

  useEffect(() => setDrawer(false), [pathname]);

  // Tiroir mobile : Échap, défilement de la page verrouillé.
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [drawer]);

  // Ctrl/Cmd + K ouvre la recherche globale ; « / » aussi hors d'un champ de saisie.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearching(true);
      } else if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setSearching(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const toggleGroup = useCallback((id: string) => setOpen((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id])), []);

  const sidebar = (mobile: boolean) => (
    <BoSidebar
      nav={nav}
      pathname={pathname}
      tab={tab}
      collapsed={!mobile && collapsed}
      openGroups={open}
      onToggleGroup={toggleGroup}
      onNavigate={mobile ? () => setDrawer(false) : undefined}
      onToggleCollapse={mobile ? undefined : () => setCollapsed((v) => !v)}
      footer={
        collapsed && !mobile ? null : (
          <p className="mb-1 px-3 text-[11px] leading-snug text-white/45">
            Droits appliqués par le serveur ·{" "}
            <Link href="/dashboard" onClick={() => setDrawer(false)} className="font-semibold text-white/70 underline underline-offset-2 hover:text-white">Mon espace</Link>
          </p>
        )
      }
    />
  );

  return (
    <BoCrumbProvider>
      <div className="min-h-screen bg-canvas text-ink">
        <a href="#contenu" className="skip-link">Aller au contenu</a>

        {/* Barre latérale (bureau) : fixe, avec son propre défilement */}
        <aside className={cx("fixed inset-y-0 left-0 z-header hidden border-r border-black/20 transition-[width] duration-200 ease-standard lg:block", collapsed ? "w-[76px]" : "w-72")}>
          {sidebar(false)}
        </aside>

        {/* Tiroir (mobile / tablette) */}
        {drawer ? (
          <div className="fixed inset-0 z-overlay lg:hidden" role="presentation">
            <div className="absolute inset-0 bg-night/60 backdrop-blur-sm" onClick={() => setDrawer(false)} aria-hidden />
            <div role="dialog" aria-modal="true" aria-label="Navigation du Back-Office" className="absolute inset-y-0 left-0 flex w-[min(20rem,88vw)] animate-slideInLeft flex-col shadow-strong">
              <button type="button" onClick={() => setDrawer(false)} aria-label="Fermer le menu" className={cx("absolute right-3 top-4 z-10 grid h-10 w-10 place-items-center rounded-full text-white/70 hover:bg-white/10 hover:text-white", RING)}>
                <X aria-hidden className="h-5 w-5" />
              </button>
              {sidebar(true)}
            </div>
          </div>
        ) : null}

        <div className={cx("transition-[padding] duration-200 ease-standard", collapsed ? "lg:pl-[76px]" : "lg:pl-72")}>
          {/* Barre supérieure */}
          <header className="sticky top-0 z-header border-b border-lineSoft bg-white/90 backdrop-blur">
            <div className="flex min-h-[64px] items-center gap-3 px-4 sm:px-6 lg:px-8">
              <button type="button" onClick={() => setDrawer(true)} aria-label="Ouvrir le menu" aria-expanded={drawer} className={cx("grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-line text-inkSoft hover:bg-canvas lg:hidden", RING)}>
                <Menu aria-hidden className="h-5 w-5" />
              </button>
              <div className="min-w-0 flex-1"><Breadcrumbs nav={nav} /></div>
              <button
                type="button"
                onClick={() => setSearching(true)}
                aria-label="Recherche globale"
                className={cx("flex h-11 shrink-0 items-center gap-2.5 rounded-full border border-line bg-canvas px-3.5 text-sm text-ash transition hover:border-primary/40 hover:bg-white lg:w-72 xl:w-80", RING)}
              >
                <Search aria-hidden className="h-4 w-4" />
                <span className="hidden min-w-0 flex-1 truncate text-left lg:block">Rechercher…</span>
                <kbd className="hidden rounded-md border border-line bg-white px-1.5 py-0.5 text-[11px] font-semibold text-ash lg:block">Ctrl K</kbd>
              </button>
              <UserMenu me={me} />
            </div>
          </header>

          <main id="contenu" tabIndex={-1} className="mx-auto w-full max-w-[1680px] px-4 py-6 focus:outline-none sm:px-6 lg:px-8 lg:py-8">
            {children}
          </main>
        </div>

        <GlobalSearch open={searching} onClose={() => setSearching(false)} nav={nav} />
        {/* Tratra AI : bouton flottant + panneau persistant ; absent sans le droit « assistant.use » (chaque outil est de toute façon filtré par le serveur). */}
        {me.permissions.includes("assistant.use") ? <TratraAI /> : null}
      </div>
    </BoCrumbProvider>
  );
}
