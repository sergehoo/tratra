import type { Service } from "./types";

/**
 * Nom public de l'artisan d'un service : profil public d'abord, sinon l'identité minimale
 * embarquée (`handyman_detail.display_name`, « Prénom N. »). Lecture défensive : le champ
 * peut être absent selon la version de l'API.
 */
export function artisanDisplayName(service: Pick<Service, "artisan" | "handyman_detail"> | null | undefined): string | undefined {
  if (!service) return undefined;
  const mini = service.handyman_detail as { display_name?: string } | null | undefined;
  return service.artisan?.display_name ?? mini?.display_name;
}
