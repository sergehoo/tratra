"use client";
import { useState } from "react";
import { Button } from "@/components/ds";
import { VerifyCard } from "@/components/trust/VerifyCard";
import { verifyContractFile, type ContractVerification } from "@/lib/contractVerify";

const TONE = { authentic: "ok", superseded: "warn", key_revoked: "warn", revoked: "danger", altered: "danger", invalid_signature: "danger", unknown: "danger" } as const;
const TITLE: Record<string, string> = {
  authentic: "Document authentique",
  superseded: "Version remplacée",
  key_revoked: "Scellement à renouveler",
  revoked: "Document révoqué",
  altered: "Document altéré",
  invalid_signature: "Scellement invalide",
  unknown: "Document inconnu",
};

function date(value?: string | null) {
  return value ? new Date(value).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" }) : "—";
}

/** Résultat d'une vérification de contrat : décision lisible, puis référence, empreinte et scellement (jamais de nom ni de montant). */
export function ContractVerifyResult({ result }: { result: ContractVerification }) {
  const tone = TONE[result.state] ?? "danger";
  return (
    <VerifyCard tone={tone} title={TITLE[result.state] ?? "Vérification"} message={result.label}>
      {result.reference ? (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-[max-content_1fr]">
          <dt className="text-ash">Référence</dt>
          <dd className="font-mono font-semibold text-ink">{result.reference}</dd>
          <dt className="text-ash">Nature</dt>
          <dd className="text-ink">{result.nature}</dd>
          <dt className="text-ash">Document</dt>
          <dd className="text-ink">
            {result.kind === "amendment" ? "Avenant" : result.stage === "final" ? "Contrat signé" : "Version soumise à signature"} · version{" "}
            {result.version} · émis le {date(result.issued_at)}
          </dd>
          <dt className="text-ash">Statut du contrat</dt>
          <dd className="text-ink">{result.contract_status}</dd>
          <dt className="text-ash">Empreinte SHA-256</dt>
          <dd className="break-all font-mono text-xs text-ink">{result.sha256}</dd>
          <dt className="text-ash">Scellement Tratra</dt>
          <dd className="text-ink">
            {result.seal?.valid ? "valide" : "invalide"} ({result.seal?.algorithm}, clé {result.seal?.kid}
            {result.seal?.key_status && result.seal.key_status !== "active" ? `, ${result.seal.key_status}` : ""})
          </dd>
          {result.stage === "final" ? (
            <>
              <dt className="text-ash">Signatures des parties</dt>
              <dd className="text-ink">{result.parties_signed ? "les deux parties ont signé (signature électronique simple)" : "incomplètes"}</dd>
            </>
          ) : null}
          {result.superseded_by ? (
            <>
              <dt className="text-ash">Remplacé par</dt>
              <dd className="font-mono text-ink">{result.superseded_by}</dd>
            </>
          ) : null}
          {result.revoked_at ? (
            <>
              <dt className="text-ash">Révoqué le</dt>
              <dd className="text-ink">{date(result.revoked_at)}</dd>
            </>
          ) : null}
        </dl>
      ) : null}
      {result.amendments?.length ? (
        <div className="space-y-1">
          <p className="text-sm font-semibold text-ink">Avenants</p>
          <ul className="space-y-1 text-xs text-inkSoft">
            {result.amendments.map((a) => (
              <li key={a.reference}>
                <span className="font-mono text-ink">{a.reference}</span> · {date(a.issued_at)}
                {a.revoked ? " · révoqué" : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-xs text-ash">
        Aucune donnée personnelle n’est affichée. Le scellement Tratra prouve l’origine et l’intégrité du document ; il ne remplace pas une
        signature électronique qualifiée.
      </p>
    </VerifyCard>
  );
}

/** Contrôle d'un PDF reçu : son empreinte est calculée par le serveur et comparée aux documents émis par Tratra. */
export function PdfCheck({ expectedReference }: { expectedReference?: string }) {
  const [state, setState] = useState<"idle" | "checking" | "error">("idle");
  const [result, setResult] = useState<ContractVerification | null>(null);

  async function check(file: File | undefined) {
    if (!file) return;
    setState("checking");
    setResult(null);
    const r = await verifyContractFile(file).catch(() => null);
    setState(r ? "idle" : "error");
    setResult(r);
  }

  const mismatch = result && result.match && expectedReference && result.reference && !result.reference.startsWith(expectedReference.split("-AV")[0]);
  return (
    <div className="space-y-3">
      <label className="block text-sm font-semibold text-ink" htmlFor="contract-pdf">
        Vérifier un PDF reçu
      </label>
      <p className="text-xs text-ash">Le fichier n’est pas conservé : seule son empreinte est comparée aux documents émis par Tratra.</p>
      <input
        id="contract-pdf"
        type="file"
        accept="application/pdf,.pdf"
        onChange={(e) => check(e.target.files?.[0])}
        className="block w-full text-sm text-inkSoft file:mr-3 file:rounded-full file:border-0 file:bg-primarySoft file:px-4 file:py-2 file:font-semibold file:text-primary"
      />
      {state === "checking" ? <p className="text-sm text-inkSoft">Vérification en cours…</p> : null}
      {state === "error" ? (
        <p role="alert" className="text-sm text-danger">
          Vérification impossible pour le moment. Réessayez dans un instant.
        </p>
      ) : null}
      {result && result.match === false ? (
        <VerifyCard
          tone="danger"
          title="Fichier non reconnu"
          message={result.label || "Aucun document Tratra ne correspond exactement à ce fichier : il a pu être modifié."}
        />
      ) : null}
      {result && result.match ? <ContractVerifyResult result={result} /> : null}
      {mismatch ? (
        <p role="alert" className="text-sm text-danger">
          Ce fichier appartient à un autre contrat que celui du QR code.
        </p>
      ) : null}
      <Button variant="ghost" size="sm" onClick={() => setResult(null)} disabled={!result}>
        Effacer le résultat
      </Button>
    </div>
  );
}
