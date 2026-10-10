"use client";
import { CircleCheck, CircleDot, MapPin, Navigation, Timer, WifiOff } from "lucide-react";
import { Alert, Badge } from "@/components/ds";
import { ageLabel, formatDistance, formatEta, type LivePhase, type LiveState } from "@/lib/live";
import dynamic from "next/dynamic";

const LiveMap = dynamic(() => import("./LiveMap").then((m) => m.LiveMap), {
  ssr: false,
  loading: () => <div className="h-72 w-full animate-pulse rounded-panel bg-lineSoft" aria-hidden />,
});

const STEPS: { phase: LivePhase; label: string }[] = [
  { phase: "confirmed", label: "Confirmée" },
  { phase: "en_route", label: "En route" },
  { phase: "arrived", label: "Arrivé" },
  { phase: "in_progress", label: "En cours" },
  { phase: "completed", label: "Terminée" },
];

/** Frise des jalons : les statuts de la réservation + « en route » et « arrivé » (jalons du suivi). */
export function LiveSteps({ phase }: { phase: LivePhase }) {
  if (phase === "cancelled") return <Badge tone="danger">Annulée</Badge>;
  const idx = STEPS.findIndex((s) => s.phase === phase);
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2" aria-label="Avancement de la mission">
      {STEPS.map((s, i) => {
        const done = i < idx || phase === "completed";
        const active = i === idx && phase !== "completed";
        return (
          <li key={s.phase} aria-current={active ? "step" : undefined} className="flex items-center gap-1">
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${
                active ? "bg-accent text-ink" : done ? "bg-primarySoft text-primaryDark" : "bg-lineSoft text-ash"
              }`}
            >
              {done ? <CircleCheck aria-hidden className="h-3.5 w-3.5" /> : <CircleDot aria-hidden className="h-3.5 w-3.5" />}
              {s.label}
              <span className="sr-only">{done ? " (terminé)" : active ? " (en cours)" : " (à venir)"}</span>
            </span>
            {i < STEPS.length - 1 ? <span aria-hidden className="h-px w-3 bg-line" /> : null}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Carte, ETA, distance et alertes d'un suivi. Honnête : rien n'est affiché sans donnée reçue ; une position ancienne
 * est signalée comme telle ; l'ETA indique s'il s'agit d'une estimation à vol d'oiseau.
 */
export function LivePanel({ state, realtime, offline, viewer }: { state: LiveState; realtime: boolean; offline: boolean; viewer: "client" | "artisan" }) {
  const artisan = state.artisan.position;
  const client = state.client.position;
  const route = state.route;
  // Pas de carte vide : elle n'apparaît que s'il y a au moins un repère réel à y placer.
  const showMap = Boolean(artisan || client || state.destination);
  const lost = artisan?.stale === true;
  return (
    <div className="space-y-4">
      <LiveSteps phase={state.phase} />

      {offline ? (
        <Alert tone="warning" icon={<WifiOff aria-hidden className="h-4 w-4" />} title="Connexion perdue">
          Le suivi reprendra automatiquement dès que le réseau sera de retour.
        </Alert>
      ) : null}

      {state.phase === "en_route" ? (
        <>
          {route ? (
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-panel bg-canvas p-3">
                <p className="flex items-center gap-1.5 text-xs font-semibold text-ash"><Timer aria-hidden className="h-4 w-4 text-primary" /> Arrivée estimée</p>
                <p className="mt-1 font-display text-2xl font-bold text-ink">{formatEta(route.eta_minutes)}</p>
              </div>
              <div className="rounded-panel bg-canvas p-3">
                <p className="flex items-center gap-1.5 text-xs font-semibold text-ash"><Navigation aria-hidden className="h-4 w-4 text-primary" /> Distance</p>
                <p className="mt-1 font-display text-2xl font-bold text-ink">{formatDistance(route.distance_m)}</p>
              </div>
              <p className="col-span-2 text-xs text-ash">
                {route.source === "osrm" ? "Itinéraire routier calculé." : "Estimation à vol d’oiseau (vitesse moyenne urbaine) : le trajet réel peut différer."}
              </p>
            </div>
          ) : (
            <p className="rounded-panel bg-canvas p-3 text-sm text-inkSoft">
              {artisan
                ? "Le lieu d’intervention n’est pas localisé : la distance et l’heure d’arrivée ne peuvent pas être calculées."
                : viewer === "client"
                  ? "L’artisan est en route. Sa position apparaîtra dès qu’il la partage."
                  : "Partage de votre position en attente de la première mesure."}
            </p>
          )}
          {lost && artisan ? (
            <Alert tone="warning" title="Position ancienne">
              Dernière position reçue {ageLabel(artisan.age_seconds)}. Elle n’est plus à jour (réseau ou GPS de l’artisan).
            </Alert>
          ) : null}
          {viewer === "client" && !state.artisan.sharing ? (
            <Alert tone="info">L’artisan a suspendu le partage de sa position. Il reste en route.</Alert>
          ) : null}
        </>
      ) : null}

      {state.phase === "arrived" ? (
        <Alert tone="success" title={viewer === "client" ? "Votre artisan est arrivé" : "Arrivée enregistrée"}>
          {viewer === "client" ? "Vérifiez son identité avec le QR de mission avant de commencer." : "Le partage de position est arrêté."}
        </Alert>
      ) : null}

      {showMap ? (
        <>
          <LiveMap artisan={artisan} client={client} destination={state.destination} route={route?.polyline ?? null} />
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ash">
            <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-full bg-primary" /> Artisan</span>
            <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-full bg-accent" /> Client</span>
            <span className="inline-flex items-center gap-1.5"><MapPin aria-hidden className="h-3.5 w-3.5" /> Lieu d’intervention</span>
            <span className="ml-auto">{realtime ? "Temps réel actif" : "Actualisation toutes les 5 s"}</span>
          </p>
        </>
      ) : null}
    </div>
  );
}
