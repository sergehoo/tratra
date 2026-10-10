"use client";
import { useState } from "react";
import { MapPinned, ShieldCheck } from "lucide-react";
import { Alert, Button, Card, CardHeader, Checkbox } from "@/components/ds";
import { useGeoShare } from "@/lib/useGeoShare";
import { useLive } from "@/lib/useLive";
import { LivePanel } from "./LivePanel";

/**
 * Client : suivre l'arrivée de l'artisan en direct. Le partage de SA position est facultatif, explicite et
 * retirable à tout moment (les positions déjà envoyées sont alors effacées).
 */
export function LiveTrackingCard({ bookingId }: { bookingId: number }) {
  const live = useLive(bookingId);
  const s = live.state;
  const sharing = s?.client.sharing === true;
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const geo = useGeoShare(sharing, live.sendPosition);

  if (!s) {
    return live.error ? <Alert tone="danger">{live.error}</Alert> : null;
  }
  if (!["confirmed", "en_route", "arrived", "in_progress"].includes(s.phase)) return null;

  async function toggle(next: boolean) {
    setBusy(true);
    await live.setConsent(next);
    setBusy(false);
  }

  return (
    <Card>
      <CardHeader icon={<MapPinned className="h-5 w-5" />} title="Suivi de l’artisan" description="Position et heure d’arrivée en direct pendant son trajet." />
      {s.phase === "confirmed" ? (
        <p className="mb-4 text-sm text-inkSoft">L’artisan n’a pas encore démarré son trajet. Vous serez notifié dès qu’il sera en route.</p>
      ) : null}
      {s.phase === "in_progress" ? <p className="mb-4 text-sm text-inkSoft">L’intervention est en cours : le suivi de position est terminé.</p> : null}
      <LivePanel state={s} realtime={live.realtime} offline={live.offline} viewer="client" />

      {s.can.share_position ? (
        <div className="mt-5 space-y-3 rounded-panel border border-lineSoft p-4">
          <p className="flex items-center gap-2 text-sm font-bold text-ink"><ShieldCheck aria-hidden className="h-4 w-4 text-primary" /> Partager ma position (facultatif)</p>
          {sharing ? (
            <>
              <p className="text-sm text-inkSoft">
                Votre position est partagée avec l’artisan jusqu’à son arrivée.
                {geo.status === "waiting" ? " En attente du signal GPS…" : ""}
              </p>
              {geo.status === "denied" ? <Alert tone="warning">L’accès à votre position est refusé par le navigateur : autorisez-le dans les réglages du site.</Alert> : null}
              {geo.status === "unavailable" ? <Alert tone="warning">Votre position est introuvable (signal GPS indisponible).</Alert> : null}
              {geo.lastError ? <p className="text-xs text-ash">{geo.lastError}</p> : null}
              <Button type="button" variant="outline" size="sm" loading={busy} onClick={() => toggle(false)}>
                Arrêter le partage et effacer mes positions
              </Button>
            </>
          ) : (
            <>
              <p className="text-sm text-inkSoft">
                Aide l’artisan à vous trouver et affine l’heure d’arrivée. Votre position n’est visible que de lui, uniquement avant son arrivée, et vous pouvez l’arrêter à tout moment.
              </p>
              <Checkbox label="J’accepte de partager ma position avec l’artisan jusqu’à son arrivée." checked={ack} onChange={(e) => setAck(e.target.checked)} />
              <Button type="button" size="sm" disabled={!ack} loading={busy} onClick={() => toggle(true)}>
                Partager ma position
              </Button>
            </>
          )}
        </div>
      ) : null}
      {live.error ? <Alert tone="danger" className="mt-4">{live.error}</Alert> : null}
    </Card>
  );
}
