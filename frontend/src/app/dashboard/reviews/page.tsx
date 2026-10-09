"use client";
import { useState } from "react";
import { Star } from "lucide-react";
import { apiErrorMessage, post } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard";
import { useData } from "@/lib/useData";
import { Alert, Button, Card, EmptyState, Modal, PageHeader, SkeletonList, Tabs, TextareaField, cx } from "@/components/ds";
import { StarRow } from "@/components/market/primitives";
import { formatDateTimeShort } from "../_components/dates";

interface ReviewRow { id: number; rating: number; comment: string; created_at: string; booking_id: number; service: string | null; author?: string; artisan?: string }
interface ToWrite { booking_id: number; service: string; artisan: string; booking_date: string | null }
interface Reviews { received: ReviewRow[]; given: ReviewRow[]; to_write: ToWrite[] }

export default function ReviewsPage() {
  const { data, loading, error, reload } = useData<Reviews>("/me/reviews/", "Vos avis ne peuvent pas être chargés.");
  const dash = useDashboard();
  const isProvider = dash.data?.capabilities.provider ?? false;
  const [tab, setTab] = useState<"write" | "received" | "given">("write");
  const [target, setTarget] = useState<ToWrite | null>(null);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");

  const tabs = [
    { id: "write" as const, label: "À rédiger", count: data?.to_write.length },
    ...(isProvider ? [{ id: "received" as const, label: "Reçus", count: data?.received.length }] : []),
    { id: "given" as const, label: "Donnés", count: data?.given.length },
  ];

  async function submit() {
    if (!target || rating < 1) return;
    setBusy(true);
    setFailure("");
    try {
      await post("/reviews/", { booking: target.booking_id, rating, comment: comment.trim() });
      setTarget(null);
      setRating(0);
      setComment("");
      await Promise.all([reload(), dash.reload()]);
    } catch (e) {
      setFailure(apiErrorMessage(e, "L’avis n’a pas pu être enregistré."));
    } finally {
      setBusy(false);
    }
  }

  const list = tab === "received" ? data?.received ?? [] : data?.given ?? [];
  return (
    <>
      <PageHeader title="Avis" description="Donnez votre avis sur vos prestations et consultez ceux que vous avez reçus." />
      {loading ? (
        <SkeletonList count={3} />
      ) : error || !data ? (
        <Alert tone="danger" title="Avis indisponibles" action={<Button size="sm" variant="outline" onClick={() => void reload()}>Réessayer</Button>}>{error}</Alert>
      ) : (
        <>
          <Tabs ariaLabel="Type d’avis" value={tab} onChange={setTab} items={tabs} className="mb-5" />
          {tab === "write" ? (
            data.to_write.length === 0 ? (
              <EmptyState icon={<Star />} title="Aucun avis à rédiger" description="Après chaque prestation terminée, vous pourrez la noter ici." />
            ) : (
              <ul className="grid grid-cols-1 gap-3">
                {data.to_write.map((t) => (
                  <li key={t.booking_id}>
                    <Card padding="sm" radius="panel" className="flex flex-wrap items-center gap-3 sm:flex-nowrap">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-display text-[15px] font-bold text-ink">{t.service}</p>
                        <p className="text-xs text-ash">Artisan : {t.artisan}{t.booking_date ? ` · ${formatDateTimeShort(t.booking_date)}` : ""}</p>
                      </div>
                      <Button size="sm" onClick={() => { setTarget(t); setFailure(""); }}>Donner mon avis</Button>
                    </Card>
                  </li>
                ))}
              </ul>
            )
          ) : list.length === 0 ? (
            <EmptyState icon={<Star />} title={tab === "received" ? "Aucun avis reçu" : "Aucun avis donné"}
              description={tab === "received" ? "Les avis de vos clients apparaîtront ici." : "Vos avis publiés apparaîtront ici."} />
          ) : (
            <ul className="grid grid-cols-1 gap-3">
              {list.map((r) => (
                <li key={r.id}>
                  <Card padding="sm" radius="panel">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <StarRow value={r.rating} />
                      <span className="text-xs text-ash">{formatDateTimeShort(r.created_at)}</span>
                    </div>
                    {r.comment ? <p className="mt-2 text-sm leading-relaxed text-inkSoft">{r.comment}</p> : null}
                    <p className={cx("mt-2 text-xs text-ash")}>{r.service ?? "Prestation"} · {tab === "received" ? `par ${r.author}` : `pour ${r.artisan}`}</p>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <Modal
        open={Boolean(target)}
        onClose={() => !busy && setTarget(null)}
        title="Votre avis"
        description={target ? `${target.service} — ${target.artisan}` : undefined}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setTarget(null)} disabled={busy}>Annuler</Button>
            <Button onClick={() => void submit()} loading={busy} disabled={rating < 1}>Publier</Button>
          </>
        }
      >
        <div className="space-y-4">
          <div role="radiogroup" aria-label="Note sur 5" className="flex gap-1">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n} type="button" role="radio" aria-checked={rating === n} aria-label={`${n} sur 5`}
                onClick={() => setRating(n)}
                className="grid h-11 w-11 place-items-center rounded-xl transition hover:bg-lineSoft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <Star aria-hidden className={cx("h-7 w-7", n <= rating ? "fill-accent text-accent" : "text-fog")} />
              </button>
            ))}
          </div>
          <TextareaField label="Commentaire" optional rows={4} value={comment} onChange={(e) => setComment(e.target.value)} />
          {failure ? <Alert tone="danger">{failure}</Alert> : null}
        </div>
      </Modal>
    </>
  );
}
