"use client";
import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Alert, Badge, Button, Checkbox, DataTable, EmptyState, Modal, SkeletonPage, TextField, type Column } from "@/components/ds";
import { bo, boError, fieldErrors } from "@/lib/bo";
import { Section, dt } from "../_components/ui";

interface Config { enabled: boolean; threshold_km: string; currency: string; mode: string; mode_label: string; fallback_flat_amount: number; rounding_step: number; rounding_method: string; effective_from: string | null; version: number }
interface Band { id: number; name: string; zone: number | null; zone_name: string | null; start: string; end: string; weekdays: number[]; days_label: string; rate_per_km: string; is_active: boolean; valid_from: string | null; valid_to: string | null }
interface Zone { id: number; name: string; communes: string[]; is_active: boolean }
interface Overview { config: Config; modes: { value: string; label: string }[]; zones: Zone[]; bands: Band[]; versions: { version: number; changed_at: string; reason: string; changed_by: string | null }[]; example: { band: string; distance_km: number; amount: number; at: string }[]; timezone: string }

const DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const ROUNDING = [["nearest", "Au plus proche"], ["up", "Au supérieur"], ["down", "À l’inférieur"]];
const fcfa = (n: number) => `${new Intl.NumberFormat("fr-FR").format(n)} FCFA`;

type Form = Record<string, string | boolean | number[]>;

function FormModal({ open, title, description, onClose, onSubmit, children }: { open: boolean; title: string; description?: string; onClose: () => void; onSubmit: () => Promise<void>; children: React.ReactNode }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal open={open} onClose={onClose} dismissible={!busy} title={title} description={description}
      footer={<><Button variant="outline" onClick={onClose} disabled={busy}>Annuler</Button><Button loading={busy} onClick={async () => { setBusy(true); try { await onSubmit(); } finally { setBusy(false); } }}>Enregistrer</Button></>}>
      <div className="space-y-4">{children}</div>
    </Modal>
  );
}

