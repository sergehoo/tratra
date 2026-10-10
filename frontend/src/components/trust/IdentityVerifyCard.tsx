"use client";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ScanLine } from "lucide-react";
import { Alert, Button, Card, CardHeader, TextField } from "@/components/ds";
import { ApiError, get, post } from "@/lib/api";
import { tokenFromInput, type BookingIdentity, type PassResult } from "@/lib/tratraId";
import { VerifyCard } from "./VerifyCard";

/**
 * Client : vérifier l'identité de l'artisan à son arrivée. Le plus simple : scanner son QR de mission avec
 * l'appareil photo du téléphone (ouvre la vérification) ; à défaut, coller ici le lien ou le code du QR.
 */
export function IdentityVerifyCard({ bookingId, active }: { bookingId: number; active: boolean }) {
  const [identity, setIdentity] = useState<BookingIdentity | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PassResult | null>(null);

  const load = useCallback(() => get<BookingIdentity>(`/bookings/${bookingId}/identity/`).then(setIdentity).catch(() => undefined), [bookingId]);
  useEffect(() => { void load(); }, [load]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const token = tokenFromInput(value);
    if (!token) return setError("Collez le lien ou le code affiché sous le QR de l’artisan.");
    setBusy(true);
    setError("");
    try {
      setResult(await post<PassResult>("/verify/pass/", { token }));
      setValue("");
      void load();
    } catch (err) {
      const data = err instanceof ApiError && err.data && typeof err.data === "object" ? (err.data as { detail?: string }) : {};
      setError(data.detail ?? "La vérification a échoué. Réessayez dans un instant.");
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return <VerifyCard tone="ok" title="Identité confirmée" message={result.message} holder={result.holder} tratraId={result.tratra_id} />;
  }
  return (
    <Card>
      <CardHeader icon={<ScanLine className="h-5 w-5" />} title="Vérifier l’artisan à son arrivée" description="Confirmez que la personne présente est bien l’artisan de cette réservation." />
      {identity?.verified ? (
        <Alert tone="success" title="Identité déjà confirmée">
          {identity.verified_at ? new Date(identity.verified_at).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" }) : null}
        </Alert>
      ) : !active ? (
        <p className="text-sm text-ash">La vérification est disponible lorsque la réservation est confirmée ou en cours.</p>
      ) : (
        <form onSubmit={submit} className="space-y-3" noValidate>
          <p className="text-sm text-inkSoft">
            Demandez à l’artisan d’afficher son <strong>QR de mission</strong>, puis scannez-le avec l’appareil photo de votre téléphone ou l’application Tratra.
          </p>
          <TextField label="Lien ou code du QR (si vous ne pouvez pas scanner)" optional value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button type="submit" block loading={busy} disabled={!value.trim()}>
            Vérifier l’artisan
          </Button>
        </form>
      )}
    </Card>
  );
}
