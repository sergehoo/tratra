import { MessageSquareQuote } from "lucide-react";
import { StarRow } from "@/components/market/primitives";
import { REVIEW_CRITERIA, type CriterionKey, type ReviewReply } from "@/lib/reviews";

function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
}

/** Avis affiché (tableau de bord, passeport public) : note, critères notés, commentaire, photos, réponse. */
export function ReviewCard({
  rating,
  comment,
  criteria,
  photos,
  reply,
  createdAt,
  meta,
  actions,
}: {
  rating: number;
  comment?: string | null;
  criteria?: Partial<Record<CriterionKey, number>>;
  photos?: string[];
  reply?: ReviewReply | null;
  createdAt: string;
  meta: string;
  actions?: React.ReactNode;
}) {
  const rated = REVIEW_CRITERIA.filter((c) => criteria?.[c.key] != null);
  return (
    <article className="rounded-panel border border-lineSoft bg-white p-4 shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StarRow value={rating} />
        <span className="text-xs text-ash">{shortDate(createdAt)}</span>
      </div>
      {rated.length ? (
        <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Critères notés">
          {rated.map((c) => (
            <li key={c.key} className="rounded-full bg-lineSoft px-2.5 py-1 text-xs font-medium text-inkSoft">
              {c.label} <strong className="text-ink">{criteria?.[c.key]}/5</strong>
            </li>
          ))}
        </ul>
      ) : null}
      {comment ? <p className="mt-2 text-sm leading-relaxed text-inkSoft">{comment}</p> : null}
      {photos?.length ? (
        <ul className="mt-3 flex flex-wrap gap-2">
          {photos.map((src, i) => (
            <li key={src}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={src} alt={`Photo ${i + 1} de l’avis`} loading="lazy" className="h-20 w-20 rounded-xl object-cover ring-1 ring-line" />
            </li>
          ))}
        </ul>
      ) : null}
      {reply ? (
        <div className="mt-3 rounded-xl bg-primarySoft/60 p-3">
          <p className="flex items-center gap-1.5 text-xs font-bold text-primaryDark">
            <MessageSquareQuote aria-hidden className="h-4 w-4" /> Réponse de l’artisan
            {reply.at ? <span className="font-medium text-ash">· {shortDate(reply.at)}</span> : null}
          </p>
          <p className="mt-1 text-sm leading-relaxed text-inkSoft">{reply.text}</p>
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-ash">{meta}</p>
        {actions}
      </div>
    </article>
  );
}