/** Paramètres du transport : activation, seuil, mode aller-retour, forfait de secours, arrondi, tranches horaires, zones, historique. */
export function TransportSettings({ onNotice }: { onNotice: (m: string) => void }) {
  const [d, setD] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState<{ kind: "config" | "band" | "zone"; item: Band | Zone | null } | null>(null);
  const [f, setF] = useState<Form>({});
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [fail, setFail] = useState("");

  const load = useCallback(async () => {
    setError("");
    try { setD(await bo.get<Overview>("/settings/transport/")); } catch (e) { setError(boError(e, "Les paramètres de transport n’ont pas pu être chargés.")); }
  }, []);
  useEffect(() => void load(), [load]);

  function open(kind: "config" | "band" | "zone", item: Band | Zone | null = null) {
    setErrs({}); setFail("");
    if (kind === "config" && d) {
      const c = d.config;
      setF({ enabled: c.enabled, threshold_km: c.threshold_km, mode: c.mode, fallback_flat_amount: String(c.fallback_flat_amount), rounding_step: String(c.rounding_step), rounding_method: c.rounding_method, effective_from: c.effective_from ?? "", reason: "" });
    } else if (kind === "band") {
      const b = item as Band | null;
      setF({ name: b?.name ?? "", start: b?.start ?? "06:00", end: b?.end ?? "09:00", weekdays: b?.weekdays ?? [0, 1, 2, 3, 4, 5, 6], rate_per_km: b?.rate_per_km ?? "", zone: b?.zone ? String(b.zone) : "", valid_from: b?.valid_from ?? "", valid_to: b?.valid_to ?? "", is_active: b?.is_active ?? true, reason: "" });
    } else {
      const z = item as Zone | null;
      setF({ name: z?.name ?? "", communes: (z?.communes ?? []).join(", "), is_active: z?.is_active ?? true, reason: "" });
    }
    setEdit({ kind, item });
  }

  async function save() {
    if (!edit) return;
    setErrs({}); setFail("");
    try {
      if (edit.kind === "config") {
        await bo.put("/settings/transport/", { ...f, effective_from: f.effective_from || null });
      } else if (edit.kind === "band") {
        const body = { ...f, zone: f.zone || null, valid_from: f.valid_from || null, valid_to: f.valid_to || null };
        if (edit.item) await bo.patch(`/settings/transport/bands/${(edit.item as Band).id}/`, body); else await bo.post("/settings/transport/bands/", body);
      } else {
        const body = { ...f, communes: String(f.communes ?? "").split(",").map((c) => c.trim()).filter(Boolean) };
        if (edit.item) await bo.patch(`/settings/transport/zones/${(edit.item as Zone).id}/`, body); else await bo.post("/settings/transport/zones/", body);
      }
      setEdit(null); onNotice("Paramètres de transport enregistrés (nouvelle version créée)."); await load();
    } catch (e) { setErrs(fieldErrors(e)); setFail(boError(e, "L’enregistrement a échoué.")); }
  }

  if (error && !d) return <Alert tone="danger" title="Transport indisponible" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>;
  if (!d) return <SkeletonPage />;
  const c = d.config;
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((v) => ({ ...v, [k]: e.target.value }));
  const sel = "block min-h-[44px] w-full rounded-control border border-line bg-white px-3 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30";

  const bandCols: Column<Band>[] = [
    { key: "n", header: "Tranche", primary: true, cell: (b) => <span className="font-semibold text-ink">{b.name}</span> },
    { key: "h", header: "Horaire", cell: (b) => `${b.start} – ${b.end}` },
    { key: "j", header: "Jours", cell: (b) => b.days_label },
    { key: "r", header: "Tarif/km", align: "right", cell: (b) => fcfa(Number(b.rate_per_km)) },
    { key: "z", header: "Zone", cell: (b) => b.zone_name ?? "Toutes" },
    { key: "s", header: "Statut", cell: (b) => <Badge tone={b.is_active ? "success" : "gray"}>{b.is_active ? "Active" : "Inactive"}</Badge> },
    { key: "x", header: "", align: "right", cell: (b) => <Button size="sm" variant="outline" onClick={() => open("band", b)}>Modifier</Button> },
  ];
  const zoneCols: Column<Zone>[] = [
    { key: "n", header: "Zone", primary: true, cell: (z) => <span className="font-semibold text-ink">{z.name}</span> },
    { key: "c", header: "Communes / villes", cell: (z) => z.communes.join(", ") },
    { key: "s", header: "Statut", cell: (z) => <Badge tone={z.is_active ? "success" : "gray"}>{z.is_active ? "Active" : "Inactive"}</Badge> },
    { key: "x", header: "", align: "right", cell: (z) => <Button size="sm" variant="outline" onClick={() => open("zone", z)}>Modifier</Button> },
  ];

  return (
    <>
      <Section title="Frais de déplacement" className="mb-6" actions={<Button size="sm" onClick={() => open("config")}>Modifier la configuration</Button>}>
        <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <div><dt className="text-xs font-semibold text-ash">État</dt><dd><Badge tone={c.enabled ? "success" : "gray"}>{c.enabled ? "Activé" : "Désactivé : aucun frais ajouté"}</Badge></dd></div>
          <div><dt className="text-xs font-semibold text-ash">Seuil de gratuité</dt><dd className="font-semibold text-ink">{c.threshold_km} km (gratuit jusqu’à cette distance)</dd></div>
          <div><dt className="text-xs font-semibold text-ash">Forfait de secours</dt><dd className="font-semibold text-ink">{fcfa(c.fallback_flat_amount)} (sans tarif applicable ou sans distance)</dd></div>
          <div className="sm:col-span-2"><dt className="text-xs font-semibold text-ash">Mode de calcul</dt><dd className="font-semibold text-ink">{c.mode_label}</dd></div>
          <div><dt className="text-xs font-semibold text-ash">Arrondi</dt><dd className="font-semibold text-ink">{c.rounding_step} {c.currency} · {ROUNDING.find((r) => r[0] === c.rounding_method)?.[1]}</dd></div>
          <div><dt className="text-xs font-semibold text-ash">Application</dt><dd className="font-semibold text-ink">{c.effective_from ? `à partir du ${c.effective_from}` : "immédiate"} · version {c.version} · fuseau {d.timezone}</dd></div>
        </dl>
        {d.example.length ? (
          <div className="mt-4 rounded-panel bg-canvas p-3 text-sm text-inkSoft">
            <p className="font-semibold text-ink">Exemple chiffré avec vos tarifs (distance d’aller de 8 km)</p>
            <ul className="mt-1 list-disc pl-5">{d.example.map((x) => <li key={x.band}>{x.band} : {fcfa(x.amount)}</li>)}</ul>
          </div>
        ) : null}
      </Section>

      <Section title="Tranches horaires et tarifs par km" className="mb-6" actions={<Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => open("band")}>Nouvelle tranche</Button>}>
        <p className="mb-3 text-xs text-ash">Heures d’Abidjan. Une tranche de zone l’emporte sur une tranche générale. Les tranches ne se chevauchent pas. Aucune suppression : désactivez une tranche pour la retirer (les réservations passées gardent leur calcul).</p>
        <DataTable caption="Tranches horaires de transport" columns={bandCols} rows={d.bands} rowKey={(b) => b.id} empty={<EmptyState title="Aucune tranche : le forfait de secours s’applique" compact />} />
      </Section>

      <Section title="Zones géographiques" className="mb-6" actions={<Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => open("zone")}>Nouvelle zone</Button>}>
        <DataTable caption="Zones de transport" columns={zoneCols} rows={d.zones} rowKey={(z) => z.id} empty={<EmptyState title="Aucune zone : les tranches s’appliquent partout" compact />} />
      </Section>

      <Section title="Historique des modifications" className="mb-6">
        <DataTable caption="Versions de la configuration" columns={[
          { key: "v", header: "Version", primary: true, cell: (v) => `v${v.version}` },
          { key: "d", header: "Date", cell: (v) => dt(v.changed_at) },
          { key: "b", header: "Par", cell: (v) => v.changed_by ?? "—" },
          { key: "r", header: "Motif", cell: (v) => v.reason || "—" },
        ] as Column<Overview["versions"][number]>[]} rows={d.versions} rowKey={(v) => v.version} empty={<EmptyState title="Aucune modification enregistrée" compact />} />
      </Section>

      <FormModal open={edit?.kind === "config"} title="Configuration du transport" description="Un motif est obligatoire ; la modification crée une nouvelle version." onClose={() => setEdit(null)} onSubmit={save}>
        <Checkbox label="Activer les frais de déplacement" checked={Boolean(f.enabled)} onChange={(e) => setF((v) => ({ ...v, enabled: e.target.checked }))} />
        <TextField label="Seuil de gratuité (km)" value={String(f.threshold_km ?? "")} onChange={set("threshold_km")} error={errs.threshold_km} inputMode="decimal" />
        <div>
          <label htmlFor="tr-mode" className="mb-1 block text-sm font-semibold text-ink">Mode de calcul</label>
          <select id="tr-mode" className={sel} value={String(f.mode ?? "")} onChange={set("mode")}>{d.modes.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}</select>
          <p className="mt-1 text-xs text-ash">Le retour n’est jamais facturé deux fois : « retour inclus » fixe un tarif sur le kilométrage d’aller simple.</p>
        </div>
        <TextField label="Forfait de secours (FCFA)" value={String(f.fallback_flat_amount ?? "")} onChange={set("fallback_flat_amount")} error={errs.fallback_flat_amount} inputMode="numeric" />
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="Arrondi (pas en FCFA)" value={String(f.rounding_step ?? "")} onChange={set("rounding_step")} error={errs.rounding_step} inputMode="numeric" />
          <div><label htmlFor="tr-round" className="mb-1 block text-sm font-semibold text-ink">Méthode d’arrondi</label><select id="tr-round" className={sel} value={String(f.rounding_method ?? "")} onChange={set("rounding_method")}>{ROUNDING.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
        </div>
        <TextField label="Date d’application" optional type="date" value={String(f.effective_from ?? "")} onChange={set("effective_from")} error={errs.effective_from} hint="Vide : application immédiate." />
        <TextField label="Motif de la modification" value={String(f.reason ?? "")} onChange={set("reason")} error={errs.reason} />
        {fail ? <Alert tone="danger">{fail}</Alert> : null}
      </FormModal>

      <FormModal open={edit?.kind === "band"} title={edit?.item ? "Modifier la tranche" : "Nouvelle tranche"} onClose={() => setEdit(null)} onSubmit={save}>
        <TextField label="Nom" value={String(f.name ?? "")} onChange={set("name")} error={errs.name} />
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="De" type="time" value={String(f.start ?? "")} onChange={set("start")} error={errs.start} />
          <TextField label="À (exclu)" type="time" value={String(f.end ?? "")} onChange={set("end")} error={errs.end} />
        </div>
        <fieldset>
          <legend className="mb-1 text-sm font-semibold text-ink">Jours concernés</legend>
          <div className="flex flex-wrap gap-2">
            {DAYS.map((label, i) => {
              const days = (f.weekdays as number[]) ?? [];
              return <label key={label} className="flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-full border border-line px-3 text-sm"><input type="checkbox" checked={days.includes(i)} onChange={(e) => setF((v) => ({ ...v, weekdays: e.target.checked ? [...days, i] : days.filter((x) => x !== i) }))} />{label}</label>;
            })}
          </div>
          {errs.weekdays ? <p className="mt-1 text-xs text-dangerInk">{errs.weekdays}</p> : null}
        </fieldset>
        <TextField label="Tarif par km (FCFA)" value={String(f.rate_per_km ?? "")} onChange={set("rate_per_km")} error={errs.rate_per_km} inputMode="decimal" />
        <div><label htmlFor="tr-zone" className="mb-1 block text-sm font-semibold text-ink">Zone</label><select id="tr-zone" className={sel} value={String(f.zone ?? "")} onChange={set("zone")}><option value="">Toutes les zones</option>{d.zones.filter((z) => z.is_active).map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}</select></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="Valide à partir du" optional type="date" value={String(f.valid_from ?? "")} onChange={set("valid_from")} error={errs.valid_from} />
          <TextField label="Valide jusqu’au" optional type="date" value={String(f.valid_to ?? "")} onChange={set("valid_to")} error={errs.valid_to} />
        </div>
        <Checkbox label="Tranche active" checked={Boolean(f.is_active)} onChange={(e) => setF((v) => ({ ...v, is_active: e.target.checked }))} />
        <TextField label="Motif de la modification" value={String(f.reason ?? "")} onChange={set("reason")} error={errs.reason} />
        {fail ? <Alert tone="danger">{fail}</Alert> : null}
      </FormModal>

      <FormModal open={edit?.kind === "zone"} title={edit?.item ? "Modifier la zone" : "Nouvelle zone"} onClose={() => setEdit(null)} onSubmit={save}>
        <TextField label="Nom de la zone" value={String(f.name ?? "")} onChange={set("name")} error={errs.name} />
        <TextField label="Communes / villes (séparées par des virgules)" value={String(f.communes ?? "")} onChange={set("communes")} error={errs.communes} hint="Comparées sans tenir compte des accents ni de la casse." />
        <Checkbox label="Zone active" checked={Boolean(f.is_active)} onChange={(e) => setF((v) => ({ ...v, is_active: e.target.checked }))} />
        <TextField label="Motif de la modification" value={String(f.reason ?? "")} onChange={set("reason")} error={errs.reason} />
        {fail ? <Alert tone="danger">{fail}</Alert> : null}
      </FormModal>
    </>
  );
}
