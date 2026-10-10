"use client";
import { useState } from "react";
import { Star } from "lucide-react";
import { apiErrorMessage, post } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard";
import { useData } from "@/lib/useData";
import type { ReviewRow } from "@/lib/reviews";
import { Alert, Button, Card, EmptyState, Modal, PageHeader, SkeletonList, Tabs, TextareaField } from "@/components/ds";
import { ReviewCard } from "@/components/reviews/ReviewCard";
import { ReviewForm } from "@/components/reviews/ReviewForm";
import { formatDateTimeShort } from "../_components/dates";

interface ToWrite { booking_id: number; service: string; artisan: string; booking_date: string | null }
interface Reviews { received: ReviewRow[]; given: ReviewRow[]; to_write: ToWrite[] }

export default function ReviewsPage() {
  const { data, loading, error, reload } = useData<Reviews>("/me/reviews/", "Vos avis ne peuvent pas être chargés.");
  const dash = useDashboard();
  const isProvider = dash.data?.capabilities.provider ?? false;
  const [tab, setTab] = useState<"write" | "received" | "given">("write");
  const [target, setTarget] = useState<ToWrite | null>(null);
  const [editing, setEditing] = useState<ReviewRow | null>(null);
  const [replying, setReplying] = useState<ReviewRow | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");

  const tabs = [
    { id: "write" as const, label: "À rédiger", count: data?.to_write.length },
    ...(isProvider ? [{ id: "received" as const, label: "Reçus", count: data?.received.length }] : []),
    { id: "given" as const, label: "Donnés", count: data?.given.length },
  ];

  async function done() {
    setTarget(null);
    setEditing(null);
    await Promise.all([reload(), dash.reload()]);
  }

  async function sendReply() {
    if (!replying || !reply.trim()) return;
    setBusy(true);
    setFailure("");
    try {
      await post(`/reviews/${replying.id}/reply/`, { text: reply.trim() });
      setReplying(null);
      await reload();
    } catch (e) {
      setFailure(apiErrorMessage(e, "La réponse n’a pas pu être publiée."));
    } finally {
      setBusy(false);
    }
  }

  const list = tab === "received" ? data?.received ?? [] : data?.given ?? [];
  return (
    <>
      <PageHeader title="Avis" description="Évaluez vos prestations (qualité, ponctualité, professionnalisme…) et répondez aux avis reçus." />
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
                      <Button size="sm" onClick={() => setTarget(t)}>Donner mon avis</Button>
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
                  <ReviewCard
                    rating={r.rating}
                    comment={r.comment}
                    criteria={r.criteria}
                    photos={r.photos}
                    reply={r.reply}
                    createdAt={r.created_at}
                    meta={`${r.service ?? "Prestation"} · ${tab === "received" ? `par ${r.author}` : `pour ${r.artisan}`}`}
                    actions={
                      tab === "received" && r.can_reply ? (
                        <Button size="sm" variant="outline" onClick={() => { setReplying(r); setReply(r.reply?.text ?? ""); setFailure(""); }}>
                          {r.reply ? "Modifier ma réponse" : "Répondre"}
                        </Button>
                      ) : tab === "given" && r.can_edit ? (
                        <Button size="sm" variant="outline" onClick={() => setEditing(r)}>Modifier</Button>
                      ) : undefined
                    }
                  />
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <ReviewForm
        open={Boolean(target) || Boolean(editing)}
        onClose={() => { setTarget(null); setEditing(null); }}
        onDone={() => void done()}
        bookingId={target?.booking_id}
        review={editing}
        subtitle={target ? `${target.service} — ${target.artisan}` : editing ? `${editing.service ?? "Prestation"} — ${editing.artisan ?? ""}` : undefined}
      />

      <Modal
        open={Boolean(replying)}
        onClose={() => !busy && setReplying(null)}
        title="Répondre à cet avis"
        description="Votre réponse est publique, sous l’avis du client."
        size="md"
        footer={
          <>
            <Button variant="outline" onClick={() => setReplying(null)} disabled={busy}>Annuler</Button>
            <Button onClick={() => void sendReply()} loading={busy} disabled={!reply.trim()}>Publier la réponse</Button>
          </>
        }
      >
        <div className="space-y-3">
          <TextareaField label="Votre réponse" rows={4} maxLength={600} value={reply} onChange={(e) => setReply(e.target.value)} />
          {failure ? <Alert tone="danger">{failure}</Alert> : null}
        </div>
      </Modal>
    </>
  );
}
