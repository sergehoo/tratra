"use client";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { CornerDownLeft, FileText, Loader2, Search } from "lucide-react";
import { cx } from "@/components/ds";
import { useBo } from "@/lib/BoProvider";
import { bo, moneyLabel, type Page } from "@/lib/bo";
import { searchEntries, searchLocal, type NavGroup } from "@/lib/boNavModel";
import { STATUS_FR } from "./ui";

interface Hit {
  key: string;
  title: string;
  subtitle?: string;
  href: string;
}

/** Enregistrements cherchables : seulement les sources dont le rôle a le droit (le serveur le revérifie à chaque appel). */
interface Source {
  id: string;
  label: string;
  permission: string;
  path: string;
  hit: (row: any, q: string) => Hit; // eslint-disable-line @typescript-eslint/no-explicit-any
  all: (q: string) => string;
}

const enc = encodeURIComponent;
const SOURCES: Source[] = [
  {
    id: "users", label: "Utilisateurs", permission: "users.view", path: "/users/",
    hit: (r) => ({ key: `u${r.id}`, title: `${r.name} #${r.id}`, subtitle: [r.phone, r.email].filter(Boolean).join(" · ") || undefined, href: `/backoffice/users/${r.id}` }),
    all: (q) => `/backoffice/users?q=${enc(q)}`,
  },
  {
    id: "kyc", label: "Dossiers KYC", permission: "kyc.review", path: "/kyc/",
    hit: (r) => ({ key: `k${r.profile_id}`, title: `${r.name} #${r.profile_id}`, subtitle: [r.state_label, r.commune].filter(Boolean).join(" · "), href: `/backoffice/kyc/${r.profile_id}` }),
    all: (q) => `/backoffice/kyc?q=${enc(q)}`,
  },
  {
    id: "bookings", label: "Réservations", permission: "bookings.view", path: "/bookings/",
    hit: (r) => ({ key: `b${r.id}`, title: `Réservation #${r.id} — ${r.service ?? "service"}`, subtitle: `${r.client} → ${r.artisan} · ${STATUS_FR[r.status] ?? r.status}`, href: `/backoffice/bookings/${r.id}` }),
    all: (q) => `/backoffice/bookings?q=${enc(q)}`,
  },
  {
    id: "payments", label: "Paiements", permission: "finance.view", path: "/finance/payments/",
    hit: (r, q) => ({ key: `p${r.id}`, title: `Paiement #${r.id} — ${moneyLabel(r.amount)}`, subtitle: `${r.client} → ${r.artisan} · ${STATUS_FR[r.status] ?? r.status}`, href: `/backoffice/finance?tab=payments&q=${enc(q)}` }),
    all: (q) => `/backoffice/finance?tab=payments&q=${enc(q)}`,
  },
  {
    id: "services", label: "Services", permission: "services.moderate", path: "/services/",
    hit: (r, q) => ({ key: `s${r.id}`, title: r.title, subtitle: [r.artisan, r.category].filter(Boolean).join(" · "), href: `/backoffice/services?q=${enc(q)}` }),
    all: (q) => `/backoffice/services?q=${enc(q)}`,
  },
  {
    id: "organizations", label: "Organisations", permission: "business.manage", path: "/business/organizations/",
    hit: (r, q) => ({ key: `o${r.id}`, title: r.name, subtitle: [r.city, r.owner].filter(Boolean).join(" · "), href: `/backoffice/business?tab=organizations&q=${enc(q)}` }),
    all: (q) => `/backoffice/business?tab=organizations&q=${enc(q)}`,
  },
  {
    id: "contracts", label: "Contrats d’engagement", permission: "engagements.view", path: "/engagements/contracts/",
    hit: (r, q) => ({ key: `c${r.id}`, title: r.title, subtitle: `${r.principal?.name} → ${r.worker?.name}`, href: `/backoffice/engagements?tab=contracts&q=${enc(q)}` }),
    all: (q) => `/backoffice/engagements?tab=contracts&q=${enc(q)}`,
  },
];

interface Result {
  state: "loading" | "ok" | "error";
  hits: Hit[];
  count: number;
}

const MIN_CHARS = 2;

