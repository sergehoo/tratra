"use client";
import { useState } from "react";
import { FileDown, PenLine, ScrollText, ShieldCheck } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, Checkbox } from "@/components/ds";
import { apiErrorMessage, privateFileUrl } from "@/lib/api";
import { dateTimeFr, eng, type ContractDetail, type SealedDocument } from "@/lib/engagements";
import { useIntent } from "../../../_components/common";

const STAGE_FR = { for_signature: "Version à signer", final: "Contrat signé" } as const;

async function openPdf(doc: SealedDocument, setError: (m: string) => void) {
  setError("");
  try {
    const url = await privateFileUrl(doc.download);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${doc.reference}-v${doc.version}.pdf`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (e) {
    setError(apiErrorMessage(e, "Document indisponible."));
  }
}

/** Signature électronique SIMPLE d'une partie sur le document à signer (distincte du scellement numérique de Tratra). */
export function SignCard({ c, onChanged }: { c: ContractDetail; onChanged: () => void }) {
  const intent = useIntent("sign");
  const [read, setRead] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const doc = [...c.documents].reverse().find((d) => d.kind === "contract" && d.stage === "for_signature" && d.version === c.terms_version && !d.revoked_at);
  const mine = c.signatures?.[c.my_role];
  const theirs = c.signatures?.[c.my_role === "worker" ? "principal" : "worker"];
  if (!c.signature_required || c.status !== "accepted") return null;
  if (mine) {
    return (
      <Alert tone="info" className="mb-6" title="Vous avez signé" icon={<PenLine />}>
        Signé le {dateTimeFr(mine)}. {theirs ? "" : `${c.counterpart.name} doit encore signer : vous serez prévenu(e).`}
      </Alert>
    );
  }
  async function sign() {
    setBusy(true);
    setError("");
    try {
      await eng.post(`/contracts/${c.id}/sign/`, { consent: true }, intent.key({ v: c.terms_version }));
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Signature impossible. Rien n’a été enregistré."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card variant="accent" padding="md" className="mb-6">
      <CardHeader title="Contrat à signer" icon={<PenLine className="h-5 w-5" />}
        description={`Les conditions sont acceptées par les deux parties. Lisez le document ${c.reference ?? ""} puis signez : votre signature porte sur ce fichier exact.`} />
      {doc ? (
        <Button variant="outline" size="sm" leftIcon={<FileDown aria-hidden className="h-4 w-4" />} onClick={() => void openPdf(doc, setError)}>
          Télécharger le document à signer (PDF)
        </Button>
      ) : null}
      <div className="mt-4">
        <Checkbox checked={read} onChange={(e) => setRead(e.target.checked)}
          label={`J’ai lu le contrat ${c.reference ?? ""} (version ${c.terms_version}) et je le signe électroniquement.`} />
      </div>
      <p className="mt-2 text-xs text-ash">
        Signature électronique simple : votre compte, la date, l’heure et l’empreinte du document sont enregistrés. Une fois les deux signatures
        posées, Tratra émet le contrat final, scellé numériquement et vérifiable par son QR code.
      </p>
      {theirs ? <p className="mt-2 text-xs text-inkSoft">{c.counterpart.name} a déjà signé le {dateTimeFr(theirs)}.</p> : null}
      {error ? <Alert tone="danger" className="mt-3">{error}</Alert> : null}
      <div className="mt-4">
        <Button disabled={!read} loading={busy} onClick={() => void sign()}>Signer le contrat</Button>
      </div>
    </Card>
  );
}

/** Articles figés à la proposition (modèle validé par revue juridique) : le texte exact accepté puis signé. */
export function ArticlesCard({ c }: { c: ContractDetail }) {
  if (!c.articles?.length) return null;
  return (
    <Card padding="md" className="mt-6">
      <CardHeader title="Articles du contrat" icon={<ScrollText className="h-5 w-5" />}
        description={c.template ? `Modèle « ${c.template.title} » (version ${c.template.version}) — ${c.template.status_label.toLowerCase()}.` : undefined} />
      <ol className="space-y-4">
        {c.articles.map((a) => (
          <li key={a.number}>
            <h3 className="text-sm font-bold text-ink">Article {a.number} — {a.title}</h3>
            <p className="mt-1 whitespace-pre-line text-sm text-inkSoft">{a.body}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** Documents scellés : référence, empreinte SHA-256, téléchargement (parties seulement). Le QR code de chaque PDF permet à n'importe qui de
 *  vérifier son authenticité, sans donnée personnelle. */
export function DocumentsCard({ c }: { c: ContractDetail }) {
  const [error, setError] = useState("");
  if (!c.documents?.length) return null;
  return (
    <Card padding="md" className="mt-6">
      <CardHeader title="Documents scellés" icon={<ShieldCheck className="h-5 w-5" />}
        description="Chaque document porte une référence unique, un QR code de vérification publique et le scellement numérique de Tratra. Un avenant produit un nouveau document : l’original n’est jamais modifié." />
      <ul className="divide-y divide-line">
        {c.documents.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="min-w-0">
              <p className="font-mono text-sm font-semibold text-ink">{d.reference}</p>
              <p className="text-xs text-ash">
                {d.kind === "amendment" ? "Avenant" : STAGE_FR[d.stage]} · version {d.version} · émis le {dateTimeFr(d.issued_at)}
              </p>
              <p className="break-all font-mono text-[11px] text-ash">SHA-256 {d.sha256}</p>
              {d.revoked_at ? <Badge tone="danger">Révoqué : {d.revoked_reason}</Badge> : null}
            </div>
            <Button size="sm" variant="outline" leftIcon={<FileDown aria-hidden className="h-4 w-4" />} onClick={() => void openPdf(d, setError)}>
              PDF
            </Button>
          </li>
        ))}
      </ul>
      {error ? <Alert tone="danger" className="mt-3">{error}</Alert> : null}
    </Card>
  );
}
