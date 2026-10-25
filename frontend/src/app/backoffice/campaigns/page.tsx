"use client";
import { useCallback, useEffect, useState } from "react";
import { BarChart3, Pencil, Play, Power, PowerOff, Sparkles } from "lucide-react";
import { Alert, Badge, Button, Checkbox, ConfirmDialog, DataTable, EmptyState, Input, Modal, PageHeader, Select, Tabs, TextField, TextareaField, type Column } from "@/components/ds";
import { AnnouncementPreview } from "../announcements/AnnouncementPreview";
import { ApiError } from "@/lib/api";
import { allowedFor, groupedDestinations, type AppDestination, type Role } from "@/lib/announcementPreview";
import { bo, boError, fieldErrors, pct, type Page } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { Drawer, FilterSelect, KV, dd, useNotice } from "../_components/ui";

interface Campaign {
  id: number; key: string; name: string; trigger: string; trigger_label: string; audience: Role; audience_label: string; goal: string; is_active: boolean;
  marketing: boolean; send_push: boolean; feature: string | null; features: string[]; missing_features: string[]; priority: number; title: string; body: string;
  action_label: string; action_value: string; starts_at: string | null; ends_at: string | null; activated_at: string | null; version: number; updated_at: string;
  sent?: number; converted?: number;
}
interface Stats {
  scheduled: number; sent: number; push: number; goal_met_before_send: number; skipped: number; skipped_reasons: Record<string, number>; cancelled: number;
  opened: number; converted: number; open_rate: number | null; conversion_rate: number | null;
}
/** Ce que verra le destinataire : même calcul que l'envoi réel (serveur). */
interface Preview {
  in_app: { title: string; body: string; action: null | { label: string; destination: { label: string; detail?: string }; app: string; web: string | null } };
  push: { enabled: boolean; title: string; body: string; channel: string; deeplink: string; weekly_limit: number };
  rules: { marketing: boolean; consent_required: boolean; send_hours: string; timezone: string; min_gap_hours: number; features: string[]; missing_features: string[] };
}
interface Detail extends Campaign {
  communes: string[]; progress: string[]; delay_hours: number; inactive_days: number; max_age_days: number; min_gap_hours: number;
  stats: Stats; preview: Preview; audience_estimate: number | null;
}
interface Meta {
  triggers: { id: string; label: string; audiences: Role[]; goal: string }[];
  audiences: { id: Role; label: string }[];
  progress: { id: string; label: string }[];
  destinations: AppDestination[];
  deployed_features: string[];
  rules: { weekly_push_limit: number; send_hours: string; sms: boolean };
}
interface Send { id: number; user: string; ref: string; status: string; status_label: string; reason: string; push: boolean; due_at: string; sent_at: string | null; converted_at: string | null; created_at: string }

