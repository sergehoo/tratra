"use client";
import { useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { Alert, Button, Card, EmptyState, Modal, PageHeader, SelectField, SkeletonList, TextField } from "@/components/ds";
import { apiErrorMessage, post } from "@/lib/api";
import { money, shortDate, useBusiness, useOrgData, type BudgetRow, type Equipment, type Site } from "@/lib/business";
import { Progress } from "@/components/business/ui";

function BudgetForm({ onDone }: { onDone: () => void }) {
  const { path } = useBusiness();
  const sites = useOrgData<Site[]>("sites/");
  const equipment = useOrgData<Equipment[]>("equipment/");
  const year = new Date().getFullYear();
  const [f, setF] = useState({ name: "", amount: "", site: "", equipment: "", period_start: `${year}-01-01`, period_end: `${year}-12-31`, alert_threshold_pct: "80" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = { name: f.name.trim(), amount: f.amount, period_start: f.period_start, period_end: f.period_end, alert_threshold_pct: Number(f.alert_threshold_pct) };
      if (f.site) body.site = Number(f.site);
      if (f.equipment) body.equipment = Number(f.equipment);
      await post(path("budgets/"), body);
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "Le budget n’a pas pu être créé."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <TextField label="Intitulé" required value={f.name} onChange={set("name")} placeholder="Maintenance 2026" />
      <TextField label="Montant alloué" required type="number" min={0} value={f.amount} onChange={set("amount")} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <SelectField label="Site" optional value={f.site} onChange={set("site")}><option value="">Toute l’organisation</option>{(sites.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</SelectField>
        <SelectField label="Équipement" optional value={f.equipment} onChange={set("equipment")}><option value="">Tous</option>{(equipment.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</SelectField>
        <TextField label="Début" required type="date" value={f.period_start} onChange={set("period_start")} />
        <TextField label="Fin" required type="date" value={f.period_end} onChange={set("period_end")} />
      </div>
      <TextField label="Alerte à (%)" type="number" min={1} max={100} value={f.alert_threshold_pct} onChange={set("alert_threshold_pct")} />
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button type="submit" block loading={busy} disabled={!f.name.trim() || !f.amount}>Créer le budget</Button>
    </form>
  );
}

export default function BudgetsPage() {
  const { can, org } = useBusiness();
  const { data, loading, error, reload } = useOrgData<BudgetRow[]>("budgets/", "Les budgets ne peuvent pas être chargés.");
  const [add, setAdd] = useState(false);
  const cur = org?.currency;
  return (
    <>
      <PageHeader eyebrow="Tratra Business" title="Budgets" description="Le consommé est calculé sur les interventions terminées et leurs montants réels ; l’engagé sur les demandes ouvertes." actions={can("budgets.manage") ? <Button leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => setAdd(true)}>Nouveau budget</Button> : null} />
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {loading ? <SkeletonList count={3} /> : data?.length ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {data.map((b) => (
            <Card key={b.id} as="article" className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-display text-lg font-bold text-ink">{b.name}</p><p className="text-xs text-ash">{shortDate(b.period_start)} → {shortDate(b.period_end)}</p></div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${b.status.level === "exceeded" ? "bg-dangerSoft text-dangerInk" : b.status.level === "warning" ? "bg-warningSoft text-warningInk" : "bg-successSoft text-successInk"}`}>{b.status.level === "exceeded" ? "Dépassé" : b.status.level === "warning" ? "Seuil atteint" : "Dans l’enveloppe"}</span></div>
              <Progress percent={b.status.percent} level={b.status.level} />
              <dl className="grid grid-cols-3 gap-2 text-sm">
                <div><dt className="text-xs text-ash">Alloué</dt><dd className="font-semibold">{money(b.amount, cur)}</dd></div>
                <div><dt className="text-xs text-ash">Consommé</dt><dd className="font-semibold">{money(b.status.spent, cur)}</dd></div>
                <div><dt className="text-xs text-ash">Engagé</dt><dd className="font-semibold">{money(b.status.committed, cur)}</dd></div>
              </dl>
              <p className="text-xs text-ash">{b.status.percent} % consommé · reste {money(b.status.remaining, cur)}</p>
            </Card>
          ))}
        </div>
      ) : <EmptyState title="Aucun budget" description="Définissez une enveloppe par site ou par équipement pour suivre vos dépenses." />}
      <Modal open={add} onClose={() => setAdd(false)} title="Nouveau budget" size="md"><BudgetForm onDone={() => { setAdd(false); void reload(); }} /></Modal>
    </>
  );
}
