"use client";
import { useCallback, useEffect, useState } from "react";
import { Button, Card, CardHeader, SkeletonList } from "@/components/ds";
import { ReviewCard } from "@/components/reviews/ReviewCard";
import { StarRow } from "@/components/market/primitives";
import { publicGet } from "@/lib/public";
import { REVIEW_CRITERIA, type CriterionKey, type ReviewReply } from "@/lib/reviews";
import type { ReviewStats } from "@/lib/trust";

interface Row {
  id: number;
  rating: number;
  comment: string;
  criteria: Partial<Record<CriterionKey, number>>;
  photos: string[];
  reply: ReviewReply | null;
  author: string;
  category?: string | null;
  created_at: string;
}
interface Page { count: number; next: string | null; results: Row[]; stats: ReviewStats }

/** Avis publiés d'un artisan (missions terminées, un avis par client) : répartition, critères et liste paginée. */
export function PassportReviews({ profileId }: { profileId: number }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async (n: number) => {
    setLoading(true);
    setFailed(false);
    const data = await publicGet<Page>(`/handymen/${profileId}/reviews/?page=${n}`, { timeoutMs: 8000 });
    if (!data) setFailed(true);
    else {
      setRows((prev) => (n === 1 ? data.results : [...prev, ...data.results]));
      setStats(data.stats);
      setMore(Boolean(data.next));
      setPage(n);
    }
    setLoading(false);
  }, [profileId]);

  useEffect(() => {
    void load(1);
  }, [load]);

  const total = stats?.count ?? 0;
  return (
    <Card as="section" aria-label="Avis des clients">
      <CardHeader title="Avis des clients" description="Uniquement des clients ayant réellement fait réaliser une mission terminée." />
      {stats && total > 0 ? (
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <div>
            <p className="font-display text-4xl font-bold text-ink">{String(stats.average).replace(".", ",")}<span className="text-lg text-ash"> / 5</span></p>
            <StarRow value={stats.average ?? 0} />
            <p className="mt-1 text-xs text-ash">
              {total} avis{stats.response_rate != null ? ` · ${Math.round(stats.response_rate * 100)} % avec réponse de l’artisan` : ""}
            </p>
            <ul className="mt-3 space-y-1" aria-label="Répartition des notes">
              {[5, 4, 3, 2, 1].map((n) => {
                const c = stats.distribution[String(n)] ?? 0;
                return (
                  <li key={n} className="flex items-center gap-2 text-xs text-ash">
                    <span className="w-3 text-right font-semibold text-inkSoft">{n}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-lineSoft">
                      <div className="h-full rounded-full bg-accent" style={{ width: `${total ? (c / total) * 100 : 0}%` }} />
                    </div>
                    <span className="w-6 text-right">{c}</span>
                  </li>
                );
              })}
            </ul>
          </div>
          <ul className="space-y-2" aria-label="Notes par critère">
            {REVIEW_CRITERIA.map((c) => {
              const row = stats.criteria[c.key];
              return (
                <li key={c.key} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-inkSoft">{c.label}</span>
                  <span className="font-semibold text-ink">
                    {row?.average != null ? `${String(row.average).replace(".", ",")}/5` : "—"}
                    {row?.count ? <span className="ml-1 text-xs font-normal text-ash">({row.count})</span> : null}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      <div className="mt-5 space-y-3">
        {rows.map((r) => (
          <ReviewCard
            key={r.id}
            rating={r.rating}
            comment={r.comment}
            criteria={r.criteria}
            photos={r.photos}
            reply={r.reply}
            createdAt={r.created_at}
            meta={`${r.author}${r.category ? ` · ${r.category}` : ""}`}
          />
        ))}
        {loading ? <SkeletonList count={2} /> : null}
        {failed ? (
          <p className="text-sm text-dangerInk">
            Les avis n’ont pas pu être chargés.{" "}
            <button type="button" className="font-semibold underline" onClick={() => void load(page)}>Réessayer</button>
          </p>
        ) : null}
        {!loading && !failed && rows.length === 0 ? <p className="text-sm text-ash">Cet artisan n’a pas encore reçu d’avis.</p> : null}
        {more && !loading ? (
          <Button type="button" variant="outline" block onClick={() => void load(page + 1)}>
            Afficher plus d’avis
          </Button>
        ) : null}
      </div>
    </Card>
  );
}
