"use client";
import { useEffect, useState } from "react";
import { Alert, Badge, Button, PageHeader, SkeletonStats, Stat, type Column } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { DateRange, FilterBar, FilterSelect, ListView, SearchBox, Section, dt } from "../_components/ui";

interface Summary {
  window_hours: number; notifications: number;
  push: { by_status: Record<string, number>; failed: number; sent: number; queued_stuck: number };
  by_category: Record<string, number>;
  devices: { total: number; by_platform: Record<string, number>; active_7d: number };
  otp: { requested: number; used: number; by_purpose: Record<string, number> };
  integrations: { push_fcm: { configured: boolean }; sms: { provider: string | null; ready: boolean }; email: { backend: string; real_delivery: boolean } };
}
interface Row { id: number; user_id: number; user: string; type: string; category: string; title: string | null; push_status: string | null; push_sent_at: string | null; is_read: boolean; created_at: string }

const PUSH_FR: Record<string, string> = { sent: "Envoyé", failed: "Échec", queued: "En file", no_device: "Aucun appareil", disabled: "Désactivé par l’utilisateur", unconfigured: "Firebase non configuré", none: "Sans push" };
const CAT_FR: Record<string, string> = { booking: "Réservations", message: "Messages", payment: "Paiements", live: "Suivi", review: "Avis", account: "Compte", business: "Entreprise", announcement: "Annonces", system: "Informations" };
const TONE: Record<string, "success" | "danger" | "warning" | "gray"> = { sent: "success", failed: "danger", queued: "warning", no_device: "gray", disabled: "gray", unconfigured: "warning" };

export default function NotificationsAdminPage() {
  const [hours, setHours] = useState("24");
  const [s, setS] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [pushStatus, setPushStatus] = useState("");
  const [category, setCategory] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const list = useBoList<Row>("/notifications/", { q: useDebounced(q), push_status: pushStatus, category, from, to });

  useEffect(() => {
    setError("");
    bo.get<Summary>(`/notifications/summary/?hours=${hours}`).then(setS).catch((e) => setError(boError(e, "La synthèse n’a pas pu être chargée.")));
  }, [hours]);

  const columns: Column<Row>[] = [
    { key: "title", header: "Notification", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.title || r.type}</span> },
    { key: "user", header: "Destinataire", hideOnMobile: true, cell: (r) => `${r.user} (#${r.user_id})` },
    { key: "cat", header: "Catégorie", hideOnMobile: true, cell: (r) => CAT_FR[r.category] ?? r.category },
    { key: "push", header: "Push", cell: (r) => (r.push_status ? <Badge tone={TONE[r.push_status] ?? "gray"}>{PUSH_FR[r.push_status] ?? r.push_status}</Badge> : <span className="text-ash">—</span>) },
    { key: "read", header: "Lue", cell: (r) => (r.is_read ? "Oui" : "Non") },
    { key: "date", header: "Créée le", cell: (r) => dt(r.created_at) },
  ];
  const integ = s?.integrations;
  return (
    <>
      <PageHeader title="Notifications" description="État réel des envois. Aucun jeton d’appareil, corps de message ni code SMS n’est affiché ici : seulement des comptes et des statuts." />
      <FilterBar><FilterSelect label="Fenêtre d’observation" value={hours} onChange={setHours} options={[["24", "24 heures"], ["72", "3 jours"], ["168", "7 jours"], ["720", "30 jours"]]} /></FilterBar>
      {error ? <Alert tone="danger" className="mb-4">{error}</Alert> : null}
      {!s && !error ? <SkeletonStats count={4} className="mb-6 sm:grid-cols-2 lg:grid-cols-4" /> : null}
      {s ? (
        <>
          {s.push.queued_stuck ? <Alert tone="warning" className="mb-4" title="Envois bloqués">{s.push.queued_stuck} notification(s) sont « en file » depuis plus de 15 minutes : vérifiez que le worker Celery consomme la file.</Alert> : null}
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Notifications créées" value={s.notifications} hint={`sur ${s.window_hours} h`} />
            <Stat label="Push envoyés" value={s.push.sent} hint={`${s.push.failed} en échec`} tone="accent" />
            <Stat label="Appareils enregistrés" value={s.devices.total} hint={`${s.devices.active_7d} actifs sur 7 jours`} tone="night" />
            <Stat label="Codes SMS demandés" value={s.otp.requested} hint={`${s.otp.used} utilisés`} />
          </div>
          <div className="mb-6 grid gap-6 lg:grid-cols-2">
            <Section title="Intégrations">
              {integ ? <ul className="space-y-2 text-sm">
                <li className="flex items-center justify-between"><span>Notifications push (Firebase)</span><Badge tone={integ.push_fcm.configured ? "success" : "warning"}>{integ.push_fcm.configured ? "Configuré" : "Non configuré"}</Badge></li>
                <li className="flex items-center justify-between"><span>SMS{integ.sms.provider ? ` (${integ.sms.provider})` : ""}</span><Badge tone={integ.sms.ready ? "success" : "warning"}>{integ.sms.ready ? "Prêt" : "Non prêt"}</Badge></li>
                <li className="flex items-center justify-between"><span>E-mail ({integ.email.backend})</span><Badge tone={integ.email.real_delivery ? "success" : "warning"}>{integ.email.real_delivery ? "Envoi réel" : "Console / test"}</Badge></li>
              </ul> : null}
              <p className="mt-3 text-xs text-ash">Sans Firebase configuré, les notifications restent consultables dans l’application mais aucun push n’est émis.</p>
            </Section>
            <Section title="Répartition">
              <p className="mb-2 flex flex-wrap gap-2 text-xs">{Object.entries(s.push.by_status).map(([k, v]) => <span key={k} className="rounded-full bg-canvas px-3 py-1">{PUSH_FR[k] ?? k} : <strong>{v}</strong></span>)}</p>
              <p className="flex flex-wrap gap-2 text-xs">{Object.entries(s.by_category).map(([k, v]) => <span key={k} className="rounded-full bg-canvas px-3 py-1">{CAT_FR[k] ?? k} : <strong>{v}</strong></span>)}</p>
              <p className="mt-3 text-xs text-ash">Appareils : {Object.entries(s.devices.by_platform).map(([k, v]) => `${k} ${v}`).join(" · ") || "aucun"}.</p>
            </Section>
          </div>
        </>
      ) : null}
      <FilterBar>
        <SearchBox value={q} onChange={setQ} placeholder="Titre ou type…" />
        <FilterSelect label="Push" value={pushStatus} onChange={setPushStatus} options={[["", "Tous"], ...Object.entries(PUSH_FR).filter(([k]) => k !== "none")]} />
        <FilterSelect label="Catégorie" value={category} onChange={setCategory} options={[["", "Toutes"], ...Object.entries(CAT_FR)]} />
        <DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
        <Button variant="outline" onClick={() => void list.reload()}>Actualiser</Button>
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} caption="Historique des notifications" empty="Aucune notification ne correspond." />
    </>
  );
}
