"use client";
import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ds";
import { VerifyCard } from "@/components/trust/VerifyCard";
import { publicUrl } from "@/lib/public";
import type { PublicVerification } from "@/lib/tratraId";

/** Vérifie en direct un QR permanent Tratra ID. La validité est recalculée par le serveur à chaque ouverture. */
export default function VerifyIdClient({ code }: { code: string }) {
  const [result, setResult] = useState<PublicVerification | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(publicUrl(`/verify/id/${encodeURIComponent(code)}/`), {
      headers: { Accept: "application/json" },
      credentials: "omit",
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (r) => {
        // 200 (actif / révoqué) et 404 (inconnu) portent la même forme de réponse.
        if (r.status === 200 || r.status === 404) setResult((await r.json()) as PublicVerification);
        else setFailed(true);
      })
      .catch((e) => {
        if (e?.name !== "AbortError") setFailed(true);
      });
    return () => controller.abort();
  }, [code]);

  if (failed) {
    return (
      <VerifyCard
        tone="warn"
        title="Vérification impossible"
        message="Le service de vérification ne répond pas. Vérifiez votre connexion puis rechargez la page — ne faites pas confiance à un badge non vérifié."
      />
    );
  }
  if (!result) return <Skeleton className="h-72 w-full !rounded-card" />;
  if (result.valid && result.holder) {
    return <VerifyCard tone="ok" title="Professionnel vérifié par Tratra" message={result.message} holder={result.holder} tratraId={result.tratra_id} />;
  }
  return (
    <VerifyCard
      tone="danger"
      title={result.status === "revoked" ? "Badge révoqué" : "Badge inconnu"}
      message={result.message}
      tratraId={result.status === "revoked" ? result.tratra_id : undefined}
    />
  );
}
