"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { resolveTrades, searchCatalog } from "@/lib/trades";
import type { Category } from "@/lib/types";

/** Recherche instantanée dans le catalogue : métiers et prestations par nom ou par synonyme (« clim », « frigo », « écran cassé »). */
export default function CatalogFinder({ categories }: { categories: Category[] }) {
  const trades = useMemo(() => resolveTrades(categories), [categories]);
  const [q, setQ] = useState("");
  const hits = useMemo(() => searchCatalog(trades, q, 12), [trades, q]);
  return (
    <div className="mt-6 max-w-2xl">
      <label htmlFor="catalog-finder" className="block text-sm font-semibold text-ink">Trouver un métier ou une prestation</label>
      <div className="mt-1.5 flex min-h-[48px] items-center gap-2 rounded-2xl border border-line bg-white px-4 focus-within:ring-2 focus-within:ring-primary/40">
        <Search aria-hidden className="h-5 w-5 shrink-0 text-primary" />
        <input id="catalog-finder" type="search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={80} autoComplete="off"
          placeholder="Clim, frigo, écran cassé, site internet…" className="w-full bg-transparent text-[15px] text-ink outline-none placeholder:text-fog" />
      </div>
      {q.trim().length >= 2 ? (
        hits.length ? (
          <ul className="mt-2 divide-y divide-slate-100 overflow-hidden rounded-2xl border border-slate-100 bg-white shadow-soft">
            {hits.map(({ category, trade, synonym }) => (
              <li key={category.id}>
                <Link href={`/search?metier=${category.parent == null ? trade.slugs.join(",") : category.slug}`}
                  className="flex flex-col px-4 py-2.5 hover:bg-primarySoft focus-visible:bg-primarySoft focus-visible:outline-none">
                  <span className="text-sm font-semibold text-ink">{category.name}</span>
                  <span className="text-xs text-ash">
                    {category.parent == null ? "Métier" : trade.label}
                    {synonym ? ` · « ${synonym} »` : ""}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p role="status" className="mt-2 text-sm text-ash">
            Aucun métier ne correspond. Décrivez plutôt votre problème : <Link href={`/panne?q=${encodeURIComponent(q.trim())}`} className="font-semibold text-primaryDark underline">J’ai une panne</Link>.
          </p>
        )
      ) : null}
    </div>
  );
}
