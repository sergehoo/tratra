"use client";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { BrandWordmark, cx } from "@/components/ds";
import { activeModule, activeSub, type NavEntry, type NavGroup } from "@/lib/boNavModel";
import { GROUP_ICONS } from "./boIcons";

const RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-night";

function linkClass(active: boolean, level: 2 | 3): string {
  return cx(
    "group relative flex items-center gap-2.5 rounded-lg transition duration-150",
    level === 2 ? "min-h-[40px] px-3 text-[13px] font-semibold" : "min-h-[36px] px-3 text-[12.5px] font-medium",
    RING,
    active ? "bg-primary/25 text-white" : "text-white/65 hover:bg-white/[0.06] hover:text-white",
  );
}

function ActiveBar() {
  return <span aria-hidden className="absolute -left-[0.7rem] top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-accent" />;
}

/**
 * Contenu de navigation (barre latérale de bureau ET tiroir mobile) : logo, 7 rubriques dépliables, pied.
 * Seule la zone des rubriques défile (défilement indépendant de la page).
 */
export function BoSidebar({
  nav,
  pathname,
  tab,
  collapsed,
  openGroups,
  onToggleGroup,
  onNavigate,
  footer,
  onToggleCollapse,
}: {
  nav: NavGroup[];
  pathname: string;
  tab: string | null;
  collapsed: boolean;
  openGroups: string[];
  onToggleGroup: (id: string) => void;
  onNavigate?: () => void;
  footer?: ReactNode;
  /** Absent dans le tiroir mobile (pas de mode réduit). */
  onToggleCollapse?: () => void;
}) {
  const hit = activeModule(nav, pathname);

  function renderEntry(item: NavEntry) {
    const isActive = hit?.item.id === item.id;
    const sub = isActive ? activeSub(item, tab) : null;
    return (
      <li key={item.id}>
        <Link href={item.href} onClick={onNavigate} aria-current={isActive && !item.subs.length ? "page" : undefined} className={linkClass(isActive && !sub, 2)}>
          {isActive && !sub ? <ActiveBar /> : null}
          <span className="min-w-0 truncate">{item.label}</span>
        </Link>
        {isActive && item.subs.length ? (
          <ul className="ml-3 mt-0.5 space-y-0.5 border-l border-white/10 pl-2">
            {item.subs.map((s) => {
              const on = sub?.tab === s.tab;
              return (
                <li key={s.tab}>
                  <Link href={s.href} onClick={onNavigate} aria-current={on ? "page" : undefined} className={linkClass(on, 3)}>
                    {on ? <ActiveBar /> : null}
                    <span className="min-w-0 truncate">{s.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : null}
      </li>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-night text-white">
      {/* Marque */}
      <div className={cx("flex shrink-0 items-center border-b border-white/[0.07]", collapsed ? "justify-center px-2 py-4" : "gap-3 px-5 py-5")}>
        <Link href="/backoffice" onClick={onNavigate} aria-label="Tratra — tableau de bord du Back-Office" className={cx("flex items-center gap-3 rounded-2xl", RING)}>
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white shadow-hair">
            <Image src="/tratra_logo.webp" alt="" width={28} height={28} className="h-7 w-7" />
          </span>
          {collapsed ? null : (
            <span className="flex flex-col">
              <BrandWordmark tone="night" className="text-[1.8rem]" />
              <span className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-full bg-accent/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-accent">
                <span aria-hidden className="h-1 w-1 rounded-full bg-accent" />
                Back-Office
              </span>
            </span>
          )}
        </Link>
      </div>

      {/* Rubriques : zone à défilement indépendant */}
      <nav aria-label="Navigation du Back-Office" className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4 [scrollbar-color:rgba(255,255,255,.18)_transparent] [scrollbar-width:thin]">
        <ul className="space-y-1">
          {nav.map((g) => {
            const GroupIcon = GROUP_ICONS[g.id];
            const groupActive = hit?.group.id === g.id;
            const single = g.items.length === 1;
            const soleItem = g.items[0];
            const flat = single && soleItem.subs.length === 0; // un seul module, sans onglets : la rubrique EST le lien

            if (collapsed) {
              return (
                <li key={g.id}>
                  <Link
                    href={g.href}
                    onClick={onNavigate}
                    title={g.label}
                    aria-label={g.label}
                    aria-current={groupActive ? "page" : undefined}
                    className={cx("relative grid h-11 place-items-center rounded-xl transition", RING, groupActive ? "bg-primary/25 text-accent" : "text-white/65 hover:bg-white/[0.06] hover:text-white")}
                  >
                    {groupActive ? <ActiveBar /> : null}
                    <GroupIcon aria-hidden className="h-[19px] w-[19px]" />
                  </Link>
                </li>
              );
            }

            if (flat) {
              const on = hit?.item.id === soleItem.id;
              return (
                <li key={g.id}>
                  <Link
                    href={soleItem.href}
                    onClick={onNavigate}
                    aria-current={on ? "page" : undefined}
                    className={cx("group relative flex min-h-[44px] items-center gap-3 rounded-xl px-3 text-sm font-semibold transition", RING, on ? "bg-primary/25 text-white" : "text-white/80 hover:bg-white/[0.06] hover:text-white")}
                  >
                    {on ? <ActiveBar /> : null}
                    <GroupIcon aria-hidden className={cx("h-[18px] w-[18px] shrink-0", on ? "text-accent" : "text-white/55 group-hover:text-white")} />
                    <span className="min-w-0 truncate">{g.label}</span>
                  </Link>
                </li>
              );
            }

            const open = openGroups.includes(g.id);
            return (
              <li key={g.id}>
                <button
                  type="button"
                  onClick={() => onToggleGroup(g.id)}
                  aria-expanded={open}
                  aria-controls={`bo-group-${g.id}`}
                  className={cx(
                    "group flex min-h-[44px] w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-semibold transition",
                    RING,
                    groupActive ? "text-white" : "text-white/80 hover:bg-white/[0.06] hover:text-white",
                  )}
                >
                  <GroupIcon aria-hidden className={cx("h-[18px] w-[18px] shrink-0", groupActive ? "text-accent" : "text-white/55 group-hover:text-white")} />
                  <span className="min-w-0 flex-1 truncate">{g.label}</span>
                  <ChevronDown aria-hidden className={cx("h-4 w-4 shrink-0 text-white/40 transition-transform duration-200", open && "rotate-180")} />
                </button>
                {open ? (
                  <ul id={`bo-group-${g.id}`} className="ml-[1.4rem] mt-1 space-y-0.5 border-l border-white/10 pl-2.5">
                    {single
                      ? soleItem.subs.map((s) => {
                          const on = hit?.item.id === soleItem.id && activeSub(soleItem, tab)?.tab === s.tab;
                          return (
                            <li key={s.tab}>
                              <Link href={s.href} onClick={onNavigate} aria-current={on ? "page" : undefined} className={linkClass(on, 2)}>
                                {on ? <ActiveBar /> : null}
                                <span className="min-w-0 truncate">{s.label}</span>
                              </Link>
                            </li>
                          );
                        })
                      : g.items.map(renderEntry)}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Pied : compte + réduire */}
      <div className="shrink-0 border-t border-white/[0.07] p-3">
        {footer}
        {onToggleCollapse ? (
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label={collapsed ? "Déployer la barre latérale" : "Réduire la barre latérale"}
            aria-pressed={collapsed}
            className={cx("mt-1 hidden min-h-[40px] w-full items-center gap-3 rounded-xl px-3 text-xs font-semibold text-white/55 transition hover:bg-white/[0.06] hover:text-white lg:flex", RING, collapsed && "justify-center px-0")}
          >
            <svg aria-hidden viewBox="0 0 20 20" className={cx("h-4 w-4 shrink-0 transition-transform", collapsed && "rotate-180")} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12.5 4.5 7 10l5.5 5.5" />
              <path d="M16 4v12" />
            </svg>
            {collapsed ? null : "Réduire le menu"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
