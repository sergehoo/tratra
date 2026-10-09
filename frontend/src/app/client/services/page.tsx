"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, Clock, Search, SearchX, X } from "lucide-react";
import { apiErrorMessage, get } from "@/lib/api";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  DURATION,
  EmptyState,
  Input,
  PageHeader,
  Skeleton,
} from "@/components/ds";
import { formatDuration, priceLabel } from "@/lib/format";
import type { Service, Paginated } from "@/lib/types";
import { ArtisanLine } from "../_components/ArtisanLine";
import { ServiceCover } from "../_components/ServiceCover";

/** Délai d'apparition échelonné des cartes (dérivé de la durée « fast » du Design System). */
const STAGGER = DURATION.fast / 3;

/** Grille de cartes en chargement (même gabarit que les cartes de service). */
function ServiceGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div role="status" aria-label="Chargement en cours" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} aria-hidden className="overflow-hidden rounded-card border border-lineSoft bg-white shadow-soft">
          <Skeleton className="aspect-[16/9] !rounded-none" />
          <div className="space-y-3 p-5">
            <Skeleton className="h-5 w-4/5" />
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-2/5" />
            <div className="flex items-center gap-3 border-t border-lineSoft pt-4">
              <Skeleton className="h-10 w-10 shrink-0 !rounded-full" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          </div>
        </div>
      ))}
      <span className="sr-only">Chargement…</span>
    </div>
  );
}

export default function ServicesPage() {
  const [items, setItems] = useState<Service[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  /** Recherche réellement appliquée aux résultats affichés (≠ saisie en cours). */
  const [applied, setApplied] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  /** Dernière requête lancée : « Réessayer » rejoue celle qui a échoué. */
  const lastQuery = useRef("");

  async function load(query = "") {
    lastQuery.current = query;
    setLoading(true);
    setError("");
    try {
      const d = await get<Paginated<Service>>(`/services/${query ? `?search=${encodeURIComponent(query)}` : ""}`);
      setItems(d.results ?? []);
      setTotal(d.count ?? d.results?.length ?? 0);
      setApplied(query);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Le catalogue ne peut pas être chargé pour le moment."));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  function clearSearch() {
    setQ("");
    searchRef.current?.focus();
    if (applied) void load();
  }

  const searching = applied !== "";
  const countLabel =
    total > items.length
      ? `${items.length} services affichés sur ${total} — affinez votre recherche pour trouver le bon.`
      : `${items.length} service${items.length > 1 ? "s" : ""}${searching ? ` pour « ${applied} »` : ""}`;

  return (
    <>
      <PageHeader
        title="Trouver un service"
        description="Parcourez les services proposés par les artisans Tratra et choisissez celui qui vous convient."
      />

      <form
        role="search"
        onSubmit={(e) => { e.preventDefault(); load(q); }}
        className="mb-6 flex max-w-2xl gap-2"
      >
        <label htmlFor="service-search" className="sr-only">Rechercher un service</label>
        <Input
          id="service-search"
          ref={searchRef}
          type="text"
          enterKeyHint="search"
          autoComplete="off"
          placeholder="Rechercher (plomberie, ménage…)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          leading={<Search className="h-5 w-5" />}
          trailing={
            q ? (
              <button
                type="button"
                onClick={clearSearch}
                aria-label="Effacer la recherche"
                className="grid h-10 w-10 place-items-center rounded-xl text-ash transition hover:bg-lineSoft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <X aria-hidden className="h-4 w-4" />
              </button>
            ) : undefined
          }
          className="flex-1"
        />
        <Button type="submit" loading={loading} className="shrink-0">
          Rechercher
        </Button>
      </form>

      {loading ? (
        <ServiceGridSkeleton />
      ) : error ? (
        <Alert
          tone="danger"
          title="Chargement impossible"
          action={
            <Button size="sm" variant="outline" onClick={() => void load(lastQuery.current)}>
              Réessayer
            </Button>
          }
        >
          {error}
        </Alert>
      ) : items.length === 0 ? (
        searching ? (
          <EmptyState
            icon={<SearchX aria-hidden />}
            title="Aucun service ne correspond à votre recherche"
            description={`Aucun résultat pour « ${applied} ». Essayez un autre mot-clé ou affichez tous les services.`}
            actions={
              <Button variant="outline" onClick={clearSearch}>
                Voir tous les services
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={<Search aria-hidden />}
            title="Aucun service n’est publié pour le moment"
            description="Le catalogue est vide pour l’instant. Revenez bientôt ou consultez vos réservations en cours."
            actions={<ButtonLink href="/client">Mes réservations</ButtonLink>}
          />
        )
      ) : (
        <>
          <p className="mb-4 text-sm font-medium text-ash" role="status">{countLabel}</p>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((s, index) => {
              const duration = formatDuration(s.duration);
              return (
                <li key={s.id} className="animate-rise" style={{ animationDelay: `${Math.min(index, 6) * STAGGER}s` }}>
                  <Link
                    href={`/client/services/${s.id}`}
                    className="group block h-full rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                  >
                    <Card interactive padding="none" className="flex h-full flex-col overflow-hidden">
                      <div className="relative">
                        <ServiceCover service={s} className="aspect-[16/9]" />
                        {s.category_detail ? (
                          <Badge tone="primary" className="absolute left-3 top-3 shadow-hair">
                            {s.category_detail.name}
                          </Badge>
                        ) : null}
                      </div>
                      <div className="flex flex-1 flex-col gap-3 p-5">
                        <h2 className="line-clamp-2 font-display text-base font-bold leading-snug text-ink transition-colors duration-base group-hover:text-primaryDark">
                          {s.title}
                        </h2>
                        {s.description ? <p className="line-clamp-2 text-sm leading-relaxed text-ash">{s.description}</p> : null}
                        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                          <span className="font-display text-base font-extrabold text-primaryDark">{priceLabel(s)}</span>
                          {duration ? (
                            <span className="inline-flex items-center gap-1 text-ash">
                              <Clock aria-hidden className="h-3.5 w-3.5" />
                              {duration}
                            </span>
                          ) : null}
                        </p>
                        <div className="mt-auto flex items-center justify-between gap-3 border-t border-lineSoft pt-4">
                          <ArtisanLine service={s} size={36} className="flex-1" />
                          <span
                            aria-hidden
                            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primarySoft text-primaryDark transition duration-base group-hover:translate-x-0.5 group-hover:bg-accent group-hover:text-ink"
                          >
                            <ArrowRight className="h-4 w-4" />
                          </span>
                        </div>
                      </div>
                    </Card>
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </>
  );
}
