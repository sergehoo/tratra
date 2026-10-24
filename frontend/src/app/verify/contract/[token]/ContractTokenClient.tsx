"use client";
import { useEffect, useState } from "react";
import { Card, Skeleton } from "@/components/ds";
import { VerifyCard } from "@/components/trust/VerifyCard";
import { verifyContractToken, type ContractVerification } from "@/lib/contractVerify";
import { ContractVerifyResult, PdfCheck } from "../ContractVerifyResult";

/** Vérification d'un contrat par son QR code : l'état est recalculé par le serveur à chaque ouverture. */
export default function ContractTokenClient({ token }: { token: string }) {
  const [result, setResult] = useState<ContractVerification | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    verifyContractToken(token, controller.signal)
      .then((r) => (r ? setResult(r) : setFailed(true)))
      .catch((e) => {
        if (e?.name !== "AbortError") setFailed(true);
      });
    return () => controller.abort();
  }, [token]);

  if (failed) {
    return (
      <VerifyCard
        tone="warn"
        title="Vérification impossible"
        message="Le service de vérification ne répond pas. Vérifiez votre connexion puis rechargez la page — ne vous fiez pas à un document non vérifié."
      />
    );
  }
  if (!result) return <Skeleton className="h-72 w-full !rounded-card" />;
  return (
    <div className="space-y-6">
      <ContractVerifyResult result={result} />
      {result.reference ? (
        <Card padding="lg">
          <PdfCheck expectedReference={result.reference} />
        </Card>
      ) : null}
    </div>
  );
}
