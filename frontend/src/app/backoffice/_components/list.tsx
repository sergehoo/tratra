"use client";
import Link from "next/link";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowDown, ArrowUp, ArrowUpDown, Download, Ellipsis, ListFilter, Loader2, RefreshCw, RotateCcw, type LucideIcon } from "lucide-react";
import { Alert, Button, Card, EmptyState, Modal, SkeletonList, SkeletonTable, Tabs, cx, type Column } from "@/components/ds";
import { MIN_REASON, boError, fieldErrors } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { apiFetch } from "@/lib/api";
import type { useBoList } from "@/lib/useBoList";

const RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";

// ── Indicateurs ──────────────────────────────────────────────────────────────────────────────────────────────────────

/** Indicateur chiffré : la valeur ne se coupe jamais sur deux lignes (taille fluide), libellé et aide en dessous. */
export function Kpi({ label, value, hint, icon, tone = "primary", href }: { label: ReactNode; value: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: "primary" | "accent" | "night" | "danger"; href?: string }) {
  const tile = { primary: "bg-primarySoft text-primary", accent: "bg-accentSoft text-accentDark", night: "bg-night text-accent", danger: "bg-dangerSoft text-danger" }[tone];
  const body = (
    <Card padding="md" radius="card" className={cx("flex h-full items-start gap-4 !p-5", href && "transition hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-strong")}>
      {icon ? <span aria-hidden className={cx("grid h-11 w-11 shrink-0 place-items-center rounded-2xl", tile)}>{icon}</span> : null}
      <div className="min-w-0 flex-1">
        <p className="whitespace-nowrap font-display font-extrabold leading-none tracking-tight text-ink tabular-nums [font-size:clamp(1.2rem,1.7vw,1.7rem)]">{value}</p>
        <p className="mt-2 text-sm font-semibold text-inkSoft">{label}</p>
        {hint ? <p className="mt-0.5 text-xs leading-snug text-ash">{hint}</p> : null}
      </div>
    </Card>
  );
  return href ? <Link href={href} className={cx("block rounded-card", RING)}>{body}</Link> : body;
}

