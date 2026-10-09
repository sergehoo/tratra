"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CalendarCheck, CalendarDays, ChevronRight, MapPin, Plus, Search } from "lucide-react";
import { apiErrorMessage, get } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  DURATION,
  EmptyState,
  PageHeader,
  SkeletonList,
  StatusBadge,
} from "@/components/ds";
import { iconForCategory } from "@/lib/trades";
import type { Booking, Paginated } from "@/lib/types";
import { formatDateTimeShort } from "../_components/dates";

/** Délai d'apparition échelonné des cartes (dérivé de la durée « fast » du Design System). */
const STAGGER = DURATION.fast / 3;

export default function ClientHome() {
  const { user } = useAuth();
  const userId = user?.id;
  const [items, setItems] = useState<Booking[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // Compte unifié : /bookings/ renvoie aussi les missions reçues — on ne garde ici que mes réservations.
      const d = await get<Paginated<Booking>>(`/bookings/?client=${userId}`);
      setItems(d.results ?? []);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Vos réservations ne peuvent pas être chargées pour le moment."));
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageHeader
        title="Mes réservations"
        description="Suivez l’avancement de vos demandes et retrouvez les détails de chaque intervention."
        actions={
          <ButtonLink href="/dashboard/services" leftIcon={<Plus aria-hidden className="h-4 w-4" />}>
            Nouvelle demande
          </ButtonLink>
        }
      />

      {loading ? (
        <SkeletonList count={3} />
      ) : error ? (
        <Alert
          tone="danger"
          title="Chargement impossible"
          action={
            <Button size="sm" variant="outline" onClick={() => void load()}>
              Réessayer
            </Button>
          }
        >
          {error}
        </Alert>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<CalendarCheck aria-hidden />}
          title="Aucune réservation pour le moment"
          description="Vos réservations apparaîtront ici dès que vous aurez demandé une intervention à un artisan."
          actions={
            <ButtonLink href="/dashboard/services" leftIcon={<Search aria-hidden className="h-4 w-4" />}>
              Trouver un service
            </ButtonLink>
          }
        />
      ) : (
        <ul className="grid grid-cols-1 gap-3">
          {items.map((b, index) => {
            const title = b.service_detail?.title ?? `Réservation n° ${b.id}`;
            const when = formatDateTimeShort(b.booking_date);
            const artisan = b.handyman_detail?.first_name;
            const Icon = iconForCategory(b.service_detail?.category_detail?.slug);
            return (
              <li key={b.id} className="animate-rise" style={{ animationDelay: `${Math.min(index, 6) * STAGGER}s` }}>
                <Link
                  href={`/dashboard/bookings/${b.id}`}
                  className="group block rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                >
                  <Card interactive padding="none" className="flex items-center gap-4 p-4 sm:p-5">
                    <span
                      aria-hidden
                      className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-primarySoft text-primary transition-colors duration-base group-hover:bg-accent group-hover:text-ink"
                    >
                      <Icon className="h-6 w-6" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <h2 className="truncate font-display text-base font-bold leading-snug text-ink">{title}</h2>
                      <StatusBadge kind="booking" status={b.status} className="mt-1.5 sm:hidden" />
                      <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ash">
                        {when ? (
                          <span className="inline-flex items-center gap-1.5">
                            <CalendarDays aria-hidden className="h-4 w-4 shrink-0" />
                            {when}
                          </span>
                        ) : null}
                        {b.city ? (
                          <span className="inline-flex items-center gap-1.5">
                            <MapPin aria-hidden className="h-4 w-4 shrink-0" />
                            {b.city}
                          </span>
                        ) : null}
                        {artisan ? <span className="truncate">avec {artisan}</span> : null}
                      </p>
                    </div>
                    <div className="hidden shrink-0 items-center gap-3 sm:flex">
                      <StatusBadge kind="booking" status={b.status} />
                      <ChevronRight
                        aria-hidden
                        className="h-5 w-5 text-fog transition duration-base group-hover:translate-x-0.5 group-hover:text-primary"
                      />
                    </div>
                  </Card>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
