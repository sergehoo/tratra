"use client";
import { useState, type FormEvent } from "react";
import { ListChecks, ScrollText } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, PageHeader, SelectField, TextField } from "@/components/ds";
import { apiErrorMessage, del, patch, post } from "@/lib/api";
import { PRIORITIES, ROLES, money, shortDate, useBusiness, useOrgData, type Site } from "@/lib/business";

interface Rule { id: number; name: string; order: number; min_amount: string; max_amount: string | null; priorities: string[]; site: number | null; steps: string[]; is_active: boolean }
interface AuditRow { at: string; action: string; actor: string; target_type: string; target_id: number | null; detail: Record<string, unknown> }

const APPROVER_ROLES = ROLES.filter((r) => ["admin", "site_manager", "approver", "finance"].includes(r.value));
const ACTION_LABEL: Record<string, string> = {
  "organization.created": "Organisation créée", "request.created": "Demande créée", "request.approved": "Étape validée", "request.rejected": "Demande refusée",
  "request.cancelled": "Demande annulée", "request.dispatched": "Artisan sollicité", "request.synced": "Mission mise à jour", "site.created": "Site créé",
  "equipment.created": "Équipement ajouté", "member.invited": "Invitation créée", "member.joined": "Membre ajouté", "member.removed": "Membre retiré",
  "invoice.issued": "Facture émise", "budget.created": "Budget créé", "contract.created": "Contrat créé", "approval_rule.created": "Règle de validation créée",
};