export function KpiGrid({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={cx("grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4", className)}>{children}</div>;
}

// ── Export CSV (jeux de données existants : droits et audit appliqués par le serveur) ─────────────────────────────────

/** Jeu de données → droit exigé en plus de `analytics.view` (miroir de `backoffice/api_system.py::EXPORTS`, le serveur refuse sinon). */
export const EXPORT_NEEDS: Record<string, string> = {
  users: "users.view", bookings: "bookings.view", payments: "finance.view", reviews: "reviews.moderate", audit: "security.manage",
  engagements: "engagements.view", engagement_installments: "engagements.view",
};

/**
 * Bouton « Exporter » : visible seulement si le rôle a le droit d'export ET celui du jeu de données ; le serveur revérifie, journalise le
 * téléchargement et n'exporte jamais de nom, de contact ni de commentaire. La période (`from`/`to`) de la page est transmise.
 */
export function ExportButton({ dataset, from, to }: { dataset: keyof typeof EXPORT_NEEDS; from?: string; to?: string }) {
  const { can } = useBo();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!can("analytics.view") || !can(EXPORT_NEEDS[dataset])) return null;

  async function download() {
    setBusy(true);
    setError("");
    try {
      const qs = new URLSearchParams();
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      const query = qs.toString();
      const res = await apiFetch(`/backoffice/analytics/export/${dataset}/${query ? `?${query}` : ""}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `tratra-${dataset}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error && e.message === "403" ? "Droits insuffisants pour cet export." : "L’export n’a pas pu être téléchargé.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button size="sm" variant="outline" loading={busy} leftIcon={<Download aria-hidden className="h-4 w-4" />} onClick={() => void download()} title="Export CSV de la période — sans nom, contact ni commentaire ; le téléchargement est journalisé.">
        Exporter
      </Button>
      {error ? <span role="alert" className="text-xs font-medium text-dangerInk">{error}</span> : null}
    </>
  );
}

// ── Filtre par statut avec compteurs réels ────────────────────────────────────────────────────────────────────────────

/**
 * Pastilles de statut (« Tous », « À examiner »…) avec le nombre réel d'éléments de chaque état. Un compteur inconnu (droit refusé,
 * requête en échec) n'est pas affiché plutôt que montré à 0.
 */
export function StatusChips({ items, value, onChange, counts, label = "Filtrer par statut" }: {
  items: [value: string, label: string][];
  value: string;
  onChange: (v: string) => void;
  counts?: Record<string, number | null>;
  label?: string;
}) {
  const id = (v: string) => (v === "" ? "_all" : v);
  return (
    <Tabs
      ariaLabel={label}
      idPrefix="status"
      className="mb-4"
      value={id(value)}
      onChange={(t) => onChange(items.find(([v]) => id(v) === t)?.[0] ?? "")}
      items={items.map(([v, l]) => ({ id: id(v), label: l, count: counts && typeof counts[id(v)] === "number" ? (counts[id(v)] as number) : undefined }))}
    />
  );
}

// ── Barre de filtres ─────────────────────────────────────────────────────────────────────────────────────────────────

/**
 * Barre de filtres d'une liste : recherche toujours visible, filtres métier (repliés derrière « Filtres » en mobile),
 * réinitialisation, actualisation et actions de page (export, création…).
 */
export function FilterBar({
  search,
  children,
  activeCount = 0,
  onReset,
  onRefresh,
  refreshing,
  actions,
}: {
  search?: ReactNode;
  children?: ReactNode;
  activeCount?: number;
  onReset?: () => void;
  onRefresh?: () => void;
  refreshing?: boolean;
  actions?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <section aria-label="Recherche et filtres" className="mb-4 rounded-card border border-lineSoft bg-white p-3 shadow-soft sm:p-4">
      <div className="flex flex-wrap items-end gap-2.5">
        {search ? <div className="min-w-0 flex-1 basis-56">{search}</div> : null}
        {children ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls={panel}
            className={cx("inline-flex min-h-[44px] items-center gap-2 rounded-full border border-line bg-white px-4 text-sm font-semibold text-inkSoft transition hover:border-primary/40 md:hidden", RING)}
          >
            <ListFilter aria-hidden className="h-4 w-4" />
            Filtres
            {activeCount ? <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold leading-none text-ink">{activeCount}</span> : null}
          </button>
        ) : null}
        <div className="flex items-center gap-2">
          {onReset && activeCount ? (
            <Button size="sm" variant="ghost" onClick={onReset} leftIcon={<RotateCcw aria-hidden className="h-4 w-4" />}>
              <span className="hidden sm:inline">Réinitialiser</span>
              <span className="sm:hidden">Effacer</span>
            </Button>
          ) : null}
          {onRefresh ? (
            <Button size="sm" variant="outline" onClick={onRefresh} disabled={refreshing} aria-label="Actualiser la liste" leftIcon={<RefreshCw aria-hidden className={cx("h-4 w-4", refreshing && "animate-spin")} />}>
              <span className="hidden sm:inline">Actualiser</span>
            </Button>
          ) : null}
          {actions}
        </div>
      </div>
      {children ? (
        <div id={panel} className={cx("mt-3 flex-wrap items-end gap-3 border-t border-lineSoft pt-3 md:flex", open ? "flex" : "hidden")}>
          {children}
        </div>
      ) : null}
    </section>
  );
}

// ── Menu d'actions d'une ligne ───────────────────────────────────────────────────────────────────────────────────────

export interface RowAction {
  label: string;
  icon?: LucideIcon;
  href?: string;
  onClick?: () => void;
  tone?: "default" | "danger";
  disabled?: boolean;
  hidden?: boolean;
}

/** Menu « ⋯ » d'une ligne : rendu dans un portail (jamais rogné par le défilement horizontal du tableau), clavier et Échap gérés. */
export function RowMenu({ actions, label }: { actions: RowAction[]; label: string }) {
  const visible = actions.filter((a) => !a.hidden);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; right: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
        button.current?.focus();
      }
    };
    const onPointer = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!menu.current?.contains(t) && !button.current?.contains(t)) close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open, close]);

  useEffect(() => {
    if (open) menu.current?.querySelector<HTMLElement>("[role=menuitem]:not([disabled])")?.focus();
  }, [open]);

  if (!visible.length) return null;

  function toggle() {
    if (open) return close();
    const rect = button.current?.getBoundingClientRect();
    if (!rect) return;
    const needs = visible.length * 44 + 16;
    const up = rect.bottom + needs > window.innerHeight - 8 && rect.top > needs;
    setPos(up ? { bottom: window.innerHeight - rect.top + 4, right: window.innerWidth - rect.right } : { top: rect.bottom + 4, right: window.innerWidth - rect.right });
    setOpen(true);
  }

  function onMenuKey(e: ReactKeyboardEvent) {
    const items = Array.from(menu.current?.querySelectorAll<HTMLElement>("[role=menuitem]:not([disabled])") ?? []);
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(i + 1) % items.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(i - 1 + items.length) % items.length]?.focus();
    }
  }

  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={toggle}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Actions : ${label}`}
        className={cx("grid h-10 w-10 place-items-center rounded-full text-ash transition hover:bg-lineSoft hover:text-ink", RING)}
      >
        <Ellipsis aria-hidden className="h-5 w-5" />
      </button>
      {open && pos
        ? createPortal(
            <div
              ref={menu}
              role="menu"
              aria-label={`Actions : ${label}`}
              onKeyDown={onMenuKey}
              style={{ position: "fixed", top: pos.top, bottom: pos.bottom, right: pos.right }}
              className="z-overlay min-w-[13rem] animate-scaleIn rounded-panel border border-lineSoft bg-white p-1.5 shadow-strong"
            >
              {visible.map((a) => {
                const Icon = a.icon;
                const cls = cx(
                  "flex min-h-[44px] w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
                  a.tone === "danger" ? "text-dangerInk hover:bg-dangerSoft" : "text-inkSoft hover:bg-canvas hover:text-ink",
                  RING,
                );
                const inner = (
                  <>
                    {Icon ? <Icon aria-hidden className="h-4 w-4 shrink-0" /> : null}
                    <span className="min-w-0 flex-1">{a.label}</span>
                  </>
                );
                return a.href && !a.disabled ? (
                  <Link key={a.label} href={a.href} role="menuitem" onClick={close} className={cls}>{inner}</Link>
                ) : (
                  <button
                    key={a.label}
                    type="button"
                    role="menuitem"
                    disabled={a.disabled}
                    onClick={() => {
                      close();
                      a.onClick?.();
                    }}
                    className={cls}
                  >
                    {inner}
                  </button>
                );
              })}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

// ── Actions groupées ─────────────────────────────────────────────────────────────────────────────────────────────────

export interface BulkField {
  key: string;
  label: string;
  type?: "text" | "select";
  options?: [string, string][];
  required?: boolean;
}

export interface BulkAction<T> {
  id: string;
  label: string;
  icon?: LucideIcon;
  tone?: "primary" | "danger";
  title: string;
  description?: ReactNode;
  confirmLabel: string;
  /** Champs complémentaires (en plus du motif, toujours exigé : il est journalisé pour chaque élément). */
  fields?: BulkField[];
  /** Seules les lignes éligibles sont traitées ; les autres sont ignorées et comptées. */
  eligible?: (row: T) => boolean;
  /** Appel de l'API EXISTANTE pour UNE ligne (donc journalisé et contrôlé comme une action isolée). */
  run: (row: T, body: Record<string, string>) => Promise<unknown>;
}

type Outcome = { id: string | number; label: string; error?: string };

/** Exécute l'action ligne par ligne (aucun endpoint « en masse » : chaque élément passe par ses propres contrôles) puis résume. */
function BulkDialog<T>({
  action,
  rows,
  rowKey,
  rowLabel,
  onClose,
  onDone,
}: {
  action: BulkAction<T>;
  rows: T[];
  rowKey: (r: T) => string | number;
  rowLabel: (r: T) => string;
  onClose: () => void;
  onDone: () => void;
}) {
  const eligible = useMemo(() => rows.filter((r) => (action.eligible ? action.eligible(r) : true)), [rows, action]);
  const skipped = rows.length - eligible.length;
  const [values, setValues] = useState<Record<string, string>>({});
  const [phase, setPhase] = useState<"form" | "running" | "done">("form");
  const [progress, setProgress] = useState(0);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const reason = (values.reason ?? "").trim();
  const missing = reason.length < MIN_REASON || (action.fields ?? []).some((f) => f.required && !(values[f.key] ?? "").trim());

  async function run() {
    setPhase("running");
    const results: Outcome[] = [];
    for (const row of eligible) {
      try {
        await action.run(row, { ...values, reason });
        results.push({ id: rowKey(row), label: rowLabel(row) });
      } catch (e) {
        const fields = fieldErrors(e);
        results.push({ id: rowKey(row), label: rowLabel(row), error: Object.values(fields)[0] || boError(e, "Échec.") });
      }
      setProgress(results.length);
    }
    setOutcomes(results);
    setPhase("done");
  }

  const failed = outcomes.filter((o) => o.error);
  return (
    <Modal
      open
      onClose={phase === "running" ? () => undefined : phase === "done" ? onDone : onClose}
      title={action.title}
      description={phase === "form" ? action.description : undefined}
      dismissible={phase !== "running"}
      size="md"
      footer={
        phase === "done" ? (
          <Button onClick={onDone}>Fermer</Button>
        ) : (
          <>
            <Button variant="outline" onClick={onClose} disabled={phase === "running"}>Annuler</Button>
            <Button variant={action.tone ?? "primary"} loading={phase === "running"} disabled={missing || eligible.length === 0} onClick={() => void run()}>
              {action.confirmLabel} ({eligible.length})
            </Button>
          </>
        )
      }
    >
      {phase === "done" ? (
        <div className="space-y-3">
          <Alert tone={failed.length ? "warning" : "success"}>
            {outcomes.length - failed.length} sur {outcomes.length} traité(s){failed.length ? ` · ${failed.length} en échec (rien n’a été modifié pour ceux-là)` : ""}.
          </Alert>
          {failed.length ? (
            <ul className="max-h-48 space-y-1 overflow-y-auto rounded-xl border border-lineSoft p-3 text-sm">
              {failed.map((o) => (
                <li key={o.id} className="flex gap-2"><span className="font-semibold text-ink">{o.label}</span><span className="text-dangerInk">— {o.error}</span></li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-inkSoft">
            <strong className="text-ink">{eligible.length}</strong> élément(s) seront traités un par un{skipped ? `, ${skipped} ignoré(s) (non concernés par cette action)` : ""}. Chaque élément est journalisé séparément avec le motif.
          </p>
          {(action.fields ?? []).map((f) =>
            f.type === "select" ? (
              <label key={f.key} className="block text-sm font-semibold text-ink">
                {f.label}
                <select className="mt-1.5 block w-full min-h-[44px] rounded-control border border-line bg-white px-3 text-sm" value={values[f.key] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}>
                  {f.options?.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
            ) : (
              <label key={f.key} className="block text-sm font-semibold text-ink">
                {f.label}
                <input className="mt-1.5 block w-full min-h-[44px] rounded-control border border-line bg-white px-3 text-sm" value={values[f.key] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} />
              </label>
            ),
          )}
          <label className="block text-sm font-semibold text-ink">
            Motif <span aria-hidden className="text-danger">*</span>
            <textarea
              className="mt-1.5 block w-full rounded-control border border-line bg-white px-3 py-2 text-sm"
              rows={3}
              value={values.reason ?? ""}
              disabled={phase === "running"}
              onChange={(e) => setValues((v) => ({ ...v, reason: e.target.value }))}
              placeholder={`Au moins ${MIN_REASON} caractères — conservé dans le journal d’audit de chaque élément`}
            />
          </label>
          {phase === "running" ? (
            <p role="status" className="flex items-center gap-2 text-sm font-medium text-inkSoft">
              <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> {progress} / {eligible.length} traité(s)…
            </p>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

// ── Tableau ──────────────────────────────────────────────────────────────────────────────────────────────────────────

/** Largeur minimale d'écran à partir de laquelle une colonne secondaire s'affiche dans le tableau (sidebar de 288 px incluse). */
const FROM = { lg: "hidden lg:table-cell", xl: "hidden xl:table-cell", "2xl": "hidden 2xl:table-cell", "3xl": "hidden 3xl:table-cell" } as const;

export interface BoColumn<T> extends Column<T> {
  /** Colonne secondaire : affichée dans le tableau seulement à partir de ce palier (toujours visible dans la carte mobile sauf `hideOnMobile`). */
  from?: keyof typeof FROM;

  /** Valeur de `?ordering=` (liste blanche côté serveur) : rend l'en-tête triable. */
  sort?: string;
  /** Texte libre (adresse, motif…) : retour à la ligne autorisé ; sinon la cellule ne se coupe pas. */
  wrap?: boolean;
}

function SortHeader({ column, ordering, onOrdering }: { column: BoColumn<never>; ordering: string; onOrdering: (v: string) => void }) {
  const key = column.sort as string;
  const state = ordering === key ? "asc" : ordering === `-${key}` ? "desc" : "none";
  const next = state === "none" ? key : state === "asc" ? `-${key}` : "";
  const Icon = state === "asc" ? ArrowUp : state === "desc" ? ArrowDown : ArrowUpDown;
  return (
    <button type="button" onClick={() => onOrdering(next)} className={cx("group inline-flex items-center gap-1.5 rounded uppercase tracking-[0.12em] hover:text-ink", RING, state !== "none" && "text-ink")}>
      {column.header}
      <Icon aria-hidden className={cx("h-3.5 w-3.5", state === "none" ? "opacity-40 group-hover:opacity-100" : "text-primary")} />
      <span className="sr-only">{state === "asc" ? "tri croissant" : state === "desc" ? "tri décroissant" : "trier"}</span>
    </button>
  );
}

type List<T> = ReturnType<typeof useBoList<T>>;

export interface ListViewProps<T> {
  list: List<T>;
  columns: BoColumn<T>[];
  rowKey: (row: T) => string | number;
  caption: string;
  empty: string;
  rowHref?: (row: T) => string;
  /** Tri serveur : valeur courante de `ordering` et son modificateur. */
  ordering?: string;
  onOrdering?: (v: string) => void;
  /** Menu « ⋯ » par ligne (actions contextuelles). */
  rowActions?: (row: T) => RowAction[];
  /** Libellé accessible d'une ligne (menu, cases à cocher, résumé des actions groupées). */
  rowLabel?: (row: T) => string;
  /** Actions groupées : active la colonne de cases à cocher. */
  bulk?: BulkAction<T>[];
  /** Taille de page choisie et son modificateur. */
  pageSize?: number;
  onPageSize?: (n: number) => void;
  /** État vide : pourquoi / quoi faire. */
  emptyHint?: ReactNode;
}

const SIZES = [25, 50, 100];

/** Tableau de gestion : tri, actions par ligne, sélection groupée, pagination, états chargement / vide / erreur. */
export function ListView<T>({ list, columns, rowKey, caption, empty, emptyHint, rowHref, ordering = "", onOrdering, rowActions, rowLabel, bulk, pageSize, onPageSize }: ListViewProps<T>) {
  const [selected, setSelected] = useState<Set<string | number>>(new Set());
  const [action, setAction] = useState<BulkAction<T> | null>(null);
  const label = rowLabel ?? ((r: T) => String(rowKey(r)));
  const rowsKey = useMemo(() => list.rows.map(rowKey).join(","), [list.rows, rowKey]);
  useEffect(() => setSelected(new Set()), [rowsKey]);

  if (list.error && list.rows.length === 0) {
    return (
      <Alert tone="danger" title="Liste indisponible" action={<Button size="sm" variant="outline" onClick={() => void list.reload()}>Réessayer</Button>}>
        {list.error}
      </Alert>
    );
  }

  const selectedRows = list.rows.filter((r) => selected.has(rowKey(r)));
  const allOnPage = list.rows.length > 0 && selectedRows.length === list.rows.length;
  const toggle = (id: string | number) => setSelected((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
  const toggleAll = () => setSelected(allOnPage ? new Set() : new Set(list.rows.map(rowKey)));
  const primary = columns.find((c) => c.primary) ?? columns[0];
  const secondary = columns.filter((c) => c !== primary && !c.hideOnMobile);
  const hasActions = Boolean(rowActions);
  const pages = Math.max(1, Math.ceil(list.count / list.pageSize));
  const from = list.count ? (list.page - 1) * list.pageSize + 1 : 0;
  const to = Math.min(list.count, list.page * list.pageSize);

  return (
    <>
      {list.error ? <Alert tone="warning" className="mb-3">{list.error}</Alert> : null}

      {bulk && selectedRows.length ? (
        <div role="region" aria-label="Actions groupées" className="sticky top-[72px] z-10 mb-3 flex flex-wrap items-center gap-3 rounded-card border border-primary/30 bg-primarySoft px-4 py-3 shadow-soft">
          <p className="text-sm font-semibold text-primaryDark">{selectedRows.length} sélectionné(s)</p>
          <div className="flex flex-wrap gap-2">
            {bulk.map((b) => {
              const Icon = b.icon;
              return (
                <Button key={b.id} size="sm" variant={b.tone === "danger" ? "danger" : "primary"} leftIcon={Icon ? <Icon aria-hidden className="h-4 w-4" /> : undefined} onClick={() => setAction(b)}>
                  {b.label}
                </Button>
              );
            })}
          </div>
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSelected(new Set())}>Tout désélectionner</Button>
        </div>
      ) : null}

      {list.loading && list.rows.length === 0 ? (
        <>
          <SkeletonTable rows={6} cols={Math.min(columns.length, 5)} className="hidden md:block" />
          <SkeletonList count={3} className="md:hidden" />
        </>
      ) : list.rows.length === 0 ? (
        <EmptyState title={empty} description={emptyHint} compact />
      ) : (
        <div className={cx("transition-opacity", list.loading && "opacity-60")} aria-busy={list.loading}>
          {/* Bureau / tablette : le défilement horizontal est borné au tableau (jamais à la page) */}
          <div className="relative hidden overflow-x-auto rounded-card border border-lineSoft bg-white shadow-soft md:block">
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">{caption}</caption>
              <thead>
                <tr className="bg-canvas">
                  {bulk ? (
                    <th scope="col" className="w-12 px-4 py-3.5">
                      <input type="checkbox" aria-label="Tout sélectionner sur cette page" checked={allOnPage} onChange={toggleAll} className="h-4 w-4 rounded border-line accent-primaryDark" />
                    </th>
                  ) : null}
                  {columns.map((c) => (
                    <th
                      key={c.key}
                      scope="col"
                      aria-sort={c.sort ? (ordering === c.sort ? "ascending" : ordering === `-${c.sort}` ? "descending" : "none") : undefined}
                      className={cx("whitespace-nowrap px-4 py-3.5 text-[11px] font-bold uppercase tracking-[0.12em] text-ash", c.from && FROM[c.from], c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left", c.className)}
                    >
                      {c.sort && onOrdering ? <SortHeader column={c as BoColumn<never>} ordering={ordering} onOrdering={onOrdering} /> : c.header}
                    </th>
                  ))}
                  {hasActions ? <th scope="col" className="w-14 px-2 py-3.5"><span className="sr-only">Actions</span></th> : null}
                </tr>
              </thead>
              <tbody>
                {list.rows.map((row) => {
                  const id = rowKey(row);
                  const href = rowHref?.(row);
                  return (
                    <tr key={id} className={cx("border-t border-lineSoft transition-colors duration-150 hover:bg-canvas/80", selected.has(id) && "bg-primarySoft/50")}>
                      {bulk ? (
                        <td className="px-4 py-3.5 align-middle">
                          <input type="checkbox" aria-label={`Sélectionner ${label(row)}`} checked={selected.has(id)} onChange={() => toggle(id)} className="h-4 w-4 rounded border-line accent-primaryDark" />
                        </td>
                      ) : null}
                      {columns.map((c, i) => (
                        <td key={c.key} className={cx("px-4 py-3.5 align-middle text-inkSoft", c.from && FROM[c.from], c.wrap ? "min-w-[10rem] max-w-[18rem] break-words" : "whitespace-nowrap", c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left", c.className)}>
                          {href && i === 0 ? (
                            <Link href={href} className={cx("rounded font-semibold text-ink hover:text-primaryDark", RING)}>{c.cell(row)}</Link>
                          ) : (
                            c.cell(row)
                          )}
                        </td>
                      ))}
                      {hasActions ? <td className="px-2 py-2 text-right align-middle"><RowMenu actions={rowActions!(row)} label={label(row)} /></td> : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile : cartes empilées */}
          <ul className="grid grid-cols-1 gap-3 md:hidden">
            {list.rows.map((row) => {
              const id = rowKey(row);
              const href = rowHref?.(row);
              return (
                <li key={id} className={cx("rounded-panel border bg-white p-4 shadow-soft", selected.has(id) ? "border-primary/40 bg-primarySoft/40" : "border-lineSoft")}>
                  <div className="flex items-start gap-3">
                    {bulk ? <input type="checkbox" aria-label={`Sélectionner ${label(row)}`} checked={selected.has(id)} onChange={() => toggle(id)} className="mt-1 h-5 w-5 shrink-0 rounded border-line accent-primaryDark" /> : null}
                    <div className="min-w-0 flex-1 font-semibold text-ink">
                      {href ? <Link href={href} className={cx("rounded hover:text-primaryDark", RING)}>{primary.cell(row)}</Link> : primary.cell(row)}
                    </div>
                    {hasActions ? <RowMenu actions={rowActions!(row)} label={label(row)} /> : null}
                  </div>
                  {secondary.length ? (
                    <dl className="mt-3 space-y-2 border-t border-lineSoft pt-3 text-sm">
                      {secondary.map((c) => (
                        <div key={c.key} className="flex items-start justify-between gap-4">
                          <dt className="shrink-0 text-ash">{c.mobileLabel ?? c.header}</dt>
                          <dd className="min-w-0 break-words text-right text-inkSoft">{c.cell(row)}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {list.count > 0 ? (
        <nav aria-label="Pagination" className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 text-sm text-inkSoft">
          <p>
            <strong className="text-ink">{from}–{to}</strong> sur <strong className="text-ink">{list.count}</strong> résultat{list.count > 1 ? "s" : ""}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            {onPageSize && pageSize ? (
              <label className="flex items-center gap-2 text-xs font-semibold text-ash">
                Par page
                <select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))} className="min-h-[40px] rounded-control border border-line bg-white px-2 text-sm text-ink">
                  {SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            ) : null}
            <span className="flex items-center gap-2">
              <Button size="sm" variant="outline" disabled={list.page <= 1} onClick={() => list.setPage(list.page - 1)}>Précédent</Button>
              <span className="min-w-[5.5rem] text-center text-xs font-semibold text-ash">Page {Math.min(list.page, pages)} / {pages}</span>
              <Button size="sm" variant="outline" disabled={list.page >= pages} onClick={() => list.setPage(list.page + 1)}>Suivant</Button>
            </span>
          </div>
        </nav>
      ) : null}

      {action ? (
        <BulkDialog
          action={action}
          rows={selectedRows}
          rowKey={rowKey}
          rowLabel={label}
          onClose={() => setAction(null)}
          onDone={() => {
            setAction(null);
            setSelected(new Set());
            void list.reload();
          }}
        />
      ) : null}
    </>
  );
}