const REASONS: Record<string, string> = {
  opted_out: "Désinscrit des conseils et nouveautés", no_consent: "Sans consentement marketing", push_quota: "Limite de push atteinte : message dans l’application seulement",
  quiet_hours: "Hors des heures autorisées", priority: "Activité prioritaire (Tratra Flash, réservation, alerte)", frequency: "Trop proche du message précédent",
  goal_met: "Objectif déjà atteint", campaign_inactive: "Campagne désactivée", account_inactive: "Compte désactivé",
};
const SEND_TONE: Record<string, "gray" | "info" | "success" | "warning" | "danger"> = { scheduled: "info", sent: "success", skipped: "warning", goal_met: "gray", cancelled: "gray" };
const reason = (r: string) => REASONS[r] ?? r;
const localInput = (iso: string | null) => (iso ? new Date(new Date(iso).getTime() - new Date(iso).getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "");
const toIso = (local: string) => (local ? new Date(local).toISOString() : null);
const num = (v: string) => (v === "" ? "" : Number(v));

type Tab = "message" | "rules" | "preview" | "stats" | "history";

function Editor({ id, meta, manage, onClose, onChanged }: { id: number | null; meta: Meta | null; manage: boolean; onClose: () => void; onChanged: (c: Detail, notice: string) => void }) {
  const [item, setItem] = useState<Detail | null>(null);
  const [f, setF] = useState<Record<string, string | number | boolean>>({});
  const [progress, setProgress] = useState<string[]>([]);
  const [tab, setTab] = useState<Tab>("message");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [sends, setSends] = useState<Page<Send> | null>(null);
  const [sendStatus, setSendStatus] = useState("");
  const [page, setPage] = useState(1);

  const fill = useCallback((d: Detail) => {
    setItem(d);
    setProgress(d.progress);
    setF({ name: d.name, title: d.title, body: d.body, action_label: d.action_label, action_value: d.action_value, marketing: d.marketing, send_push: d.send_push,
      trigger: d.trigger, audience: d.audience, communes: d.communes.join(", "), delay_hours: d.delay_hours, inactive_days: d.inactive_days, max_age_days: d.max_age_days,
      min_gap_hours: d.min_gap_hours, priority: d.priority, starts_at: localInput(d.starts_at), ends_at: localInput(d.ends_at) });
  }, []);
  useEffect(() => {
    setItem(null); setErrors({}); setFailure(""); setSaved(""); setTab("message"); setSends(null); setPage(1); setSendStatus("");
    if (id === null) return;
    bo.get<Detail>(`/campaigns/${id}/?estimate=1`).then(fill).catch((e) => setFailure(boError(e, "Campagne indisponible.")));
  }, [id, fill]);
  useEffect(() => {
    if (id === null || tab !== "history") return;
    bo.get<Page<Send>>(`/campaigns/${id}/sends/?page=${page}${sendStatus ? `&status=${sendStatus}` : ""}`).then(setSends).catch((e) => setFailure(boError(e, "Historique indisponible.")));
  }, [id, tab, page, sendStatus]);

  const audience = (f.audience as Role) ?? "clients";
  const trigger = meta?.triggers.find((t) => t.id === f.trigger);
  const dests = (meta?.destinations ?? []).filter((d) => !d.param_required);
  const dest = dests.find((d) => d.key === f.action_value) ?? null;
  const set = (k: string, v: string | number | boolean) => setF((cur) => ({ ...cur, [k]: v }));

  async function save() {
    if (!item) return;
    setBusy(true); setErrors({}); setFailure(""); setSaved("");
    const payload = { ...f, communes: String(f.communes ?? "").split(",").map((c) => c.trim()).filter(Boolean), progress, starts_at: toIso(String(f.starts_at ?? "")),
      ends_at: toIso(String(f.ends_at ?? "")), version: item.version };
    try {
      const result = await bo.patch<Detail>(`/campaigns/${item.id}/`, payload);
      fill({ ...result, audience_estimate: item.audience_estimate });
      setSaved(result.is_active ? "Enregistré : s’applique aux prochains envois." : "Enregistré (campagne désactivée).");
      onChanged(result, "Campagne enregistrée.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setFailure("Cette campagne a été modifiée entre-temps : fermez puis rouvrez-la pour repartir de la dernière version.");
      else { setErrors(fieldErrors(e)); setFailure(boError(e, "La campagne n’a pas pu être enregistrée.")); }
    } finally {
      setBusy(false);
    }
  }

  const locked = !manage;
  const tabs: { id: Tab; label: string }[] = [{ id: "message", label: "Message" }, { id: "rules", label: "Ciblage et rythme" }, { id: "preview", label: "Aperçu" },
    { id: "stats", label: "Statistiques" }, { id: "history", label: "Historique" }];
  const editing = tab === "message" || tab === "rules";

  return (
    <Drawer open={id !== null} onClose={onClose} dismissible={!busy} width="xl" title={item ? item.name : "Campagne"}
      description={item ? `${item.trigger_label} · ${item.audience_label} · objectif : ${item.goal}` : undefined}
      footer={editing && manage && item ? <>
        <span role="status" className={`mr-auto text-sm font-semibold ${failure ? "text-dangerInk" : "text-successInk"}`}>{failure ? "Non enregistré : voir le message." : saved}</span>
        <Button variant="outline" onClick={onClose} disabled={busy}>Fermer</Button><Button loading={busy} onClick={() => void save()}>Enregistrer</Button></> : <Button variant="outline" onClick={onClose}>Fermer</Button>}>
      {!item ? (failure ? <Alert tone="danger">{failure}</Alert> : <p className="text-sm text-ash">Chargement…</p>) : (
        <div className="space-y-4">
          <Tabs items={tabs} value={tab} onChange={setTab} ariaLabel="Sections de la campagne" idPrefix="campaign" />
          {item.is_active ? <Alert tone="info">Campagne active : les modifications du message s’appliquent aux prochains envois. Déclencheur et audience ne changent que campagne désactivée.</Alert> : null}
          {tab === "message" ? (
            <div className="space-y-4">
              <TextField label="Nom interne" value={String(f.name ?? "")} error={errors.name} disabled={locked} onChange={(e) => set("name", e.target.value)} />
              <TextField label="Titre" required value={String(f.title ?? "")} error={errors.title} disabled={locked} hint="140 caractères au plus ; le push en affiche moins." onChange={(e) => set("title", e.target.value)} />
              <TextareaField label="Message" required rows={4} value={String(f.body ?? "")} error={errors.body} disabled={locked} hint={`${String(f.body ?? "").length}/600 — n’annoncez jamais une fonction non déployée ni une promesse invérifiable.`} onChange={(e) => set("body", e.target.value)} />
              <div className="grid gap-4 sm:grid-cols-2">
                <TextField label="Libellé du bouton" value={String(f.action_label ?? "")} error={errors.action_label} disabled={locked} onChange={(e) => set("action_label", e.target.value)} />
                <label className="block text-sm font-semibold text-ink">Écran ouvert
                  <Select className="mt-1.5" value={String(f.action_value ?? "")} disabled={locked} onChange={(e) => set("action_value", e.target.value)}>
                    <option value="">Aucun (le message seul)</option>
                    {groupedDestinations(dests, [audience]).map(([group, items]) => (
                      <optgroup key={group} label={group}>{items.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}</optgroup>
                    ))}
                    {dest && !allowedFor(dest, [audience]) ? <option value={dest.key}>{dest.label} (non ouvert à cette audience)</option> : null}
                  </Select>
                  <span className="text-xs font-normal text-ash">Seuls les écrans ouverts à l’audience sont proposés ; l’application et le site vérifient de nouveau les droits.</span></label>
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-2">
                <Checkbox label="Marketing (consentement exigé)" checked={Boolean(f.marketing)} disabled={locked} onChange={(e) => set("marketing", e.target.checked)} />
                <Checkbox label="Notification push (si autorisée)" checked={Boolean(f.send_push)} disabled={locked} onChange={(e) => set("send_push", e.target.checked)} />
              </div>
              {failure ? <Alert tone="danger">{failure}</Alert> : null}
            </div>
          ) : null}
          {tab === "rules" ? (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-semibold text-ink">Déclencheur
                  <Select className="mt-1.5" value={String(f.trigger ?? "")} disabled={locked || item.is_active} onChange={(e) => set("trigger", e.target.value)}>
                    {meta?.triggers.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                  </Select>{errors.trigger ? <span role="alert" className="text-xs text-dangerInk">{errors.trigger}</span> : <span className="text-xs font-normal text-ash">Objectif : {trigger?.goal ?? "—"}</span>}</label>
                <label className="block text-sm font-semibold text-ink">Audience
                  <Select className="mt-1.5" value={audience} disabled={locked || item.is_active} onChange={(e) => set("audience", e.target.value)}>
                    {meta?.audiences.map((a) => <option key={a.id} value={a.id} disabled={Boolean(trigger && !trigger.audiences.includes(a.id))}>{a.label}</option>)}
                  </Select>{errors.audience ? <span role="alert" className="text-xs text-dangerInk">{errors.audience}</span> : null}</label>
              </div>
              <TextField label="Communes ou villes ciblées" optional disabled={locked} value={String(f.communes ?? "")} hint="Séparées par des virgules. Communes DÉCLARÉES dans les profils, jamais la position GPS. Vide = partout." onChange={(e) => set("communes", e.target.value)} />
              <fieldset><legend className="mb-1.5 text-sm font-semibold text-ink">Progression ciblée <span className="text-xs font-normal text-ash">(aucune = toutes)</span></legend>
                <div className="flex flex-wrap gap-x-6 gap-y-2">
                  {meta?.progress.map((p) => <Checkbox key={p.id} label={p.label} disabled={locked} checked={progress.includes(p.id)} onChange={(e) => setProgress((cur) => (e.target.checked ? [...cur, p.id] : cur.filter((x) => x !== p.id)))} />)}
                </div></fieldset>
              <div className="grid gap-4 sm:grid-cols-3">
                {f.trigger === "inactive"
                  ? <TextField label="Jours sans connexion" type="number" min={1} max={365} disabled={locked} value={String(f.inactive_days ?? "")} error={errors.inactive_days} onChange={(e) => set("inactive_days", num(e.target.value))} />
                  : <TextField label="Délai après l’événement (heures)" type="number" min={0} disabled={locked} value={String(f.delay_hours ?? "")} error={errors.delay_hours} onChange={(e) => set("delay_hours", num(e.target.value))} />}
                <TextField label="Fenêtre (jours)" type="number" min={1} max={90} disabled={locked} value={String(f.max_age_days ?? "")} error={errors.max_age_days} hint="Événements plus anciens ignorés." onChange={(e) => set("max_age_days", num(e.target.value))} />
                <TextField label="Écart minimal (heures)" type="number" min={0} disabled={locked} value={String(f.min_gap_hours ?? "")} error={errors.min_gap_hours} hint="Avec le message d’engagement précédent." onChange={(e) => set("min_gap_hours", num(e.target.value))} />
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <TextField label="Priorité" type="number" min={1} max={999} disabled={locked} value={String(f.priority ?? "")} error={errors.priority} hint="Plus petit = prioritaire." onChange={(e) => set("priority", num(e.target.value))} />
                <label className="block text-sm font-semibold text-ink">Début <span className="text-xs font-normal text-ash">(facultatif)</span>
                  <Input className="mt-1.5" type="datetime-local" disabled={locked} value={String(f.starts_at ?? "")} onChange={(e) => set("starts_at", e.target.value)} />{errors.starts_at ? <span role="alert" className="text-xs text-dangerInk">{errors.starts_at}</span> : null}</label>
                <label className="block text-sm font-semibold text-ink">Fin <span className="text-xs font-normal text-ash">(facultatif)</span>
                  <Input className="mt-1.5" type="datetime-local" disabled={locked} value={String(f.ends_at ?? "")} onChange={(e) => set("ends_at", e.target.value)} />{errors.ends_at ? <span role="alert" className="text-xs text-dangerInk">{errors.ends_at}</span> : null}</label>
              </div>
              {failure ? <Alert tone="danger">{failure}</Alert> : null}
            </div>
          ) : null}
          {tab === "preview" ? (
            <div className="space-y-3">
              <p className="text-sm text-inkSoft">Aperçu de la version enregistrée : enregistrez vos modifications pour les y voir.</p>
              <AnnouncementPreview title={item.preview.in_app.title} body={item.preview.in_app.body} imageSrc={null} sendPush={item.preview.push.enabled}
                actionKind={item.preview.in_app.action ? "deeplink" : "none"} actionLabel={item.preview.in_app.action?.label ?? ""}
                destination={item.preview.in_app.action?.destination ?? null} webHref={item.preview.in_app.action?.web}
                notes={[
                  ...(item.preview.rules.missing_features.length ? [{ tone: "danger" as const, text: `Fonction non déclarée déployée (${item.preview.rules.missing_features.join(", ")}) : activation impossible.` }] : []),
                  { tone: "info" as const, text: `Envoi entre ${item.preview.rules.send_hours} (${item.preview.rules.timezone}), au plus ${item.preview.push.weekly_limit} push d’engagement par semaine et par compte ; aucun SMS.` },
                  ...(item.preview.rules.consent_required ? [{ tone: "info" as const, text: "Message marketing : seuls les comptes ayant donné leur consentement le reçoivent." }] : []),
                ]} />
              <KV items={[["Lien de l’application", item.preview.push.deeplink], ["Canal Android", item.preview.push.channel], ["Équivalent sur le site", item.preview.in_app.action?.web ?? "—"]]} />
            </div>
          ) : null}
          {tab === "stats" ? (
            <div className="space-y-4">
              <KV items={[["Nouveaux destinataires au prochain passage (estimation)", item.audience_estimate ?? "—"], ["Programmés", item.stats.scheduled], ["Envoyés", item.stats.sent], ["Dont push", item.stats.push],
                ["Ouverts", `${item.stats.opened} (${pct(item.stats.open_rate)})`], ["Objectif atteint après envoi", `${item.stats.converted} (${pct(item.stats.conversion_rate)})`],
                ["Objectif atteint avant envoi", item.stats.goal_met_before_send], ["Annulés", item.stats.cancelled]]} />
              <div><h3 className="mb-1 text-sm font-bold text-ink">Non envoyés ({item.stats.skipped})</h3>
                {Object.keys(item.stats.skipped_reasons).length ? (
                  <ul className="space-y-1 text-sm text-inkSoft">{Object.entries(item.stats.skipped_reasons).map(([k, v]) => <li key={k}>{reason(k)} : {v}</li>)}</ul>
                ) : <p className="text-sm text-inkSoft">Aucun.</p>}</div>
              <p className="text-xs text-ash">Statistiques agrégées ; l’historique n’affiche que le prénom et l’initiale du nom.</p>
            </div>
          ) : null}
          {tab === "history" ? (
            <div className="space-y-3">
              <FilterSelect label="Statut" value={sendStatus} onChange={(v) => { setSendStatus(v); setPage(1); }}
                options={[["", "Tous"], ["scheduled", "Programmés"], ["sent", "Envoyés"], ["skipped", "Non envoyés"], ["goal_met", "Objectif déjà atteint"], ["cancelled", "Annulés"]]} />
              {sends && sends.results.length ? (
                <ul className="divide-y divide-line rounded-xl ring-1 ring-line">
                  {sends.results.map((s) => (
                    <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5 text-sm">
                      <span className="min-w-0"><span className="font-semibold text-ink">{s.user}</span>{s.ref ? <span className="ml-2 text-xs text-ash">{s.ref}</span> : null}
                        <span className="block text-xs text-ash">{s.sent_at ? <>Envoyé {dd(s.sent_at)}{s.push ? " · push" : " · dans l’application"}</> : <>Prévu {dd(s.due_at)}</>}{s.reason ? ` · ${reason(s.reason)}` : ""}{s.converted_at ? " · objectif atteint" : ""}</span></span>
                      <Badge tone={SEND_TONE[s.status] ?? "gray"}>{s.status_label}</Badge>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-sm text-inkSoft">{sends ? "Aucun envoi." : "Chargement…"}</p>}
              {sends && (sends.next || sends.previous) ? (
                <div className="flex justify-between"><Button size="sm" variant="outline" disabled={!sends.previous} onClick={() => setPage((p) => p - 1)}>Précédents</Button>
                  <Button size="sm" variant="outline" disabled={!sends.next} onClick={() => setPage((p) => p + 1)}>Suivants</Button></div>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </Drawer>
  );
}

export default function CampaignsAdminPage() {
  const { can } = useBo();
  const manage = can("announcements.manage");
  const [notice, setNotice] = useNotice();
  const [rows, setRows] = useState<Campaign[] | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [filters, setFilters] = useState({ active: "", audience: "", trigger: "" });
  const [failure, setFailure] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [toggle, setToggle] = useState<{ item: Campaign; estimate: number | null } | null>(null);
  const [runAsk, setRunAsk] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();
    try {
      const r = await bo.get<{ results: Campaign[]; meta: Meta }>(`/campaigns/${q ? `?${q}` : ""}`);
      setRows(r.results);
      setMeta(r.meta);
    } catch (e) {
      setRows([]);
      setFailure(boError(e, "Campagnes indisponibles."));
    }
  }, [filters]);
  useEffect(() => { void load(); }, [load]);

  async function askToggle(item: Campaign) {
    setFailure("");
    let estimate: number | null = null;
    if (!item.is_active) {
      try { estimate = (await bo.get<Detail>(`/campaigns/${item.id}/?estimate=1`)).audience_estimate; } catch { /* estimation facultative */ }
    }
    setToggle({ item, estimate });
  }
  async function doToggle() {
    if (!toggle) return;
    setBusy(true);
    try {
      await bo.post(`/campaigns/${toggle.item.id}/${toggle.item.is_active ? "deactivate" : "activate"}/`, {});
      setNotice(toggle.item.is_active ? "Campagne désactivée : les envois programmés sont annulés." : "Campagne activée : premiers envois au prochain passage (toutes les 10 minutes).");
      void load();
    } catch (e) {
      setFailure(boError(e, "L’opération a échoué."));
    } finally {
      setBusy(false);
      setToggle(null);
    }
  }
  async function doRun() {
    setBusy(true);
    try {
      const r = await bo.post<Record<string, number>>("/campaigns/run/", {});
      const sent = (r.sent ?? 0) + (r.sent_in_app ?? 0);
      setNotice(`Passage exécuté : ${r.scheduled ?? 0} envoi(s) programmé(s), ${sent} message(s) envoyé(s).`);
      void load();
    } catch (e) {
      setFailure(boError(e, "Le passage a échoué."));
    } finally {
      setBusy(false);
      setRunAsk(false);
    }
  }

  const deployed = (c: Campaign) => !c.missing_features.length;
  const columns: Column<Campaign>[] = [
    { key: "name", header: "Campagne", primary: true, cell: (c) => <span className="min-w-0"><span className="block font-semibold text-ink">{c.name}</span><span className="block text-xs text-ash">{c.trigger_label}</span></span> },
    { key: "aud", header: "Audience", cell: (c) => <Badge tone={c.audience === "artisans" ? "accent" : c.audience === "companies" ? "night" : "primary"}>{c.audience_label}</Badge> },
    { key: "goal", header: "Objectif", hideOnMobile: true, cell: (c) => <span className="text-sm text-inkSoft">{c.goal}</span> },
    { key: "res", header: "Résultats", hideOnMobile: true, cell: (c) => <span className="whitespace-nowrap text-sm"><span className="block text-ink">{c.sent ?? 0} envoyé{(c.sent ?? 0) > 1 ? "s" : ""}</span><span className="block text-xs text-ash">{c.converted ?? 0} objectif{(c.converted ?? 0) > 1 ? "s" : ""} atteint{(c.converted ?? 0) > 1 ? "s" : ""}</span></span> },
    { key: "status", header: "Statut", cell: (c) => (c.is_active ? <Badge tone="success">Active</Badge> : !deployed(c) ? <span title={`Non déclarée déployée : ${c.missing_features.join(", ")}`}><Badge tone="warning">Fonction non déployée</Badge></span> : <Badge tone="gray">Désactivée</Badge>) },
    {
      key: "act", header: "Actions", align: "right", cell: (c) => (
        <span className="inline-flex flex-nowrap justify-end gap-2 whitespace-nowrap">
          <Button size="sm" variant="outline" leftIcon={manage ? <Pencil aria-hidden className="h-4 w-4" /> : <BarChart3 aria-hidden className="h-4 w-4" />} onClick={() => setOpenId(c.id)}>{manage ? "Modifier" : "Voir"}</Button>
          {manage ? (c.is_active
            ? <Button size="sm" variant="outline" leftIcon={<PowerOff aria-hidden className="h-4 w-4" />} onClick={() => void askToggle(c)}>Désactiver</Button>
            : <Button size="sm" disabled={!deployed(c)} leftIcon={<Power aria-hidden className="h-4 w-4" />} onClick={() => void askToggle(c)}>Activer</Button>) : null}
        </span>
      ),
    },
  ];
  const active = rows?.filter((r) => r.is_active).length ?? 0;

  return (
    <>
      <PageHeader title="Engagement automatisé" description="Messages déclenchés par des événements réels (inscription, profil, identité, offres, commandes, activité), envoyés dans l’application et en push si autorisé — jamais par SMS. Chaque campagne s’arrête dès que son objectif est atteint."
        actions={manage ? <Button size="sm" variant="outline" leftIcon={<Play aria-hidden className="h-4 w-4" />} onClick={() => setRunAsk(true)} disabled={!active}>Exécuter un passage</Button> : null} />
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      {meta ? (
        <Alert tone="info" className="mb-4">
          Règles appliquées à chaque envoi : au plus {meta.rules.weekly_push_limit} push d’engagement par semaine et par compte, envoi entre {meta.rules.send_hours}, priorité absolue à Tratra Flash,
          aux réservations et aux alertes de sécurité, consentement exigé pour le marketing, désinscription par la catégorie « Conseils, rappels et nouveautés ».
          {" "}Fonctions déclarées déployées : {meta.deployed_features.length ? meta.deployed_features.join(", ") : "aucune"}.
        </Alert>
      ) : null}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <FilterSelect label="Statut" value={filters.active} onChange={(v) => setFilters({ ...filters, active: v })} options={[["", "Toutes"], ["1", "Actives"], ["0", "Désactivées"]]} />
        <FilterSelect label="Audience" value={filters.audience} onChange={(v) => setFilters({ ...filters, audience: v })} options={[["", "Toutes"], ...(meta?.audiences.map((a) => [a.id, a.label] as [string, string]) ?? [])]} />
        <FilterSelect label="Déclencheur" value={filters.trigger} onChange={(v) => setFilters({ ...filters, trigger: v })} options={[["", "Tous"], ...(meta?.triggers.map((t) => [t.id, t.label] as [string, string]) ?? [])]} />
        <span className="ml-auto text-sm text-ash">{rows ? `${rows.length} campagne(s) · ${active} active(s)` : ""}</span>
      </div>
      <DataTable columns={columns} rows={rows ?? []} loading={rows === null} rowKey={(c) => c.id} caption="Campagnes d’engagement"
        empty={<EmptyState icon={<Sparkles aria-hidden className="h-6 w-6" />} title="Aucune campagne ne correspond" description="Modifiez les filtres." />} />

      <Editor id={openId} meta={meta} manage={manage} onClose={() => setOpenId(null)} onChanged={(_c, text) => { setNotice(text); void load(); }} />
      <Modal open={Boolean(toggle)} onClose={() => setToggle(null)} dismissible={!busy} title={toggle ? `${toggle.item.is_active ? "Désactiver" : "Activer"} « ${toggle.item.name} » ?` : ""}
        footer={<><Button variant="outline" onClick={() => setToggle(null)} disabled={busy}>Annuler</Button>
          <Button loading={busy} variant={toggle?.item.is_active ? "danger" : "primary"} onClick={() => void doToggle()}>{toggle?.item.is_active ? "Désactiver" : "Activer"}</Button></>}>
        {toggle ? (toggle.item.is_active
          ? <p className="text-sm text-inkSoft">Les envois programmés sont annulés et le message disparaît des flux. Les notifications déjà reçues restent dans l’historique des utilisateurs.</p>
          : <div className="space-y-2 text-sm text-inkSoft">
            <p><span className="font-semibold text-ink">{toggle.item.title}</span> — {toggle.item.body}</p>
            <p>{toggle.estimate !== null ? `Environ ${toggle.estimate} nouveau(x) destinataire(s) au prochain passage. ` : ""}Les règles (consentement, limite de push, heures, priorité opérationnelle) s’appliquent à chaque envoi.</p>
          </div>) : null}
      </Modal>
      <ConfirmDialog open={runAsk} onClose={() => setRunAsk(false)} loading={busy} onConfirm={() => void doRun()} tone="primary" confirmLabel="Exécuter maintenant"
        title="Exécuter un passage maintenant ?" description="Programme et envoie les messages dus des campagnes actives, avec exactement les mêmes règles que la tâche automatique (toutes les 10 minutes)." />
    </>
  );
}
