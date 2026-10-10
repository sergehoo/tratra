"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Bot, Check, Clock, X } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, ConfirmDialog, EmptyState, PageHeader, SkeletonPage, TextareaField } from "@/components/ds";
import { TrustBadges } from "@/components/trust/TrustBadge";
import { apiErrorMessage, post } from "@/lib/api";
import { money, shortDate, useBusiness, useOrgData, type BizRequest, type Suggestion } from "@/lib/business";
import { PriorityPill, StatusPill } from "@/components/business/ui";

const ICON = { approved: Check, rejected: X, pending: Clock } as const;
const TONE = { approved: "text-success", rejected: "text-danger", pending: "text-ash" } as const;

export default function RequestDetail() {
  const { id } = useParams<{ id: string }>();
  const { org, can, path } = useBusiness();
  const { data: r, loading, error, reload } = useOrgData<BizRequest>(`requests/${id}/`, "Cette demande est introuvable ou inaccessible.");
  const canDispatch = can("requests.dispatch");
  const sugg = useOrgData<{ results: Suggestion[] }>(r && canDispatch && r.status === "approved" ? `requests/${id}/suggestions/` : null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState("");
  const [failure, setFailure] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);

  async function act(key: string, sub: string, body?: unknown) {
    setBusy(key);
    setFailure("");
    try {
      await post(path(`requests/${id}/${sub}`), body);
      await reload();
    } catch (e) {
      setFailure(apiErrorMessage(e, "L’action a échoué."));
    } finally {
      setBusy("");
    }
  }

  if (loading) return <SkeletonPage />;
  if (!r) return <><PageHeader title="Demande" back={{ href: "/dashboard/business/requests", label: "Demandes" }} /><EmptyState title="Demande introuvable" description={error || "Elle n’existe pas ou n’est pas accessible avec votre rôle."} /></>;
  const cur = org?.currency;
  const cancellable = ["pending_approval", "approved", "dispatched", "scheduled"].includes(r.status);
  return (
    <>
      <PageHeader eyebrow={r.number} title={r.title} back={{ href: "/dashboard/business/requests", label: "Demandes" }} actions={<span className="flex items-center gap-2"><PriorityPill priority={r.priority} /><StatusPill status={r.status} /></span>} />
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 lg:items-start">
        <div className="space-y-6 lg:col-span-2">
          <Card as="section" aria-label="Détails">
            <CardHeader title="Détails" />
            <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <div><dt className="text-xs text-ash">Site</dt><dd className="font-medium text-ink">{r.site_name}</dd></div>
              <div><dt className="text-xs text-ash">Équipement</dt><dd className="font-medium text-ink">{r.equipment_name ?? "—"}</dd></div>
              <div><dt className="text-xs text-ash">Métier</dt><dd className="font-medium text-ink">{r.category_name ?? "Non précisé"}</dd></div>
              <div><dt className="text-xs text-ash">Demandeur</dt><dd className="font-medium text-ink">{r.requested_by_name}</dd></div>
              <div><dt className="text-xs text-ash">Coût estimé</dt><dd className="font-medium text-ink">{money(r.estimated_cost, cur)}</dd></div>
              <div><dt className="text-xs text-ash">Coût réel</dt><dd className="font-medium text-ink">{money(r.cost, cur)}</dd></div>
              <div><dt className="text-xs text-ash">Échéance de prise en charge</dt><dd className="font-medium text-ink">{shortDate(r.sla.due_response_at)}{r.sla.response_met === false ? " · dépassée" : r.sla.response_met ? " · tenue" : ""}</dd></div>
              <div><dt className="text-xs text-ash">Échéance de résolution</dt><dd className="font-medium text-ink">{shortDate(r.sla.due_resolution_at)}{r.sla.resolution_met === false ? " · dépassée" : r.sla.resolution_met ? " · tenue" : ""}</dd></div>
            </dl>
            {r.description ? <p className="mt-4 whitespace-pre-line rounded-panel bg-canvas p-3 text-sm text-inkSoft">{r.description}</p> : null}
            {r.rejection_reason ? <Alert tone="danger" className="mt-4" title="Motif du refus">{r.rejection_reason}</Alert> : null}
            {r.booking_id ? <p className="mt-4 text-sm text-inkSoft">Mission confiée à un artisan (réservation n° {r.booking_id}) : son avancement met à jour cette demande.</p> : null}
          </Card>

          {r.budget_warnings.length ? (
            <Alert tone="warning" title="Budget dépassé si cette demande est réalisée">
              {r.budget_warnings.map((w) => <span key={w.budget_id} className="block">{w.name} : {money(w.projected, cur)} prévus pour {money(w.amount, cur)} alloués.</span>)}
            </Alert>
          ) : null}

          {canDispatch && r.status === "approved" ? (
            <Card as="section" aria-label="Affectation">
              <CardHeader icon={<Bot className="h-5 w-5" />} title="Choisir l’artisan" description="Artisans vérifiés uniquement, classés selon le contrat, la proximité, la confiance et la disponibilité." action={<Button size="sm" variant="outline" loading={busy === "auto"} disabled={!sugg.data?.results.length} onClick={() => act("auto", "dispatch/", { auto: true })}>Affectation automatique</Button>} />
              {sugg.loading ? <p className="text-sm text-ash">Recherche des artisans…</p> : sugg.data?.results.length ? (
                <ul className="space-y-3">
                  {sugg.data.results.map((s, i) => (
                    <li key={s.user_id} className="rounded-panel border border-lineSoft p-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1.5">
                          <p className="flex flex-wrap items-center gap-2 font-semibold text-ink">{s.display_name}{i === 0 ? <Badge tone="accent">Recommandé</Badge> : null}{s.online ? <Badge tone="success" pulse>En ligne</Badge> : null}</p>
                          <TrustBadges badges={s.badges.map((c) => ({ code: c as "VERIFIE" | "EXPERT" | "SUR", label: c }))} />
                          <ul className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-ash">{s.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
                        </div>
                        <Button size="sm" loading={busy === `d${s.user_id}`} onClick={() => act(`d${s.user_id}`, "dispatch/", { artisan: s.user_id })}>Confier la mission</Button>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : <Alert tone="info">Aucun artisan éligible n’est disponible pour cette demande pour le moment.</Alert>}
            </Card>
          ) : null}
        </div>

        <div className="space-y-6">
          <Card as="section" aria-label="Validation">
            <CardHeader title="Validation" description={r.steps.length ? "Chaque étape doit être validée dans l’ordre." : "Aucune validation requise : demande validée d’office."} />
            {r.steps.length ? (
              <ol className="space-y-3">
                {r.steps.map((s) => {
                  const Icon = ICON[s.status];
                  return (
                    <li key={s.order} className="flex gap-3">
                      <Icon aria-hidden className={`mt-0.5 h-5 w-5 shrink-0 ${TONE[s.status]}`} />
                      <div className="text-sm"><p className="font-semibold text-ink">{s.role_label}</p>
                        <p className="text-xs text-ash">{s.status === "pending" ? "En attente" : `${s.status === "approved" ? "Validé" : "Refusé"} par ${s.decided_by_name ?? "—"} le ${shortDate(s.decided_at)}`}</p>
                        {s.comment ? <p className="text-xs text-inkSoft">{s.comment}</p> : null}</div>
                    </li>
                  );
                })}
              </ol>
            ) : null}
            {r.can_decide ? (
              <div className="mt-4 space-y-3 border-t border-lineSoft pt-4">
                <TextareaField label="Commentaire" optional value={comment} onChange={(e) => setComment(e.target.value)} rows={2} />
                <div className="flex gap-2">
                  <Button block loading={busy === "approve"} leftIcon={<Check aria-hidden className="h-4 w-4" />} onClick={() => act("approve", "decide/", { approve: true, comment })}>Valider</Button>
                  <Button block variant="outline" loading={busy === "reject"} leftIcon={<X aria-hidden className="h-4 w-4" />} onClick={() => act("reject", "decide/", { approve: false, comment })}>Refuser</Button>
                </div>
              </div>
            ) : null}
          </Card>
          {cancellable ? <Button variant="outline" block onClick={() => setConfirmCancel(true)}>Annuler la demande</Button> : null}
          {r.equipment ? <Link href="/dashboard/business/sites" className="block text-center text-sm font-semibold text-primaryDark hover:underline">Voir l’équipement</Link> : null}
        </div>
      </div>
      <ConfirmDialog open={confirmCancel} onClose={() => setConfirmCancel(false)} tone="danger" title="Annuler cette demande ?" description="Si un artisan a déjà été sollicité, sa réservation sera annulée." confirmLabel="Oui, annuler" cancelLabel="Garder" loading={busy === "cancel"} onConfirm={async () => { await act("cancel", "cancel/"); setConfirmCancel(false); }} />
    </>
  );
}
