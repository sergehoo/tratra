"use client";
import { useEffect, useState } from "react";
import { ArrowRight, Quote, RefreshCw, Wrench } from "lucide-react";
import { StarRow } from "@/components/market/primitives";
import { formatCount, formatRating } from "@/lib/format";
import type { PublicReview } from "@/lib/types";
import { useLanding } from "./LandingData";
import { CONTAINER, CtaLink, SECTION_Y, SectionHeading, btn } from "./kit";
import { Reveal, RevealGroup, RevealItem } from "./Reveal";

const RTF = new Intl.RelativeTimeFormat("fr", { numeric: "auto" });
const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["week", 604_800],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

function relativeDate(iso: string, now: number): string | null {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  const diff = (t - now) / 1000;
  for (const [unit, secs] of UNITS) {
    if (Math.abs(diff) >= secs) return RTF.format(Math.round(diff / secs), unit);
  }
  return "à l’instant";
}

function absoluteDate(iso: string): string | null {
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? DATE.format(d) : null;
}

/**
 * Horloge posée après le montage : le rendu serveur affiche la date absolue,
 * le client la remplace par une date relative (pas d'écart d'hydratation).
 */
function useNow(): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => setNow(Date.now()), []);
  return now;
}

function ReviewCard({ review, now }: { review: PublicReview; now: number | null }) {
  const absolute = absoluteDate(review.created_at);
  const when = (now !== null && relativeDate(review.created_at, now)) || absolute;
  const comment = review.comment?.trim();

  return (
    <figure className="flex h-full flex-col rounded-3xl border border-slate-100 bg-white p-6 shadow-soft transition duration-300 hover:-translate-y-1 hover:shadow-strong">
      <div className="flex items-center justify-between gap-3">
        <StarRow value={review.rating} />
        <Quote aria-hidden className="h-7 w-7 text-accent" />
      </div>
      {comment ? (
        <blockquote className="mt-4 line-clamp-6 text-[15px] leading-relaxed text-ink">« {comment} »</blockquote>
      ) : (
        <p className="mt-4 text-sm italic text-ash">Note attribuée sans commentaire.</p>
      )}
      <figcaption className="mt-auto border-t border-slate-100 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <span className="font-semibold text-ink">{review.author}</span>
          {when ? (
            <time dateTime={review.created_at} title={absolute ?? undefined} className="text-xs text-ash">
              {when}
            </time>
          ) : null}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          {review.category ? (
            <span className="rounded-full bg-accentSoft px-2.5 py-1 font-semibold text-ink">{review.category}</span>
          ) : null}
          <span className="inline-flex items-center gap-1 text-ash">
            <Wrench aria-hidden className="h-3.5 w-3.5 text-primaryDark" />
            Artisan : <span className="font-semibold text-ink">{review.artisan}</span>
          </span>
        </div>
      </figcaption>
    </figure>
  );
}

/** Avis réels uniquement (GET /reviews/public/) — jamais de témoignage inventé. */
export default function ReviewsSection() {
  const { data, loading, error, reload } = useLanding("reviews");
  const now = useNow();
  const reviews = data?.results ?? [];
  const count = data?.count ?? 0;
  const average = formatRating(data?.average);

  return (
    <section id="avis" aria-labelledby="avis-titre" className={`scroll-mt-20 bg-white lg:scroll-mt-24 ${SECTION_Y}`}>
      <div className={CONTAINER}>
        {count > 0 && reviews.length ? (
          <div className="grid gap-10 lg:grid-cols-12 lg:gap-12">
            <Reveal className="lg:col-span-4">
              <div className="lg:sticky lg:top-28">
                <SectionHeading
                  id="avis-titre"
                  eyebrow="Avis clients"
                  title="Ce qu’en disent les clients"
                  description="Chaque avis publié provient du client d’une mission terminée sur Tratra."
                />
                <div className="mt-8 rounded-3xl bg-night p-6 text-white shadow-strong">
                  {average ? (
                    <p className="flex items-end gap-2">
                      <span className="font-display text-5xl font-extrabold leading-none">{average}</span>
                      <span className="pb-1 text-lg font-semibold text-white/70">/ 5</span>
                    </p>
                  ) : null}
                  {data?.average ? <StarRow value={data.average} className="mt-3" /> : null}
                  <p className="mt-3 text-sm text-white/75">
                    {formatCount(count)} avis publié{count > 1 ? "s" : ""}
                  </p>
                </div>
              </div>
            </Reveal>

            <RevealGroup as="ul" className="grid gap-5 md:grid-cols-2 lg:col-span-8">
              {reviews.slice(0, 6).map((r) => (
                <RevealItem as="li" key={r.id}>
                  <ReviewCard review={r} now={now} />
                </RevealItem>
              ))}
            </RevealGroup>
          </div>
        ) : loading ? (
          <div role="status" aria-label="Chargement des avis">
            <h2 id="avis-titre" className="sr-only">
              Avis clients
            </h2>
            <div aria-hidden className="grid gap-5 md:grid-cols-3">
              {Array.from({ length: 3 }, (_, i) => (
                <div key={i} className="rounded-3xl border border-slate-100 bg-white p-6 shadow-soft">
                  <div className="skeleton h-4 w-28" />
                  <div className="skeleton mt-5 h-3 w-full" />
                  <div className="skeleton mt-2 h-3 w-5/6" />
                  <div className="skeleton mt-2 h-3 w-2/3" />
                  <div className="skeleton mt-6 h-3 w-1/3" />
                </div>
              ))}
            </div>
          </div>
        ) : (
          <Reveal>
            <div className="relative overflow-hidden rounded-[2rem] border border-slate-100 bg-gradient-to-br from-white via-white to-primarySoft p-8 shadow-soft sm:p-12 lg:p-16">
              <div aria-hidden className="absolute -right-10 -top-10 h-48 w-48 rounded-full bg-accentSoft blur-2xl" />
              <div className="relative grid items-center gap-10 lg:grid-cols-12">
                <div className="lg:col-span-8">
                  <span className="grid h-16 w-16 place-items-center rounded-2xl bg-accent text-night shadow-[0_12px_32px_-8px_rgba(246,201,14,.6)]">
                    <Quote aria-hidden className="h-8 w-8" />
                  </span>
                  <p className="mt-6 text-[11px] font-bold uppercase tracking-[0.16em] text-primaryDark">
                    Avis clients
                  </p>
                  <h2
                    id="avis-titre"
                    className="mt-3 font-display text-[1.75rem] font-extrabold leading-tight tracking-tight text-ink [text-wrap:balance] sm:text-4xl"
                  >
                    Des avis authentiques, laissés après une mission terminée
                  </h2>
                  <p className="mt-4 max-w-2xl text-base leading-relaxed text-ash sm:text-lg">
                    {error
                      ? "Les avis n’ont pas pu être chargés pour le moment. Ici, seul le client d’une mission terminée peut laisser un avis."
                      : "Ici, seul le client d’une mission terminée peut laisser un avis. Les premiers avis apparaîtront après les premières missions terminées."}
                  </p>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row lg:col-span-4 lg:flex-col lg:items-stretch">
                  <CtaLink href="/search" variant="primary" size="lg">
                    Trouver un artisan
                    <ArrowRight aria-hidden className="h-5 w-5" />
                  </CtaLink>
                  {error ? (
                    <button type="button" onClick={reload} className={btn("outline", "lg")}>
                      <RefreshCw aria-hidden className="h-4 w-4" />
                      Réessayer
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          </Reveal>
        )}
      </div>
    </section>
  );
}
