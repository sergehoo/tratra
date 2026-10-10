"use client";
import { useEffect, useRef, useState } from "react";
import { Skeleton } from "@/components/ds";
import { VerifyCard } from "@/components/trust/VerifyCard";
import { ApiError, post } from "@/lib/api";
import type { PassResult } from "@/lib/tratraId";

const REFUSAL: Record<string, string> = {
  unknown: "Ce QR ne correspond à aucune de vos réservations. Connectez-vous avec le compte qui a réservé.",
  used: "Ce QR a déjà été utilisé : l'identité de l'artisan a déjà été vérifiée.",
  expired: "Ce QR a expiré. Demandez à l'artisan d'en afficher un nouveau.",
  replaced: "Ce QR a été remplacé par un plus récent. Demandez à l'artisan de l'afficher à nouveau.",
  revoked: "Cet artisan n'est plus vérifié par Tratra. Ne le laissez pas intervenir et contactez le support.",
  booking_not_active: "Cette réservation n'est plus en cours.",
};

/** Le client scanne le QR de mission : l'identité de l'artisan est confirmée (une seule fois) pour SA réservation. */
export default function PassClient({ token }: { token: string }) {
  const [result, setResult] = useState<PassResult | null>(null);
  const [refusal, setRefusal] = useState<{ code: string; detail: string } | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // un seul envoi : le QR est à usage unique (StrictMode rejoue les effets)
    started.current = true;
    post<PassResult>("/verify/pass/", { token })
      .then(setResult)
      .catch((e) => {
        const data = e instanceof ApiError && e.data && typeof e.data === "object" ? (e.data as { code?: string; detail?: string }) : {};
        const code = data.code ?? "error";
        setRefusal({ code, detail: REFUSAL[code] ?? data.detail ?? "La vérification a échoué. Réessayez dans un instant." });
      });
  }, [token]);

  if (!result && !refusal) return <Skeleton className="h-72 w-full !rounded-card" />;
  if (result) {
    return (
      <VerifyCard tone="ok" title="Identité confirmée" message={result.message} holder={result.holder} tratraId={result.tratra_id}>
        <p className="text-sm text-inkSoft">
          Réservation #{result.booking_id}{result.service ? ` · ${result.service}` : ""} — vérifié le{" "}
          {new Date(result.verified_at).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" })}.
        </p>
      </VerifyCard>
    );
  }
  return <VerifyCard tone={refusal!.code === "revoked" ? "danger" : "warn"} title="Vérification refusée" message={refusal!.detail} />;
}
