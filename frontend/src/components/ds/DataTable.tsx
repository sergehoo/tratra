import Link from "next/link";
import type { ReactNode } from "react";
import { cx } from "./cx";
import { EmptyState } from "./EmptyState";
import { SkeletonList, SkeletonTable } from "./Skeleton";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  align?: "left" | "right" | "center";
  /** Classes de la colonne en mode tableau (largeur, etc.). */
  className?: string;
  /** Colonne principale : devient le titre de la carte en mobile. */
  primary?: boolean;
  /** Masque la colonne en mobile (information secondaire). */
  hideOnMobile?: boolean;
  /** Libellé affiché en mobile (par défaut : `header`). */
  mobileLabel?: ReactNode;
}

const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;

/**
 * Tableau responsive : vrai <table> dès `md`, liste de cartes empilées en mobile
 * (colonne `primary` = titre, autres = paires libellé/valeur).
 * États de chargement et vide intégrés.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  loading,
  empty,
  rowHref,
  className = "",
  skeletonRows = 5,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  /** Titre accessible du tableau (masqué visuellement). */
  caption: string;
  loading?: boolean;
  /** Rendu quand `rows` est vide (ex. <EmptyState … />). */
  empty?: ReactNode;
  /** Rend toute la ligne cliquable vers une route réelle. */
  rowHref?: (row: T) => string;
  className?: string;
  skeletonRows?: number;
}) {
  if (loading) {
    return (
      <div className={className}>
        <SkeletonTable rows={skeletonRows} cols={Math.min(columns.length, 5)} className="hidden md:block" />
        <SkeletonList count={Math.min(skeletonRows, 3)} className="md:hidden" />
      </div>
    );
  }
  if (rows.length === 0) {
    return <div className={className}>{empty ?? <EmptyState title="Aucun élément" compact />}</div>;
  }

  const primary = columns.find((c) => c.primary) ?? columns[0];
  const secondary = columns.filter((c) => c !== primary && !c.hideOnMobile);

  return (
    <div className={className}>
      {/* Bureau / tablette */}
      <div className="hidden overflow-x-auto rounded-card border border-lineSoft bg-white shadow-soft md:block">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="bg-canvas">
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className={cx(
                    "px-5 py-3.5 text-[11px] font-bold uppercase tracking-[0.12em] text-ash",
                    ALIGN[c.align ?? "left"],
                    c.className,
                  )}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const href = rowHref?.(row);
              return (
                <tr
                  key={rowKey(row)}
                  className="border-t border-lineSoft transition-colors duration-150 hover:bg-canvas/80"
                >
                  {columns.map((c, i) => (
                    <td key={c.key} className={cx("px-5 py-4 align-middle text-inkSoft", ALIGN[c.align ?? "left"], c.className)}>
                      {href && i === 0 ? (
                        <Link
                          href={href}
                          className="rounded font-semibold text-ink hover:text-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                        >
                          {c.cell(row)}
                        </Link>
                      ) : (
                        c.cell(row)
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Mobile : cartes empilées */}
      <ul className="grid grid-cols-1 gap-3 md:hidden">
        {rows.map((row) => {
          const href = rowHref?.(row);
          const body = (
            <>
              <div className="min-w-0 font-semibold text-ink">{primary.cell(row)}</div>
              {secondary.length ? (
                <dl className="mt-3 space-y-2 border-t border-lineSoft pt-3 text-sm">
                  {secondary.map((c) => (
                    <div key={c.key} className="flex items-center justify-between gap-4">
                      <dt className="shrink-0 text-ash">{c.mobileLabel ?? c.header}</dt>
                      <dd className="min-w-0 text-right text-inkSoft">{c.cell(row)}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </>
          );
          return (
            <li key={rowKey(row)}>
              {href ? (
                <Link
                  href={href}
                  className="block rounded-panel border border-lineSoft bg-white p-4 shadow-soft transition hover:border-primary/20 hover:shadow-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  {body}
                </Link>
              ) : (
                <div className="rounded-panel border border-lineSoft bg-white p-4 shadow-soft">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