function RuleForm({ onDone }: { onDone: () => void }) {
  const { path } = useBusiness();
  const sites = useOrgData<Site[]>("sites/");
  const [f, setF] = useState({ name: "", min_amount: "0", max_amount: "", priority: "", site: "", step1: "site_manager", step2: "", step3: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = { name: f.name.trim(), min_amount: f.min_amount || "0", steps: [f.step1, f.step2, f.step3].filter(Boolean), priorities: f.priority ? [f.priority] : [] };
      if (f.max_amount) body.max_amount = f.max_amount;
      if (f.site) body.site = Number(f.site);
      await post(path("approval-rules/"), body);
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "La règle n’a pas pu être créée."));
    } finally {
      setBusy(false);
    }
  }
  const roleSelect = (k: "step1" | "step2" | "step3", label: string, optional: boolean) => (
    <SelectField label={label} optional={optional} value={f[k]} onChange={set(k)}>{optional ? <option value="">—</option> : null}{APPROVER_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</SelectField>
  );
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <TextField label="Nom de la règle" required value={f.name} onChange={set("name")} placeholder="Interventions > 100 000 FCFA" />
      <div className="grid grid-cols-2 gap-4"><TextField label="Montant minimum" type="number" min={0} value={f.min_amount} onChange={set("min_amount")} /><TextField label="Montant maximum" optional type="number" min={0} value={f.max_amount} onChange={set("max_amount")} /></div>
      <div className="grid grid-cols-2 gap-4">
        <SelectField label="Priorité" optional value={f.priority} onChange={set("priority")}><option value="">Toutes</option>{Object.entries(PRIORITIES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</SelectField>
        <SelectField label="Site" optional value={f.site} onChange={set("site")}><option value="">Tous</option>{(sites.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</SelectField>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">{roleSelect("step1", "Étape 1", false)}{roleSelect("step2", "Étape 2", true)}{roleSelect("step3", "Étape 3", true)}</div>
      <p className="text-xs text-ash">Les étapes se valident dans l’ordre. Personne ne valide sa propre demande ; le propriétaire et les administrateurs peuvent déroger (la dérogation est tracée).</p>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button type="submit" block loading={busy} disabled={!f.name.trim()}>Ajouter la règle</Button>
    </form>
  );
}

export default function SettingsPage() {
  const { org, can, path, reload: reloadOrgs } = useBusiness();
  const rules = useOrgData<Rule[]>(can("approval_rules.manage") ? "approval-rules/" : null, "Les règles ne peuvent pas être chargées.");
  const audit = useOrgData<AuditRow[]>(can("audit.view") ? "audit/" : null);
  const [name, setName] = useState(org?.name ?? "");
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const [adding, setAdding] = useState(false);
  const cur = org?.currency;

  async function saveOrg(e: FormEvent) {
    e.preventDefault();
    setFailure("");
    try {
      await patch(path(""), { name: name.trim() });
      await reloadOrgs();
      setNotice("Organisation mise à jour.");
    } catch (err) {
      setFailure(apiErrorMessage(err, "Impossible d’enregistrer."));
    }
  }
  async function toggle(r: Rule) {
    try { await patch(path(`approval-rules/${r.id}/`), { is_active: !r.is_active }); await rules.reload(); } catch { setFailure("La règle n’a pas pu être modifiée."); }
  }
  async function remove(r: Rule) {
    try { await del(path(`approval-rules/${r.id}/`)); await rules.reload(); } catch { setFailure("La règle n’a pas pu être supprimée."); }
  }
  return (
    <>
      <PageHeader eyebrow="Tratra Business" title="Paramètres" description="Organisation, circuit de validation et journal d’audit." />
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      {notice ? <Alert tone="success" className="mb-4" onDismiss={() => setNotice("")}>{notice}</Alert> : null}
      <div className="space-y-6">
        {can("org.manage") ? (
          <Card as="section" aria-label="Organisation">
            <CardHeader title="Organisation" />
            <form onSubmit={saveOrg} className="flex flex-wrap items-end gap-3"><div className="min-w-[16rem] flex-1"><TextField label="Nom" value={name} onChange={(e) => setName(e.target.value)} /></div><Button type="submit" disabled={!name.trim() || name === org?.name}>Enregistrer</Button></form>
          </Card>
        ) : null}
        {can("approval_rules.manage") ? (
          <Card as="section" aria-label="Validation hiérarchique">
            <CardHeader icon={<ListChecks className="h-5 w-5" />} title="Validation hiérarchique" description="Selon le montant, la priorité et le site, une suite de validations avant l’envoi à un artisan. Sans règle applicable : validation automatique." action={<Button size="sm" onClick={() => setAdding((v) => !v)}>{adding ? "Fermer" : "Ajouter une règle"}</Button>} />
            {adding ? <div className="mb-6 rounded-panel border border-lineSoft p-4"><RuleForm onDone={() => { setAdding(false); void rules.reload(); }} /></div> : null}
            {rules.data?.length ? (
              <ul className="space-y-3">{rules.data.map((r) => (
                <li key={r.id} className="rounded-panel border border-lineSoft p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-ink">{r.name}</p><Badge tone={r.is_active ? "success" : "gray"}>{r.is_active ? "Active" : "Désactivée"}</Badge></div>
                  <p className="text-xs text-ash">{money(r.min_amount, cur)} {r.max_amount ? `→ ${money(r.max_amount, cur)}` : "et plus"}{r.priorities.length ? ` · priorité ${r.priorities.map((p) => PRIORITIES[p]?.label ?? p).join(", ")}` : ""}</p>
                  <p className="mt-1 text-sm text-inkSoft">{r.steps.map((s, i) => `${i + 1}. ${ROLES.find((x) => x.value === s)?.label ?? s}`).join("  →  ") || "Validation automatique"}</p>
                  <div className="mt-2 flex gap-2"><Button size="sm" variant="outline" onClick={() => toggle(r)}>{r.is_active ? "Désactiver" : "Activer"}</Button><Button size="sm" variant="ghost" onClick={() => remove(r)}>Supprimer</Button></div>
                </li>))}</ul>
            ) : <p className="text-sm text-ash">Aucune règle : toutes les demandes sont validées d’office.</p>}
          </Card>
        ) : null}
        {can("audit.view") ? (
          <Card as="section" aria-label="Journal d’audit">
            <CardHeader icon={<ScrollText className="h-5 w-5" />} title="Journal d’audit" description="Qui a fait quoi, et quand (200 derniers événements)." />
            {audit.data?.length ? (
              <ul className="divide-y divide-lineSoft text-sm">{audit.data.map((e, i) => (
                <li key={i} className="flex flex-wrap items-center justify-between gap-2 py-2"><span><strong className="text-ink">{ACTION_LABEL[e.action] ?? e.action}</strong>{e.detail.number ? <span className="text-ash"> · {String(e.detail.number)}</span> : null}</span><span className="text-xs text-ash">{e.actor} · {shortDate(e.at)}</span></li>))}</ul>
            ) : <EmptyState title="Aucun événement" />}
          </Card>
        ) : null}
      </div>
    </>
  );
}
