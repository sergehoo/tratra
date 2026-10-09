"use client";
import { useCallback, useEffect, useState } from "react";
import { CalendarClock, ClipboardList, ShieldCheck, Wallet } from "lucide-react";
import { get, post } from "@/lib/api";
import {
  Alert,
  Button,
  ButtonLink,
  EmptyState,
  PageHeader,
  SkeletonList,
  SkeletonStats,
  Stat,
} from "@/components/ds";
import type { Booking, Paginated } from "@/lib/types";
import { MissionCard } from "./_components/MissionCard";
import { PresenceCard } from "./_components/PresenceCard";

export default function WorkerHome() {
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [available, setAvailable] = useState<string>("—");
  const [online, setOnline] = useState<boolean | null>(null);
  const [pending, setPending] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [bookingsFailed, setBookingsFailed] = useState(false);
  const [payoutFailed, setPayoutFailed] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setBookingsFailed(false);
    setPayoutFailed(false);
    Promise.all([
      get<Paginated<Booking>>("/bookings/")
        .then((d) => setBookings(d.results ?? []))
        .catch(() => setBookingsFailed(true)),
      get<{ available: string }>("/payouts/available/")
        .then((d) => setAvailable(d.available))
        .catch(() => setPayoutFailed(true)),
    ]).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function setPresence(value: boolean) {
    setMsg("");
    setPending(value);
    try {
      await post("/handymen/presence/", { online: value });
      setOnline(value);
    } catch {
      setMsg("Action impossible (profil non vérifié ?).");
    } finally {
      setPending(null);
    }
  }

  const upcoming = bookings.filter((b) => ["pending", "confirmed", "in_progress"].includes(b.status));
  // « — » tant que le montant n'est pas connu : jamais de « NaN FCFA » ni de zéro inventé.
  const gains = Number(available || 0);
  const gainsLabel = Number.isFinite(gains) ? `${gains.toLocaleString("fr-FR")} FCFA` : "—";

  return (
    <>
      <PageHeader
        eyebrow="Espace artisan"
        title="Tableau de bord"
        description="Vos missions, vos gains et votre disponibilité en un coup d’œil."
      />

      {loading ? (
        <SkeletonStats />
      ) : (
        <div className="grid animate-rise gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Stat
            icon={<CalendarClock className="h-6 w-6" />}
            label="Missions à venir"
            value={bookingsFailed ? "—" : upcoming.length}
            hint={bookingsFailed ? "Indisponible pour le moment" : "En attente, confirmées ou en cours"}
          />
          <Stat
            icon={<Wallet className="h-6 w-6" />}
            tone="accent"
            label="Gains disponibles"
            value={payoutFailed ? "—" : gainsLabel}
            hint={payoutFailed ? "Indisponible pour le moment" : undefined}
          />
          <PresenceCard
            className="sm:col-span-2 xl:col-span-1"
            online={online}
            pending={pending}
            error={msg}
            onChange={setPresence}
          />
        </div>
      )}

      <section aria-labelledby="missions-title" className="mt-8 sm:mt-10">
        <div className="mb-4 flex items-end justify-between gap-3">
          <h2 id="missions-title" className="font-display text-xl font-extrabold tracking-tight text-ink">
            Mes missions
          </h2>
        </div>

        {loading ? (
          <SkeletonList />
        ) : bookingsFailed ? (
          <Alert
            tone="danger"
            title="Impossible de charger vos missions"
            action={
              <Button size="sm" variant="outline" onClick={load}>
                Réessayer
              </Button>
            }
          >
            Vérifiez votre connexion puis réessayez.
          </Alert>
        ) : bookings.length === 0 ? (
          <EmptyState
            icon={<ClipboardList />}
            title="Aucune mission pour le moment"
            description="Dès qu’un client vous réserve, sa demande apparaît ici. Un profil vérifié peut se rendre disponible en ligne et être proposé aux clients."
            actions={
              <ButtonLink href="/worker/kyc" variant="soft" leftIcon={<ShieldCheck aria-hidden className="h-4 w-4" />}>
                Vérifier mon profil
              </ButtonLink>
            }
          />
        ) : (
          <div className="grid grid-cols-1 animate-rise gap-3">
            {bookings.map((b) => (
              <MissionCard key={b.id} booking={b} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}