/**
 * Recherche globale (Ctrl/Cmd + K) : pages du Back-Office (instantané, filtré par droits) et enregistrements
 * (comptes, dossiers, réservations, paiements…) via les API existantes — aucune donnée fictive, aucun droit contourné.
 */
export function GlobalSearch({ open, onClose, nav }: { open: boolean; onClose: () => void; nav: NavGroup[] }) {
  const router = useRouter();
  const { can } = useBo();
  const uid = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const lastFocus = useRef<HTMLElement | null>(null);
  const seq = useRef(0);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [results, setResults] = useState<Record<string, Result>>({});
  const [index, setIndex] = useState(0);

  const entries = useMemo(() => searchEntries(nav), [nav]);
  const sources = useMemo(() => SOURCES.filter((s) => can(s.permission)), [can]);
  const pages = useMemo(() => (q.trim() ? searchLocal(entries, q) : entries.filter((e) => !e.href.includes("?tab=")).slice(0, 7)), [entries, q]);

  useEffect(() => {
    if (!open) return;
    lastFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setQ("");
    setDebounced("");
    setResults({});
    setIndex(0);
    const t = setTimeout(() => inputRef.current?.focus(), 30);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      clearTimeout(t);
      document.body.style.overflow = previous;
      lastFocus.current?.focus?.();
    };
  }, [open]);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    if (!open || debounced.length < MIN_CHARS) {
      setResults({});
      return;
    }
    const mine = ++seq.current;
    setResults(Object.fromEntries(sources.map((s) => [s.id, { state: "loading", hits: [], count: 0 } as Result])));
    for (const s of sources) {
      bo.get<Page<unknown>>(`${s.path}?q=${enc(debounced)}&page_size=4`)
        .then((page) => {
          if (mine !== seq.current) return;
          setResults((r) => ({ ...r, [s.id]: { state: "ok", hits: page.results.map((row) => s.hit(row, debounced)), count: page.count } }));
        })
        .catch(() => {
          if (mine === seq.current) setResults((r) => ({ ...r, [s.id]: { state: "error", hits: [], count: 0 } }));
        });
    }
  }, [debounced, open, sources]);

  // Liste aplatie pour la navigation au clavier.
  const flat = useMemo(() => {
    const items: { key: string; href: string }[] = pages.map((p) => ({ key: `page:${p.href}`, href: p.href }));
    for (const s of sources) for (const h of results[s.id]?.hits ?? []) items.push({ key: `${s.id}:${h.key}`, href: h.href });
    return items;
  }, [pages, sources, results]);

  useEffect(() => setIndex(0), [debounced, pages.length]);
  useEffect(() => {
    document.getElementById(`${uid}-opt-${index}`)?.scrollIntoView({ block: "nearest" });
  }, [index, uid]);

  if (!open) return null;

  const go = (href: string) => {
    onClose();
    router.push(href);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setIndex((i) => Math.min(i + 1, Math.max(0, flat.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && flat[index]) {
      e.preventDefault();
      go(flat[index].href);
    }
  };

  let cursor = -1;
  const option = (href: string, body: ReactNode, key: string) => {
    cursor += 1;
    const i = cursor;
    return (
      <li key={key} role="presentation">
        <button
          type="button"
          role="option"
          id={`${uid}-opt-${i}`}
          aria-selected={i === index}
          onMouseMove={() => setIndex(i)}
          onClick={() => go(href)}
          className={cx("flex min-h-[48px] w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm transition", i === index ? "bg-primarySoft text-ink" : "text-inkSoft hover:bg-canvas")}
        >
          {body}
          {i === index ? <CornerDownLeft aria-hidden className="ml-auto h-4 w-4 shrink-0 text-primaryDark" /> : null}
        </button>
      </li>
    );
  };

  const searching = debounced.length >= MIN_CHARS;
  const anyLoading = searching && sources.some((s) => results[s.id]?.state === "loading");
  const nothing = searching && !anyLoading && flat.length === 0;

  return (
    <div className="fixed inset-0 z-modal" role="presentation">
      <div className="absolute inset-0 bg-night/60 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Recherche globale"
        onKeyDown={onKey}
        className="relative mx-auto mt-[7vh] flex max-h-[80vh] w-[min(44rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-card border border-lineSoft bg-white shadow-strong"
      >
        <div className="flex items-center gap-3 border-b border-lineSoft px-4">
          <Search aria-hidden className="h-5 w-5 shrink-0 text-ash" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            role="combobox"
            aria-expanded="true"
            aria-controls={`${uid}-list`}
            aria-activedescendant={flat.length ? `${uid}-opt-${index}` : undefined}
            aria-label="Rechercher dans le Back-Office"
            placeholder="Page, compte, téléphone, réservation, paiement…"
            className="h-14 min-w-0 flex-1 bg-transparent text-base text-ink placeholder:text-fog focus:outline-none"
          />
          {anyLoading ? <Loader2 aria-label="Recherche en cours" className="h-4 w-4 animate-spin text-ash" /> : null}
          <kbd className="hidden rounded-md border border-line bg-canvas px-1.5 py-0.5 text-[11px] font-semibold text-ash sm:block">Échap</kbd>
        </div>

        <ul id={`${uid}-list`} role="listbox" aria-label="Résultats" className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain p-2">
          {pages.length ? (
            <li role="presentation">
              <p className="px-3 pb-1 pt-2 text-[11px] font-bold uppercase tracking-[0.14em] text-ash">Pages</p>
              <ul role="presentation" className="space-y-0.5">
                {pages.map((p) =>
                  option(
                    p.href,
                    <>
                      <FileText aria-hidden className="h-4 w-4 shrink-0 text-ash" />
                      <span className="min-w-0 flex-1 truncate font-semibold text-ink">{p.label}</span>
                      <span className="hidden shrink-0 text-xs text-ash sm:block">{p.group}</span>
                    </>,
                    `page:${p.href}`,
                  ),
                )}
              </ul>
            </li>
          ) : null}

          {searching
            ? sources.map((s) => {
                const r = results[s.id];
                if (!r || (r.state === "ok" && r.hits.length === 0)) return null;
                return (
                  <li key={s.id} role="presentation">
                    <div className="flex items-center justify-between px-3 pb-1 pt-2">
                      <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-ash">{s.label}</p>
                      {r.state === "ok" && r.count > r.hits.length ? (
                        <button type="button" onClick={() => go(s.all(debounced))} className="text-xs font-semibold text-primaryDark underline underline-offset-2">
                          Voir les {r.count} résultats
                        </button>
                      ) : null}
                    </div>
                    {r.state === "loading" ? <p className="px-3 py-2 text-xs text-ash">Recherche…</p> : null}
                    {r.state === "error" ? <p role="alert" className="px-3 py-2 text-xs text-dangerInk">Recherche indisponible pour cette catégorie.</p> : null}
                    <ul role="presentation" className="space-y-0.5">
                      {r.hits.map((h) =>
                        option(
                          h.href,
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-semibold text-ink">{h.title}</span>
                            {h.subtitle ? <span className="block truncate text-xs text-ash">{h.subtitle}</span> : null}
                          </span>,
                          `${s.id}:${h.key}`,
                        ),
                      )}
                    </ul>
                  </li>
                );
              })
            : null}

          {nothing ? <li role="presentation" className="px-4 py-8 text-center text-sm text-ash">Aucun résultat pour « {debounced} ».</li> : null}
          {!searching ? (
            <li role="presentation" className="px-4 pb-3 pt-1 text-xs text-ash">
              Saisissez au moins {MIN_CHARS} caractères pour chercher un compte, un dossier, une réservation ou un paiement
              {sources.length ? "" : " (votre rôle n’ouvre aucun enregistrement : seules les pages sont cherchables)"}.
            </li>
          ) : null}
        </ul>

        <div className="flex items-center gap-4 border-t border-lineSoft bg-canvas px-4 py-2 text-[11px] font-medium text-ash">
          <span><kbd className="font-semibold">↑↓</kbd> naviguer</span>
          <span><kbd className="font-semibold">↵</kbd> ouvrir</span>
          <span className="ml-auto">Les droits de votre rôle s’appliquent à chaque recherche.</span>
        </div>
      </div>
    </div>
  );
}
