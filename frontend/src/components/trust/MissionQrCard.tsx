"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { QrCode, RefreshCw } from "lucide-react";
import { Alert, Button, Card, CardHeader } from "@/components/ds";
import { ApiError, get, post } from "@/lib/api";
import type { BookingIdentity, MissionPass } from "@/lib/tratraId";

function clock(seconds: number): string {
  const s = Math.max(0, seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Artisan : QR de mission TEMPORAIRE (15 min, usage unique) à montrer au client à l'arrivée. L'écran suit en
 * direct la confirmation par le client ; aucune donnée sensible n'est encodée dans le QR.
 */
export function MissionQrCard({ bookingId }: { bookingId: number }) {
  const [pass, setPass] = useState<MissionPass | null>(null);
  const [identity, setIdentity] = useState<BookingIdentity | null>(null);
  const [left, setLeft] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);

  const refreshIdentity = useCallback(() => get<BookingIdentity>(`/bookings/${bookingId}/identity/`).then(setIdentity).catch(() => undefined), [bookingId]);
  useEffect(() => { void refreshIdentity(); }, [refreshIdentity]);

  // Compte à rebours et suivi de la confirmation tant que le QR est affiché.
  useEffect(() => {
    if (!pass) return;
    const end = new Date(pass.expires_at).getTime();
    const tick = () => setLeft(Math.max(0, Math.round((end - Date.now()) / 1000)));
    tick();
    timer.current = window.setInterval(() => {
      tick();
      void refreshIdentity();
    }, 3000);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [pass, refreshIdentity]);

  async function show() {
    setBusy(true);
    setError("");
    try {
      setPass(await post<MissionPass>(`/bookings/${bookingId}/identity-pass/`));
    } catch (e) {
      const data = e instanceof ApiError && e.data && typeof e.data === "object" ? (e.data as { detail?: string }) : {};
      setError(data.detail ?? "Le QR de mission n’a pas pu être généré. Réessayez dans un instant.");
    } finally {
      setBusy(false);
    }
  }

  const verified = identity?.verified === true;
  const expired = pass != null && left === 0;
  return (
    <Card>
      <CardHeader
        icon={<QrCode className="h-5 w-5" />}
        title="Identité à l’arrivée"
        description="Montrez ce QR au client : il confirme que vous êtes bien l’artisan attendu pour cette mission."
      />
      {verified ? (
        <Alert tone="success" title="Identité confirmée par le client">
          {identity?.verified_at ? new Date(identity.verified_at).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" }) : null}
        </Alert>
      ) : pass && !expired ? (
        <div className="space-y-3 text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={pass.qr} alt="QR de mission Tratra" className="mx-auto h-56 w-56 rounded-panel border border-lineSoft bg-white p-2" />
          <p className="text-sm text-inkSoft">Valable encore <strong className="text-ink">{clock(left)}</strong> · à usage unique</p>
          <Button type="button" variant="outline" size="sm" leftIcon={<RefreshCw aria-hidden className="h-4 w-4" />} loading={busy} onClick={show}>
            Générer un nouveau QR
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          {expired ? <Alert tone="warning">Ce QR a expiré. Générez-en un nouveau.</Alert> : null}
          <Button type="button" block size="lg" loading={busy} leftIcon={<QrCode aria-hidden className="h-4 w-4" />} onClick={show}>
            Afficher mon QR de mission
          </Button>
        </div>
      )}
      {error ? <Alert tone="danger" className="mt-4">{error}</Alert> : null}
    </Card>
  );
}
