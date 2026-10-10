"use client";
import { useState, type FormEvent } from "react";
import { Alert, Button, SelectField, TextField, TextareaField } from "@/components/ds";
import { apiErrorMessage, post } from "@/lib/api";
import { useData } from "@/lib/useData";
import { PRIORITIES, useBusiness, useOrgData, type BizRequest, type Equipment, type Site } from "@/lib/business";
import type { Category, Paginated } from "@/lib/types";

/** Formulaire de demande d'intervention (saisie ou QR d'équipement). Le serveur choisit la règle de validation et les SLA. */
export function NewRequestForm({
  orgId,
  initial,
  fromQr = false,
  onCreated,
}: {
  orgId?: number;
  initial?: { site?: number; equipment?: number; category?: number | null };
  fromQr?: boolean;
  onCreated: (r: BizRequest) => void;
}) {
  const { org } = useBusiness();
  const id = orgId ?? org?.id;
  const sites = useOrgData<Site[]>("sites/");
  const equipment = useOrgData<Equipment[]>("equipment/");
  const cats = useData<Paginated<Category>>("/categories/?page_size=100&ordering=name");
  const [f, setF] = useState({
    site: String(initial?.site ?? ""), equipment: String(initial?.equipment ?? ""), category: String(initial?.category ?? ""),
    title: "", description: "", priority: "normal", estimated_cost: "", desired_date: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  const siteEquipment = (equipment.data ?? []).filter((e) => !f.site || String(e.site) === f.site);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!f.site || !f.title.trim()) return setError("Choisissez le site et décrivez le problème.");
    setBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = { site: Number(f.site), title: f.title.trim(), description: f.description.trim(), priority: f.priority };
      if (f.equipment) body.equipment = Number(f.equipment);
      if (f.category) body.category = Number(f.category);
      if (f.estimated_cost) body.estimated_cost = f.estimated_cost;
      if (f.desired_date) body.desired_date = new Date(f.desired_date).toISOString();
      if (fromQr) body.from_qr = true;
      onCreated(await post<BizRequest>(`/business/orgs/${id}/requests/`, body));
    } catch (err) {
      setError(apiErrorMessage(err, "La demande n’a pas pu être créée."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <SelectField label="Site" required value={f.site} onChange={set("site")} disabled={Boolean(initial?.site)}>
        <option value="">Choisir…</option>
        {(sites.data ?? []).filter((s) => s.is_active).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </SelectField>
      <SelectField label="Équipement concerné" optional value={f.equipment} onChange={set("equipment")} disabled={Boolean(initial?.equipment)}>
        <option value="">Aucun / autre</option>
        {siteEquipment.map((e) => <option key={e.id} value={e.id}>{e.name}{e.location_detail ? ` — ${e.location_detail}` : ""}</option>)}
      </SelectField>
      <TextField label="Problème à traiter" required value={f.title} onChange={set("title")} maxLength={200} placeholder="Ex. Fuite sous l’évier du bureau 12" />
      <TextareaField label="Détails" optional value={f.description} onChange={set("description")} rows={3} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <SelectField label="Métier" optional value={f.category} onChange={set("category")}>
          <option value="">Non précisé</option>
          {(cats.data?.results ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </SelectField>
        <SelectField label="Priorité" value={f.priority} onChange={set("priority")}>
          {Object.entries(PRIORITIES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SelectField>
        <TextField label={`Coût estimé (${org?.currency === "XOF" ? "FCFA" : org?.currency ?? ""})`} optional type="number" min={0} value={f.estimated_cost} onChange={set("estimated_cost")} hint="Détermine la validation nécessaire." />
        <TextField label="Date souhaitée" optional type="datetime-local" value={f.desired_date} onChange={set("desired_date")} />
      </div>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button type="submit" block size="lg" loading={busy}>Envoyer la demande</Button>
    </form>
  );
}
