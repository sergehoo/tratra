"use client";
import { useEffect, useState, type FormEvent } from "react";
import { Building, LocateFixed, MapPin, Plus, Printer, QrCode } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, Modal, PageHeader, SelectField, SkeletonList, TextField, TextareaField } from "@/components/ds";
import { apiErrorMessage, post, privateFileUrl } from "@/lib/api";
import { shortDate, useBusiness, useOrgData, type Equipment, type Site } from "@/lib/business";
import { useData } from "@/lib/useData";
import type { Category, Paginated } from "@/lib/types";

const EQ_STATUS: Record<string, { label: string; tone: "success" | "warning" | "danger" | "gray" }> = {
  operational: { label: "En service", tone: "success" },
  degraded: { label: "Dégradé", tone: "warning" },
  out_of_service: { label: "Hors service", tone: "danger" },
  retired: { label: "Retiré", tone: "gray" },
};

function SiteForm({ onDone }: { onDone: () => void }) {
  const { path } = useBusiness();
  const [f, setF] = useState({ name: "", address: "", city: "", postal_code: "", lat: "", lng: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  function locate() {
    navigator.geolocation?.getCurrentPosition(
      (p) => setF((s) => ({ ...s, lat: p.coords.latitude.toFixed(6), lng: p.coords.longitude.toFixed(6) })),
      () => setError("Position introuvable : saisissez les coordonnées à la main ou laissez vide."),
    );
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = { name: f.name.trim(), address: f.address.trim(), city: f.city.trim(), postal_code: f.postal_code.trim() };
      if (f.lat && f.lng) Object.assign(body, { lat: Number(f.lat), lng: Number(f.lng) });
      await post(path("sites/"), body);
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "Le site n’a pas pu être créé."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <TextField label="Nom du site" required value={f.name} onChange={set("name")} maxLength={150} />
      <TextareaField label="Adresse" optional value={f.address} onChange={set("address")} rows={2} />
      <div className="grid grid-cols-2 gap-4"><TextField label="Ville" optional value={f.city} onChange={set("city")} /><TextField label="Code postal" optional value={f.postal_code} onChange={set("postal_code")} /></div>
      <div className="grid grid-cols-2 gap-4"><TextField label="Latitude" optional value={f.lat} onChange={set("lat")} inputMode="decimal" /><TextField label="Longitude" optional value={f.lng} onChange={set("lng")} inputMode="decimal" /></div>
      <Button type="button" variant="ghost" size="sm" leftIcon={<LocateFixed aria-hidden className="h-4 w-4" />} onClick={locate}>Utiliser ma position</Button>
      <p className="text-xs text-ash">Les coordonnées servent à choisir l’artisan le plus proche et à estimer son arrivée.</p>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button type="submit" block loading={busy} disabled={!f.name.trim()}>Créer le site</Button>
    </form>
  );
}

function EquipmentForm({ site, onDone }: { site: Site; onDone: () => void }) {
  const { path } = useBusiness();
  const cats = useData<Paginated<Category>>("/categories/?page_size=100&ordering=name");
  const buildings = useOrgData<{ id: number; name: string }[]>(`buildings/?site=${site.id}`);
  const [f, setF] = useState({ name: "", category: "", building: "", reference: "", location_detail: "", installed_on: "", warranty_ends_on: "", new_building: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      let building = f.building ? Number(f.building) : null;
      if (f.new_building.trim()) building = (await post<{ id: number }>(path("buildings/"), { site: site.id, name: f.new_building.trim() })).id;
      const body: Record<string, unknown> = { name: f.name.trim(), site: site.id, reference: f.reference.trim(), location_detail: f.location_detail.trim() };
      if (f.category) body.category = Number(f.category);
      if (building) body.building = building;
      if (f.installed_on) body.installed_on = f.installed_on;
      if (f.warranty_ends_on) body.warranty_ends_on = f.warranty_ends_on;
      await post(path("equipment/"), body);
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "L’équipement n’a pas pu être créé."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <TextField label="Nom de l’équipement" required value={f.name} onChange={set("name")} placeholder="Ex. Climatiseur salle de réunion" />
      <SelectField label="Métier d’entretien" optional value={f.category} onChange={set("category")}><option value="">Non précisé</option>{(cats.data?.results ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</SelectField>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <SelectField label="Bâtiment" optional value={f.building} onChange={set("building")}><option value="">—</option>{(buildings.data ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</SelectField>
        <TextField label="…ou nouveau bâtiment" optional value={f.new_building} onChange={set("new_building")} />
        <TextField label="Référence / n° de série" optional value={f.reference} onChange={set("reference")} />
        <TextField label="Emplacement précis" optional value={f.location_detail} onChange={set("location_detail")} placeholder="Étage 2, local technique" />
        <TextField label="Mise en service" optional type="date" value={f.installed_on} onChange={set("installed_on")} />
        <TextField label="Fin de garantie" optional type="date" value={f.warranty_ends_on} onChange={set("warranty_ends_on")} />
      </div>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button type="submit" block loading={busy} disabled={!f.name.trim()}>Ajouter l’équipement</Button>
    </form>
  );
}

function QrModal({ eq, onClose }: { eq: Equipment; onClose: () => void }) {
  const { path } = useBusiness();
  const [src, setSrc] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let url = "";
    privateFileUrl(path(`equipment/${eq.id}/qr.png`)).then((u) => { url = u; setSrc(u); }).catch(() => setError("Le QR n’a pas pu être généré."));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [eq.id, path]);
  return (
    <Modal open onClose={onClose} title={eq.name} description={`QR ${eq.qr_code} — à coller sur l’équipement : un membre qui le scanne peut signaler un problème en deux touches.`} size="sm"
      footer={<><Button variant="outline" onClick={onClose}>Fermer</Button><Button leftIcon={<Printer aria-hidden className="h-4 w-4" />} onClick={() => window.print()} disabled={!src}>Imprimer</Button></>}>
      {error ? <Alert tone="danger">{error}</Alert> : src ? (
        <div className="text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} alt={`QR de l’équipement ${eq.name}`} className="mx-auto h-56 w-56 rounded-panel border border-lineSoft bg-white p-2" />
          <p className="mt-2 font-mono text-sm font-bold text-ink">{eq.qr_code}</p>
          <p className="text-xs text-ash">{eq.site_name}{eq.location_detail ? ` · ${eq.location_detail}` : ""}</p>
        </div>
      ) : <SkeletonList count={1} />}
    </Modal>
  );
}

export default function SitesPage() {
  const { can } = useBusiness();
  const sites = useOrgData<Site[]>("sites/", "Les sites ne peuvent pas être chargés.");
  const [selected, setSelected] = useState<number | null>(null);
  const equipment = useOrgData<Equipment[]>(selected ? `equipment/?site=${selected}` : null);
  const [addSite, setAddSite] = useState(false);
  const [addEq, setAddEq] = useState(false);
  const [qr, setQr] = useState<Equipment | null>(null);
  const manage = can("sites.manage");
  const site = (sites.data ?? []).find((s) => s.id === selected) ?? (sites.data ?? [])[0];
  useEffect(() => { if (!selected && site) setSelected(site.id); }, [site, selected]);

  return (
    <>
      <PageHeader eyebrow="Tratra Business" title="Sites et équipements" description="Chaque équipement a son QR : un scan suffit pour signaler un problème." actions={manage ? <Button leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => setAddSite(true)}>Ajouter un site</Button> : null} />
      {sites.loading ? <SkeletonList count={3} /> : !sites.data?.length ? (
        <EmptyState icon={<Building />} title="Aucun site" description={manage ? "Ajoutez votre premier site pour y rattacher équipements et demandes." : "Aucun site ne vous est attribué."} />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 lg:items-start">
          <ul className="space-y-2" aria-label="Sites">
            {sites.data.map((s) => (
              <li key={s.id}>
                <button type="button" onClick={() => setSelected(s.id)} aria-pressed={s.id === selected} className={`w-full rounded-panel border p-3 text-left transition ${s.id === selected ? "border-primary bg-primarySoft" : "border-lineSoft bg-white hover:bg-canvas"}`}>
                  <p className="font-semibold text-ink">{s.name}</p>
                  <p className="flex items-center gap-1 text-xs text-ash"><MapPin aria-hidden className="h-3.5 w-3.5" />{[s.address, s.city].filter(Boolean).join(", ") || "Adresse non renseignée"}</p>
                  <p className="mt-1 text-xs text-inkSoft">{s.equipment_count} équipement{s.equipment_count > 1 ? "s" : ""}{s.location ? " · localisé" : " · non localisé"}</p>
                </button>
              </li>
            ))}
          </ul>
          <Card as="section" aria-label="Équipements" className="lg:col-span-2">
            <CardHeader title={site ? `Équipements — ${site.name}` : "Équipements"} action={manage && site ? <Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => setAddEq(true)}>Ajouter</Button> : undefined} />
            {equipment.loading ? <SkeletonList count={2} /> : equipment.data?.length ? (
              <ul className="divide-y divide-lineSoft">
                {equipment.data.map((e) => (
                  <li key={e.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0"><p className="font-semibold text-ink">{e.name}</p>
                      <p className="text-xs text-ash">{[e.building_name, e.location_detail, e.category_name].filter(Boolean).join(" · ") || "—"}{e.warranty_ends_on ? ` · garantie jusqu’au ${shortDate(e.warranty_ends_on)}` : ""}</p></div>
                    <div className="flex items-center gap-2"><Badge tone={EQ_STATUS[e.status]?.tone ?? "gray"}>{EQ_STATUS[e.status]?.label ?? e.status}</Badge>
                      <Button size="sm" variant="outline" leftIcon={<QrCode aria-hidden className="h-4 w-4" />} onClick={() => setQr(e)}>QR</Button></div>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-ash">Aucun équipement sur ce site.</p>}
          </Card>
        </div>
      )}
      <Modal open={addSite} onClose={() => setAddSite(false)} title="Ajouter un site" size="md"><SiteForm onDone={() => { setAddSite(false); void sites.reload(); }} /></Modal>
      {site ? <Modal open={addEq} onClose={() => setAddEq(false)} title={`Nouvel équipement — ${site.name}`} size="lg"><EquipmentForm site={site} onDone={() => { setAddEq(false); void equipment.reload(); void sites.reload(); }} /></Modal> : null}
      {qr ? <QrModal eq={qr} onClose={() => setQr(null)} /> : null}
    </>
  );
}
