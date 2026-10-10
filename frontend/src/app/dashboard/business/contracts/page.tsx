"use client";
import { useState, type FormEvent } from "react";
import { CalendarClock, Plus, ScrollText } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, Modal, PageHeader, SelectField, SkeletonList, TextField } from "@/components/ds";
import { apiErrorMessage, post } from "@/lib/api";
import { shortDate, useBusiness, useOrgData, type Equipment, type Site } from "@/lib/business";

interface Contract { id: number; name: string; site: number | null; provider: number | null; provider_name: string | null; starts_on: string; ends_on: string | null; sla_response_hours: number; sla_resolution_hours: number; status: string }
interface Plan { id: number; equipment: number; equipment_name: string; title: string; frequency_days: number; next_due_on: string; lead_days: number; last_done_on: string | null; is_active: boolean }

function ContractForm({ onDone }: { onDone: () => void }) {
  const { path } = useBusiness();
  const sites = useOrgData<Site[]>("sites/");
  const [f, setF] = useState({ name: "", site: "", provider: "", starts_on: new Date().toISOString().slice(0, 10), ends_on: "", sla_response_hours: "24", sla_resolution_hours: "72" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = { name: f.name.trim(), starts_on: f.starts_on, sla_response_hours: Number(f.sla_response_hours), sla_resolution_hours: Number(f.sla_resolution_hours) };
      if (f.site) body.site = Number(f.site);
      if (f.ends_on) body.ends_on = f.ends_on;
      if (f.provider) body.provider = Number(f.provider);
      await post(path("contracts/"), body);
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "Le contrat n’a pas pu être créé."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <TextField label="Intitulé" required value={f.name} onChange={set("name")} />
      <SelectField label="Site concerné" optional value={f.site} onChange={set("site")}><option value="">Tous les sites</option>{(sites.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</SelectField>
      <TextField label="Identifiant de l’artisan attitré" optional type="number" value={f.provider} onChange={set("provider")} hint="Identifiant utilisateur d’un artisan vérifié (visible dans l’affectation). Il passera en tête des suggestions." />
      <div className="grid grid-cols-2 gap-4"><TextField label="Début" required type="date" value={f.starts_on} onChange={set("starts_on")} /><TextField label="Fin" optional type="date" value={f.ends_on} onChange={set("ends_on")} /></div>
      <div className="grid grid-cols-2 gap-4"><TextField label="SLA prise en charge (h)" type="number" min={1} value={f.sla_response_hours} onChange={set("sla_response_hours")} /><TextField label="SLA résolution (h)" type="number" min={1} value={f.sla_resolution_hours} onChange={set("sla_resolution_hours")} /></div>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button type="submit" block loading={busy} disabled={!f.name.trim()}>Créer le contrat</Button>
    </form>
  );
}

function PlanForm({ onDone }: { onDone: () => void }) {
  const { path } = useBusiness();
  const equipment = useOrgData<Equipment[]>("equipment/");
  const [f, setF] = useState({ equipment: "", title: "", frequency_days: "90", next_due_on: "", lead_days: "7" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(path("preventive-plans/"), { equipment: Number(f.equipment), title: f.title.trim(), frequency_days: Number(f.frequency_days), next_due_on: f.next_due_on, lead_days: Number(f.lead_days) });
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "Le plan n’a pas pu être créé."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <SelectField label="Équipement" required value={f.equipment} onChange={set("equipment")}><option value="">Choisir…</option>{(equipment.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.name} — {e.site_name}</option>)}</SelectField>
      <TextField label="Intitulé" required value={f.title} onChange={set("title")} placeholder="Entretien semestriel" />
      <div className="grid grid-cols-2 gap-4"><TextField label="Tous les (jours)" required type="number" min={1} value={f.frequency_days} onChange={set("frequency_days")} /><TextField label="Prochaine échéance" required type="date" value={f.next_due_on} onChange={set("next_due_on")} /></div>
      <TextField label="Créer la demande (jours avant)" type="number" min={0} value={f.lead_days} onChange={set("lead_days")} hint="La demande d’intervention est créée automatiquement et les responsables sont prévenus." />
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button type="submit" block loading={busy} disabled={!f.equipment || !f.title.trim() || !f.next_due_on}>Planifier</Button>
    </form>
  );
}

export default function ContractsPage() {
  const { can } = useBusiness();
  const contracts = useOrgData<Contract[]>("contracts/", "Les contrats ne peuvent pas être chargés.");
  const plans = useOrgData<Plan[]>("preventive-plans/");
  const [addContract, setAddContract] = useState(false);
  const [addPlan, setAddPlan] = useState(false);
  const today = new Date().toISOString().slice(0, 10);
  return (
    <>
      <PageHeader eyebrow="Tratra Business" title="Contrats et maintenance préventive" description="Les SLA des contrats fixent les échéances de prise en charge et de résolution ; le préventif crée les demandes à l’avance." />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 lg:items-start">
        <Card as="section" aria-label="Contrats">
          <CardHeader icon={<ScrollText className="h-5 w-5" />} title="Contrats de maintenance" action={can("contracts.manage") ? <Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => setAddContract(true)}>Ajouter</Button> : undefined} />
          {contracts.loading ? <SkeletonList count={2} /> : contracts.data?.length ? (
            <ul className="space-y-3">{contracts.data.map((c) => (
              <li key={c.id} className="rounded-panel border border-lineSoft p-3">
                <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-ink">{c.name}</p><Badge tone={c.status === "active" ? "success" : "gray"}>{c.status === "active" ? "Actif" : c.status === "expired" ? "Expiré" : "Résilié"}</Badge></div>
                <p className="text-xs text-ash">{shortDate(c.starts_on)} → {c.ends_on ? shortDate(c.ends_on) : "sans fin"} · prise en charge {c.sla_response_hours} h · résolution {c.sla_resolution_hours} h</p>
                <p className="text-xs text-inkSoft">{c.provider_name ? `Prestataire attitré : ${c.provider_name}` : "Sans prestataire attitré"}</p>
              </li>))}</ul>
          ) : <EmptyState title="Aucun contrat" description="Sans contrat, les SLA par défaut s’appliquent selon la priorité." />}
        </Card>
        <Card as="section" aria-label="Maintenance préventive">
          <CardHeader icon={<CalendarClock className="h-5 w-5" />} title="Maintenance préventive" action={can("preventive.manage") ? <Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => setAddPlan(true)}>Planifier</Button> : undefined} />
          {plans.loading ? <SkeletonList count={2} /> : plans.data?.length ? (
            <ul className="space-y-3">{plans.data.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-panel border border-lineSoft p-3">
                <div><p className="font-semibold text-ink">{p.title}</p><p className="text-xs text-ash">{p.equipment_name} · tous les {p.frequency_days} j{p.last_done_on ? ` · dernière le ${shortDate(p.last_done_on)}` : ""}</p></div>
                <Badge tone={p.next_due_on < today ? "danger" : "info"}>{p.next_due_on < today ? "En retard · " : "Prochaine · "}{shortDate(p.next_due_on)}</Badge>
              </li>))}</ul>
          ) : <EmptyState title="Aucun plan" description="Planifiez l’entretien régulier de vos équipements." />}
        </Card>
      </div>
      <Modal open={addContract} onClose={() => setAddContract(false)} title="Nouveau contrat" size="md"><ContractForm onDone={() => { setAddContract(false); void contracts.reload(); }} /></Modal>
      <Modal open={addPlan} onClose={() => setAddPlan(false)} title="Nouveau plan préventif" size="md"><PlanForm onDone={() => { setAddPlan(false); void plans.reload(); }} /></Modal>
    </>
  );
}
