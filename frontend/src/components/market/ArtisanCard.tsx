import { ArrowRight, Briefcase, MapPin } from "lucide-react";
import { Badge } from "@/components/ds/Badge";
import { ButtonLink } from "@/components/ds/Button";
import { Card } from "@/components/ds/Card";
import type { PublicArtisan } from "@/lib/types";
import { formatFCFA } from "@/lib/format";
import { Avatar, RatingStars, VerifiedBadge } from "./primitives";

/** Libellé de CTA long (nom de métier) : on autorise le retour à la ligne. */
const CTA_CLASS = "!whitespace-normal text-center";

/** Tuile d'information (note, missions, expérience, tarif). */
const TILE = "rounded-panel bg-canvas px-3 py-2";

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
    <Card as="article" padding="md" interactive className="group flex h-full flex-col">
      <div className="flex items-start gap-4">
        <Avatar name={artisan.display_name} photo={artisan.photo} size={64} online={artisan.online} />
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-display text-lg font-bold text-ink">{artisan.display_name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {artisan.is_verified ? <VerifiedBadge /> : null}
            {artisan.online ? (
              <Badge tone="success" pulse>
                En ligne
              </Badge>
            ) : null}
          </div>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
        {artisan.rating > 0 ? (
          <div className={TILE}>
            <dt className="text-xs text-ash">Note</dt>
            <dd><RatingStars rating={artisan.rating} size="md" /></dd>
          </div>
        ) : null}
        {artisan.completed_jobs > 0 ? (
          <div className={TILE}>
            <dt className="text-xs text-ash">Missions</dt>
            <dd className="font-semibold text-ink">{artisan.completed_jobs}</dd>
          </div>
        ) : null}
        {artisan.experience_years > 0 ? (
          <div className={TILE}>
            <dt className="text-xs text-ash">Expérience</dt>
            <dd className="inline-flex items-center gap-1 font-semibold text-ink">
              <Briefcase aria-hidden className="h-3.5 w-3.5 text-primary" />
              {artisan.experience_years} an{artisan.experience_years > 1 ? "s" : ""}
            </dd>
          </div>
        ) : null}
        {rate ? (
          <div className={TILE}>
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
            <li key={s.id}>
              <Badge tone="accent">{s.name}</Badge>
            </li>
          ))}
          {artisan.skills.length > 3 ? (
            <li>
              <Badge tone="gray">+{artisan.skills.length - 3}</Badge>
            </li>
          ) : null}
        </ul>
      ) : null}

      {hasServices ? (
        <div className="mt-auto pt-5">
          <ButtonLink
            href={`/search?handyman=${artisan.user_id}`}
            variant="soft"
            block
            className={CTA_CLASS}
            aria-label={`Voir les prestations de ${artisan.display_name}`}
            rightIcon={
              <ArrowRight
                aria-hidden
                className="h-4 w-4 transition duration-base ease-emphasized group-hover:translate-x-0.5"
              />
            }
          >
            Voir ses prestations
          </ButtonLink>
        </div>
      ) : skill ? (
        <div className="mt-auto pt-5">
          <ButtonLink
            href={`/search?metier=${encodeURIComponent(skill.slug)}`}
            variant="soft"
            block
            className={CTA_CLASS}
            rightIcon={
              <ArrowRight
                aria-hidden
                className="h-4 w-4 shrink-0 transition duration-base ease-emphasized group-hover:translate-x-0.5"
              />
            }
          >
            Voir les prestations en {skill.name}
          </ButtonLink>
        </div>
      ) : null}
    </Card>
  );
}
