"use client";
import { useState } from "react";
import { Flag, MapPinned, Navigation } from "lucide-react";
import { Alert, Button, Card, CardHeader, Checkbox, ConfirmDialog } from "@/components/ds";
import { useGeoShare } from "@/lib/useGeoShare";
import { useLive } from "@/lib/useLive";
import { LivePanel } from "./LivePanel";

/**
 * Artisan : « Je suis en route » (consentement explicite au partage de position, jusqu'à l'arrivée), suivi de son
 * trajet et « Je suis arrivé ». Démarrer / terminer la mission reste géré par les boutons de la machine à états.
 */
export function ArtisanLiveControls({ bookingId, onChange }: { bookingId: number; onChange?: () => void }) {
  const live = useLive(bookingId);
  const s = live.state;
  const sharing = s?.artisan.sharing === true && s?.phase === "en_route";
  const geo = useGeoShare(sharing, live.sendPosition);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState<"start" | "arrive" | "pause" | null>(null);
  const [ack, setAck] = useState(false);

  if (!s) return live.error ? <Alert tone="danger">{live.error}</Alert> : null;
  if (!["confirmed", "en_route", "arrived"].includes(s.phase)) return null;

  async function act(kind: "start" | "arrive" | "pause") {
    setBusy(kind);
    if (kind === "start") await live.startRoute();
    else if (kind === "arrive") await live.arrive();
    else await live.setConsent(!sharing);
    setBusy(null);
    onChange?.();
  }

  return (
    <Card>
      <CardHeader icon={<MapPinned className="h-5 w-5" />} title="Trajet vers le client" description="Votre position n’est partagée que pendant le trajet, avec votre accord." />
      <LivePanel state={s} realtime={live.realtime} offline={live.offline} viewer="artisan" />

      <div className="mt-4 space-y-3">
        {s.can.start_route ? (
          <Button type="button" size="lg" block leftIcon={<Navigation aria-hidden className="h-4 w-4" />} onClick={() => setConfirm(true)} disabled={!s.window_open}>
            Je suis en route
          </Button>
        ) : null}
        {s.phase === "confirmed" && !s.window_open ? <p className="text-xs text-ash">Le suivi s’ouvre quelques heures avant l’heure prévue de l’intervention.</p> : null}

        {s.phase === "en_route" ? (
          <>
            {geo.status === "waiting" ? <p className="text-sm text-inkSoft">En attente du signal GPS…</p> : null}
            {geo.status === "denied" ? <Alert tone="warning" title="Position refusée">Autorisez la localisation dans les réglages du navigateur pour partager votre trajet. Vous pouvez tout de même indiquer votre arrivée.</Alert> : null}
            {geo.status === "unavailable" ? <Alert tone="warning">Signal GPS indisponible : le client ne voit pas votre position pour le moment.</Alert> : null}
            {geo.lastError ? <p className="text-xs text-ash">{geo.lastError}</p> : null}
            <Button type="button" variant="outline" block loading={busy === "pause"} onClick={() => act("pause")}>
              {sharing ? "Suspendre le partage de ma position" : "Reprendre le partage de ma position"}
            </Button>
          </>
        ) : null}

        {s.can.arrive ? (
          <Button type="button" size="lg" block variant={s.phase === "en_route" ? "primary" : "outline"} loading={busy === "arrive"} leftIcon={<Flag aria-hidden className="h-4 w-4" />} onClick={() => act("arrive")}>
            Je suis arrivé
          </Button>
        ) : null}
      </div>
      {live.error ? <Alert tone="danger" className="mt-4">{live.error}</Alert> : null}

      <ConfirmDialog
        open={confirm}
        onClose={() => {
          setConfirm(false);
          setAck(false);
        }}
        onConfirm={async () => {
          setConfirm(false);
          await act("start");
          setAck(false);
        }}
        title="Partager ma position avec le client ?"
        description="Le client verra votre position et l’heure d’arrivée estimée pendant votre trajet. Le partage s’arrête automatiquement à votre arrivée, et vous pouvez le suspendre à tout moment."
        confirmLabel="Accepter et partir"
        cancelLabel="Annuler"
        confirmDisabled={!ack}
      >
        <Checkbox label="J’accepte de partager ma position avec le client jusqu’à mon arrivée." checked={ack} onChange={(e) => setAck(e.target.checked)} />
      </ConfirmDialog>
    </Card>
  );
}
