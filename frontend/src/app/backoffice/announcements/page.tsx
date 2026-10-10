"use client";
import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Alert, Badge, Button, Checkbox, ConfirmDialog, Input, Modal, PageHeader, Select, TextField, TextareaField, type Column } from "@/components/ds";
import { ApiError, apiFetch, upload } from "@/lib/api";
import { bo, boError, fieldErrors } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { patchForm } from "@/lib/uploadPatch";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { FilterBar, FilterSelect, KV, ListView, SearchBox, Tag, dt, useNotice } from "../_components/ui";

interface Announcement {
  id: number; title: string; body: string; image_url: string | null; kind: "service" | "promotion"; action_kind: "none" | "link" | "deeplink"; action_label: string; action_value: string;
  to_clients: boolean; to_artisans: boolean; to_companies: boolean; cities: string[]; audience: string[]; send_push: boolean; publish_at: string | null; expires_at: string | null;
  status: string; published_at: string | null; created_at: string; version: number;
}
interface Stats { status: string; audience_estimate: number; delivered: number; push: Record<string, number>; seen: number; opened: number; dismissed: number; seen_rate: number | null; open_rate: number | null }

const STATUS_FR: Record<string, string> = { draft: "Brouillon", scheduled: "Programmée", published: "Publiée", expired: "Expirée", cancelled: "Annulée" };
const STATUS_TONE: Record<string, "gray" | "info" | "success" | "warning" | "danger"> = { draft: "gray", scheduled: "info", published: "success", expired: "warning", cancelled: "danger" };
const SCREENS: [string, string][] = [["reviews", "Mes avis"], ["notifications", "Notifications"], ["kyc", "Vérification d’identité"], ["announcement", "Annonces"]];
const localInput = (iso: string | null) => (iso ? new Date(new Date(iso).getTime() - new Date(iso).getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "");
const toIso = (local: string) => (local ? new Date(local).toISOString() : null);

function Form({ open, item, onClose, onSaved }: { open: boolean; item: Announcement | null; onClose: () => void; onSaved: (a: Announcement) => void }) {
  const blank = { title: "", body: "", kind: "service", to_clients: true, to_artisans: false, to_companies: false, cities: "", send_push: true, expires_at: "", action_kind: "none", action_label: "", action_value: "" };
  const [f, setF] = useState(blank);
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    setFile(null);
    setErrors({});
    setFailure("");
    setF(item ? { title: item.title, body: item.body, kind: item.kind, to_clients: item.to_clients, to_artisans: item.to_artisans, to_companies: item.to_companies, cities: item.cities.join(", "), send_push: item.send_push, expires_at: localInput(item.expires_at), action_kind: item.action_kind, action_label: item.action_label, action_value: item.action_value } : blank);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, item]);

  async function save() {
    setBusy(true);
    setErrors({});
    setFailure("");
    const cities = f.cities.split(",").map((c) => c.trim()).filter(Boolean);
    const payload = { title: f.title, body: f.body, kind: f.kind, to_clients: f.to_clients, to_artisans: f.to_artisans, to_companies: f.to_companies, cities, send_push: f.send_push,
      expires_at: toIso(f.expires_at), action_kind: f.action_kind, action_label: f.action_kind === "none" ? "" : f.action_label, action_value: f.action_kind === "none" ? "" : f.action_value, ...(item ? { version: item.version } : {}) };
    try {
      let saved: Announcement;
      if (file) {
        const form = new FormData();
        Object.entries(payload).forEach(([k, v]) => { if (k !== "cities" && v !== null && v !== undefined) form.append(k, String(v)); });
        cities.forEach((c) => form.append("cities", c));
        form.append("image", file);
        saved = item ? await patchForm<Announcement>(`/backoffice/announcements/${item.id}/`, form) : await upload<Announcement>("/backoffice/announcements/", form);
      } else {
        saved = item ? await bo.patch<Announcement>(`/announcements/${item.id}/`, payload) : await bo.post<Announcement>("/announcements/", payload);
      }
      onSaved(saved);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setFailure("Cette annonce a été modifiée entre-temps : fermez puis rouvrez-la pour repartir de la dernière version.");
      else {
        setErrors(fieldErrors(e));
        const data = e instanceof ApiError && e.data && typeof e.data === "object" ? (e.data as Record<string, unknown>) : {};
        const flat = Object.fromEntries(Object.entries(data).filter(([, v]) => Array.isArray(v)).map(([k, v]) => [k, String((v as unknown[])[0])]));
        setErrors((cur) => ({ ...cur, ...flat }));
        setFailure(Object.keys(flat).length ? "Corrigez les champs signalés." : boError(e, "L’annonce n’a pas pu être enregistrée."));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} dismissible={!busy} size="lg" title={item ? `Modifier « ${item.title} »` : "Nouvelle annonce"} description="Enregistrée en brouillon : rien n’est envoyé avant la publication ou la programmation."
      footer={<><Button variant="outline" onClick={onClose} disabled={busy}>Annuler</Button><Button loading={busy} onClick={() => void save()}>Enregistrer le brouillon</Button></>}>
      <div className="space-y-4">
        <TextField label="Titre" required value={f.title} error={errors.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <TextareaField label="Contenu" required value={f.body} error={errors.body} onChange={(e) => setF({ ...f, body: e.target.value })} rows={4} />
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm font-semibold text-ink">Nature
            <Select className="mt-1.5" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="service">Information de service</option><option value="promotion">Promotion (consentement marketing requis)</option></Select></label>
          <label className="block text-sm font-semibold text-ink">Expiration <span className="text-xs font-normal text-ash">(facultatif)</span>
            <Input className="mt-1.5" type="datetime-local" value={f.expires_at} onChange={(e) => setF({ ...f, expires_at: e.target.value })} />{errors.expires_at ? <span role="alert" className="text-xs text-dangerInk">{errors.expires_at}</span> : null}</label>
        </div>
        <fieldset><legend className="mb-1.5 text-sm font-semibold text-ink">Destinataires</legend>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <Checkbox label="Clients" checked={f.to_clients} onChange={(e) => setF({ ...f, to_clients: e.target.checked })} />
            <Checkbox label="Artisans" checked={f.to_artisans} onChange={(e) => setF({ ...f, to_artisans: e.target.checked })} />
            <Checkbox label="Entreprises" checked={f.to_companies} onChange={(e) => setF({ ...f, to_companies: e.target.checked })} />
          </div>
          {errors.detail || errors.to_clients ? <p role="alert" className="mt-1 text-xs text-dangerInk">{errors.detail ?? errors.to_clients}</p> : null}
        </fieldset>
        <TextField label="Villes ciblées" optional hint="Séparées par des virgules. Villes DÉCLARÉES dans les profils : jamais la position GPS. Vide = partout." value={f.cities} onChange={(e) => setF({ ...f, cities: e.target.value })} />
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="block text-sm font-semibold text-ink">Action
            <Select className="mt-1.5" value={f.action_kind} onChange={(e) => setF({ ...f, action_kind: e.target.value, action_value: "" })}><option value="none">Aucune</option><option value="link">Lien web (https)</option><option value="deeplink">Écran de l’application</option></Select></label>
          {f.action_kind !== "none" ? <TextField label="Libellé du bouton" value={f.action_label} onChange={(e) => setF({ ...f, action_label: e.target.value })} /> : null}
          {f.action_kind === "link" ? <TextField label="Adresse https" value={f.action_value} error={errors.action_value} onChange={(e) => setF({ ...f, action_value: e.target.value })} placeholder="https://tratra.net/…" /> : null}
          {f.action_kind === "deeplink" ? (
            <label className="block text-sm font-semibold text-ink">Écran
              <Select className="mt-1.5" value={f.action_value} onChange={(e) => setF({ ...f, action_value: e.target.value })}><option value="">Choisir…</option>{SCREENS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
              {errors.action_value ? <span role="alert" className="text-xs text-dangerInk">{errors.action_value}</span> : null}</label>
          ) : null}
        </div>
        <label className="block text-sm font-semibold text-ink">Image <span className="text-xs font-normal text-ash">(facultatif — ré-encodée, sans métadonnées)</span>
          <Input className="mt-1.5" type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />{errors.image ? <span role="alert" className="text-xs text-dangerInk">{errors.image}</span> : null}</label>
        <Checkbox label="Envoyer aussi une notification push" checked={f.send_push} onChange={(e) => setF({ ...f, send_push: e.target.checked })} />
        {failure ? <Alert tone="danger">{failure}</Alert> : null}
      </div>
    </Modal>
  );
}

export default function AnnouncementsAdminPage() {
  const { can } = useBo();
  const [notice, setNotice] = useNotice();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const list = useBoList<Announcement>("/announcements/", { q: useDebounced(q), status, kind });
  const [form, setForm] = useState<{ open: boolean; item: Announcement | null }>({ open: false, item: null });
  const [confirm, setConfirm] = useState<{ op: "publish" | "cancel" | "delete"; item: Announcement; estimate?: number } | null>(null);
  const [schedule, setSchedule] = useState<Announcement | null>(null);
  const [when, setWhen] = useState("");
  const [stats, setStats] = useState<{ item: Announcement; data: Stats } | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const manage = can("announcements.manage");

  async function ask(op: "publish" | "cancel" | "delete", item: Announcement) {
    setFailure("");
    let estimate: number | undefined;
    if (op === "publish") {
      try { estimate = (await bo.get<Stats>(`/announcements/${item.id}/stats/`)).audience_estimate; } catch { /* estimation facultative */ }
    }
    setConfirm({ op, item, estimate });
  }
  async function run() {
    if (!confirm) return;
    setBusy(true);
    setFailure("");
    try {
      const { op, item } = confirm;
      if (op === "delete") await fetchDelete(item.id);
      else await bo.post(`/announcements/${item.id}/${op}/`, {});
      setConfirm(null);
      setNotice(op === "publish" ? "Annonce publiée : la diffusion est en cours." : op === "cancel" ? "Annonce annulée." : "Brouillon supprimé.");
      list.reload();
    } catch (e) {
      setConfirm(null);
      setFailure(boError(e, "L’opération a échoué."));
    } finally {
      setBusy(false);
    }
  }
  async function fetchDelete(id: number) {
    const res = await apiFetch(`/backoffice/announcements/${id}/`, { method: "DELETE" });
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
  }
  async function doSchedule() {
    if (!schedule) return;
    setBusy(true);
    setFailure("");
    try {
      await bo.post(`/announcements/${schedule.id}/schedule/`, { publish_at: toIso(when) });
      setSchedule(null);
      setNotice("Annonce programmée.");
      list.reload();
    } catch (e) {
      setFailure(boError(e, "La programmation a échoué."));
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<Announcement>[] = [
    { key: "title", header: "Annonce", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.title}</span> },
    { key: "kind", header: "Nature", cell: (r) => <Badge tone={r.kind === "promotion" ? "accent" : "primary"}>{r.kind === "promotion" ? "Promotion" : "Service"}</Badge> },
    { key: "aud", header: "Destinataires", hideOnMobile: true, cell: (r) => `${r.audience.join(", ") || "—"}${r.cities.length ? ` · ${r.cities.join(", ")}` : ""}` },
    { key: "status", header: "Statut", cell: (r) => <Badge tone={STATUS_TONE[r.status] ?? "gray"}>{STATUS_FR[r.status] ?? r.status}</Badge> },
    { key: "when", header: "Publication", hideOnMobile: true, cell: (r) => dt(r.status === "published" ? r.published_at : r.publish_at) },
    { key: "exp", header: "Expire", hideOnMobile: true, cell: (r) => dt(r.expires_at) },
    {
      key: "act", header: "", align: "right", cell: (r) => (
        <span className="flex flex-wrap justify-end gap-2">
          <Button size="sm" variant="outline" onClick={async () => { try { setStats({ item: r, data: await bo.get<Stats>(`/announcements/${r.id}/stats/`) }); } catch (e) { setFailure(boError(e, "Statistiques indisponibles.")); } }}>Statistiques</Button>
          {manage && (r.status === "draft" || r.status === "scheduled") ? (
            <>
              <Button size="sm" variant="outline" onClick={() => setForm({ open: true, item: r })}>Modifier</Button>
              <Button size="sm" variant="outline" onClick={() => { setWhen(""); setSchedule(r); }}>Programmer</Button>
              <Button size="sm" onClick={() => void ask("publish", r)}>Publier</Button>
            </>
          ) : null}
          {manage && r.status === "draft" ? <Button size="sm" variant="danger" onClick={() => void ask("delete", r)}>Supprimer</Button> : null}
          {manage && (r.status === "scheduled" || r.status === "published") ? <Button size="sm" variant="danger" onClick={() => void ask("cancel", r)}>Annuler</Button> : null}
        </span>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Annonces" description="Informations de service et promotions ciblées par rôle et par ville déclarée. Aucune promotion n’est envoyée sans le consentement marketing de l’utilisateur."
        actions={manage ? <Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => setForm({ open: true, item: null })}>Nouvelle annonce</Button> : null} />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      <FilterBar>
        <SearchBox value={q} onChange={setQ} placeholder="Titre…" />
        <FilterSelect label="Statut" value={status} onChange={setStatus} options={[["", "Tous"], ...Object.entries(STATUS_FR)]} />
        <FilterSelect label="Nature" value={kind} onChange={setKind} options={[["", "Toutes"], ["service", "Service"], ["promotion", "Promotion"]]} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} caption="Annonces" empty="Aucune annonce. Créez la première avec « Nouvelle annonce »." />

      <Form open={form.open} item={form.item} onClose={() => setForm({ open: false, item: null })} onSaved={() => { setForm({ open: false, item: null }); setNotice("Brouillon enregistré."); list.reload(); }} />
      <ConfirmDialog open={Boolean(confirm)} onClose={() => setConfirm(null)} loading={busy} onConfirm={() => void run()}
        tone={confirm?.op === "publish" ? "primary" : "danger"} confirmLabel={confirm?.op === "publish" ? "Publier maintenant" : confirm?.op === "cancel" ? "Annuler l’annonce" : "Supprimer le brouillon"}
        title={confirm?.op === "publish" ? `Publier « ${confirm.item.title} » ?` : confirm?.op === "cancel" ? `Annuler « ${confirm?.item.title} » ?` : `Supprimer « ${confirm?.item.title} » ?`}
        description={confirm?.op === "publish" ? `${confirm.estimate !== undefined ? `Environ ${confirm.estimate} compte(s) seront destinataires. ` : ""}La diffusion démarre immédiatement et ne peut plus être modifiée : on peut seulement l’annuler.${confirm.item.kind === "promotion" ? " Seuls les comptes ayant donné leur consentement marketing la recevront." : ""}` : confirm?.op === "cancel" ? "Elle disparaît des flux des utilisateurs ; les notifications déjà reçues restent dans leur historique." : "Cette action est définitive."} />
      <Modal open={Boolean(schedule)} onClose={() => setSchedule(null)} dismissible={!busy} title="Programmer la publication" size="sm"
        footer={<><Button variant="outline" onClick={() => setSchedule(null)} disabled={busy}>Annuler</Button><Button loading={busy} disabled={!when} onClick={() => void doSchedule()}>Programmer</Button></>}>
        <label className="block text-sm font-semibold text-ink">Date et heure de publication<Input className="mt-1.5" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></label>
        <p className="mt-2 text-xs text-ash">Publiée automatiquement à l’heure choisie (vérification chaque minute). Doit être dans le futur.</p>
      </Modal>
      <Modal open={Boolean(stats)} onClose={() => setStats(null)} title={`Statistiques — ${stats?.item.title ?? ""}`}>
        {stats ? (
          <div className="space-y-4">
            <KV items={[["Statut", <Tag key="s" value="x" label={STATUS_FR[stats.data.status]} tone={STATUS_TONE[stats.data.status]} />], ["Audience estimée", stats.data.audience_estimate], ["Livraisons", stats.data.delivered], ["Vues", `${stats.data.seen}${stats.data.seen_rate !== null ? ` (${Math.round(stats.data.seen_rate * 100)} %)` : ""}`],
              ["Ouvertures", `${stats.data.opened}${stats.data.open_rate !== null ? ` (${Math.round(stats.data.open_rate * 100)} %)` : ""}`], ["Masquées", stats.data.dismissed]]} />
            <div><h3 className="mb-1 text-sm font-bold text-ink">Notifications push</h3>
              <p className="text-sm text-inkSoft">{Object.keys(stats.data.push).length ? Object.entries(stats.data.push).map(([k, v]) => `${k} : ${v}`).join(" · ") : "Aucun envoi push."}</p></div>
            <p className="text-xs text-ash">Statistiques agrégées : aucune identité d’utilisateur n’est affichée.</p>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
