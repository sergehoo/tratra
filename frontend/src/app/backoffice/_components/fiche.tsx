"use client";
import { useMemo, type ReactNode } from "react";
import { Avatar, Tabs, cx } from "@/components/ds";
import { useTabParam } from "@/lib/useUrlFilters";

export interface FicheTab {
  id: string;
  label: string;
  /** Compteur réel (éléments de l'onglet) — absent tant qu'il n'est pas connu. */
  count?: number;
  /** Onglet réservé à un droit que l'utilisateur n'a pas : il n'est simplement pas proposé. */
  hidden?: boolean;
  content: ReactNode;
}

/**
 * Fiche détaillée : en-tête (identité, pastilles, faits clés, actions) puis onglets gardés dans l'URL (`?tab=`).
 * Les contenus des onglets non affichés ne sont pas montés : leurs données ne sont chargées qu'à l'ouverture.
 */
export function Fiche({
  name,
  eyebrow,
  subtitle,
  badges,
  facts,
  actions,
  tabs,
  alert,
}: {
  name: string;
  eyebrow?: ReactNode;
  subtitle?: ReactNode;
  badges?: ReactNode;
  facts?: [string, ReactNode][];
  actions?: ReactNode;
  tabs: FicheTab[];
  alert?: ReactNode;
}) {
  const visible = useMemo(() => tabs.filter((t) => !t.hidden), [tabs]);
  const ids = useMemo(() => visible.map((t) => t.id), [visible]);
  const [tab, setTab] = useTabParam(ids, ids[0] ?? "general");
  const current = visible.find((t) => t.id === tab) ?? visible[0];

  return (
    <>
      <header className="mb-6 rounded-card border border-lineSoft bg-white p-5 shadow-soft sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
          <div className="flex min-w-0 items-center gap-4">
            <Avatar name={name} size={64} />
            <div className="min-w-0">
              {eyebrow ? <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-primaryDark">{eyebrow}</p> : null}
              <h1 className="font-display text-2xl font-extrabold leading-tight tracking-tight text-ink [text-wrap:balance] sm:text-[1.9rem]">{name}</h1>
              {subtitle ? <p className="mt-1 text-sm text-ash">{subtitle}</p> : null}
              {badges ? <div className="mt-2.5 flex flex-wrap gap-1.5">{badges}</div> : null}
            </div>
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2.5">{actions}</div> : null}
        </div>
        {facts?.length ? (
          <dl className="mt-5 grid gap-x-6 gap-y-3 border-t border-lineSoft pt-4 sm:grid-cols-2 lg:grid-cols-4">
            {facts.map(([k, v]) => (
              <div key={k} className="min-w-0">
                <dt className="text-[11px] font-bold uppercase tracking-[0.12em] text-ash">{k}</dt>
                <dd className="mt-0.5 break-words text-sm font-semibold text-ink">{v ?? "—"}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </header>

      {alert}

      <Tabs
        ariaLabel="Sections de la fiche"
        value={current?.id ?? ""}
        onChange={setTab}
        className="mb-5"
        items={visible.map((t) => ({ id: t.id, label: t.label, count: t.count }))}
      />
      <div role="tabpanel" id={`panel-${current?.id}`} aria-labelledby={`tab-${current?.id}`} className={cx("min-w-0")}>
        {current?.content}
      </div>
    </>
  );
}

/** Bloc d'un onglet : titre, pastille d'aide et contenu ; garde les fiches aérées et cohérentes. */
export function Pane({ children, columns = 2 }: { children: ReactNode; columns?: 1 | 2 }) {
  return <div className={cx("grid gap-5", columns === 2 && "lg:grid-cols-2")}>{children}</div>;
}

/** État « réservé » : l'onglet existe mais le rôle n'a pas le droit d'en voir le contenu. */
export function Restricted({ right, children }: { right: string; children?: ReactNode }) {
  return (
    <p className="rounded-panel bg-canvas p-4 text-sm text-inkSoft">
      {children ?? "Ces informations sont réservées à un autre rôle."} <span className="text-ash">(droit requis : {right})</span>
    </p>
  );
}
