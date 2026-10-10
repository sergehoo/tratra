"use client";
import { useEffect, useRef, useState } from "react";
import { ImagePlus } from "lucide-react";
import { ApiError, apiErrorMessage, patch, post, upload } from "@/lib/api";
import { REVIEW_CRITERIA, type CriterionKey, type ReviewRow } from "@/lib/reviews";
import { Alert, Button, Modal, TextareaField } from "@/components/ds";
import { StarPicker } from "./StarPicker";

const MAX_PHOTOS = 4;

/** Création (booking) ou correction (review) d'un avis : note globale, critères facultatifs, commentaire, photos. */
export function ReviewForm({
  open,
  onClose,
  onDone,
  bookingId,
  review,
  subtitle,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
  bookingId?: number;
  review?: ReviewRow | null;
  subtitle?: string;
}) {
  const [rating, setRating] = useState(0);
  const [criteria, setCriteria] = useState<Partial<Record<CriterionKey, number>>>({});
  const [comment, setComment] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setRating(review?.rating ?? 0);
    setCriteria(review?.criteria ?? {});
    setComment(review?.comment ?? "");
    setFiles([]);
    setError("");
  }, [open, review]);

  const room = MAX_PHOTOS - (review?.photos.length ?? 0);

  async function submit() {
    if (rating < 1) return;
    setBusy(true);
    setError("");
    try {
      const body = { rating, comment: comment.trim(), ...Object.fromEntries(REVIEW_CRITERIA.map((c) => [c.key, criteria[c.key] || null])) };
      const saved = review
        ? await patch<{ id: number }>(`/reviews/${review.id}/`, body)
        : await post<{ id: number }>("/reviews/", { booking: bookingId, ...body });
      for (const file of files.slice(0, room)) {
        const form = new FormData();
        form.append("image", file);
        await upload(`/reviews/${saved.id}/photos/`, form);
      }
      onDone();
    } catch (e) {
      const photo = e instanceof ApiError && e.data && typeof e.data === "object" && "image" in (e.data as object);
      setError(apiErrorMessage(e, photo ? "Une photo n’a pas pu être ajoutée." : "L’avis n’a pas pu être enregistré."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={() => !busy && onClose()}
      title={review ? "Modifier mon avis" : "Votre avis"}
      description={subtitle}
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>Annuler</Button>
          <Button onClick={() => void submit()} loading={busy} disabled={rating < 1}>{review ? "Enregistrer" : "Publier"}</Button>
        </>
      }
    >
      <div className="space-y-5">
        <div>
          <p className="mb-1 text-sm font-semibold text-ink">Note globale</p>
          <StarPicker label="Note globale sur 5" value={rating} onChange={setRating} />
        </div>
        <fieldset>
          <legend className="mb-2 text-sm font-semibold text-ink">Détails <span className="font-normal text-ash">(facultatif)</span></legend>
          <ul className="space-y-1">
            {REVIEW_CRITERIA.map((c) => (
              <li key={c.key} className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm text-inkSoft">{c.label}</span>
                <StarPicker size="sm" clearable label={`${c.label} sur 5`} value={criteria[c.key] ?? 0} onChange={(v) => setCriteria((s) => ({ ...s, [c.key]: v }))} />
              </li>
            ))}
          </ul>
        </fieldset>
        <TextareaField label="Commentaire" optional rows={4} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />
        {room > 0 ? (
          <div>
            <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" multiple className="sr-only" id="review-photos"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, room))} />
            <Button type="button" variant="outline" size="sm" leftIcon={<ImagePlus aria-hidden className="h-4 w-4" />} onClick={() => input.current?.click()}>
              Ajouter des photos {files.length ? `(${files.length})` : ""}
            </Button>
            <p className="mt-1 text-xs text-ash">Jusqu’à {room} photo{room > 1 ? "s" : ""} (JPEG, PNG ou WebP).</p>
          </div>
        ) : null}
        {error ? <Alert tone="danger">{error}</Alert> : null}
      </div>
    </Modal>
  );
}
