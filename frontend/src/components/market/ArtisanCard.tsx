import Link from "next/link";
import { ArrowRight, Briefcase, MapPin } from "lucide-react";
import type { PublicArtisan } from "@/lib/types";
import { formatFCFA } from "@/lib/format";
import { Avatar, OnlineDot, RatingStars, VerifiedBadge } from "./primitives";

const CTA =
  "inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-2xl border border-primary/20 bg-white px-4 py-2.5 text-sm font-semibold text-primaryDark transition hover:border-primary hover:bg-primarySoft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent text-center";

/**
 * Carte d'un artisan réel (GET /handymen/featured/).
 * CTA jamais vide : ses prestations s'il en a publié, sinon les prestations de
 * sa spécialité (si `tradesWithServices` est fourni, seulement une spécialité
 * qui compte des prestations actives), sinon aucun lien.
 */
export default function ArtisanCard({
  artisan,
  tradesWithServices,
}: {
  artisan: PublicArtisan;
  /** Slugs des métiers ayant au moins une prestation active (null/absent : inconnu). */
  tradesWithServices?: ReadonlySet<string> | null;
}) {
  const rate = formatFCFA(artisan.hourly_rate);
  const place = [artisan.commune, artisan.quartier].filter(Boolean).join(" · ");
  const hasServices = (artisan.services_count ?? 0) > 0;
  const skill = hasServices
    ? null
    : artisan.skills.find((s) => !tradesWithServices || tradesWithServices.has(s.slug)) ?? null;

  return (
    <article className="group flex h-full flex-col rounded-3xl border border-slate-100 bg-white p-5 shadow-soft transition duration-300 hover:-translate-y-1 hover:shadow-strong">
      <div className="flex items-start gap-4">
        <Avatar name={artisan.display_name} photo={artisan.photo} size={64} online={artisan.online} />
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-display text-lg font-bold text-ink">{artisan.display_name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {artisan.is_verified ? <VerifiedBadge /> : null}
            {artisan.online ? <OnlineDot /> : null}
          </div>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
        {artisan.rating > 0 ? (
          <div className="rounded-2xl bg-slate-50 px-3 py-2">
            <dt className="text-xs text-ash">Note</dt>
            <dd><RatingStars rating={artisan.rating} size="md" /></dd>
          </div>
        ) : null}
        {artisan.completed_jobs > 0 ? (
          <div className="rounded-2xl bg-slate-50 px-3 py-2">
            <dt className="text-xs text-ash">Missions</dt>
            <dd className="font-semibold text-ink">{artisan.completed_jobs}</dd>
          </div>
        ) : null}
        {artisan.experience_years > 0 ? (
          <div className="rounded-2xl bg-slate-50 px-3 py-2">
            <dt className="text-xs text-ash">Expérience</dt>
            <dd className="inline-flex items-center gap-1 font-semibold text-ink">
              <Briefcase aria-hidden className="h-3.5 w-3.5 text-primary" />
              {artisan.experience_years} an{artisan.experience_years > 1 ? "s" : ""}
            </dd>
          </div>
        ) : null}
        {rate ? (
          <div className="rounded-2xl bg-slate-50 px-3 py-2">
            <dt className="text-xs text-ash">À partir de</dt>
            <dd className="font-semibold text-primaryDark">{rate} / h</dd>
          </div>
        ) : null}
      </dl>

      {place ? (
        <p className="mt-3 inline-flex items-center gap-1.5 text-sm text-ash">
          <MapPin aria-hidden className="h-4 w-4 text-primary" />
          {place}
        </p>
      ) : null}

      {artisan.skills.length ? (
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Spécialités">
          {artisan.skills.slice(0, 3).map((s) => (
            <li key={s.id} className="rounded-full bg-accentSoft px-2.5 py-1 text-xs font-semibold text-ink">
              {s.name}
            </li>
          ))}
          {artisan.skills.length > 3 ? (
            <li className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-ash">
              +{artisan.skills.length - 3}
            </li>
          ) : null}
        </ul>
      ) : null}

      {hasServices ? (
        <div className="mt-auto pt-5">
          <Link
            href={`/search?handyman=${artisan.user_id}`}
            className={CTA}
            aria-label={`Voir les prestations de ${artisan.display_name}`}
          >
            Voir ses prestations
            <ArrowRight aria-hidden className="h-4 w-4 transition group-hover:translate-x-0.5" />
          </Link>
        </div>
      ) : skill ? (
        <div className="mt-auto pt-5">
          <Link href={`/search?metier=${encodeURIComponent(skill.slug)}`} className={CTA}>
            Voir les prestations en {skill.name}
            <ArrowRight aria-hidden className="h-4 w-4 shrink-0 transition group-hover:translate-x-0.5" />
          </Link>
        </div>
      ) : null}
    </article>
  );
}
