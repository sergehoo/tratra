"use client";
import { useEffect, useState } from "react";
import { Bell, Smartphone, Send, MessageSquareText, UserRound } from "lucide-react";
import { Alert, Badge, PageHeader, SkeletonStats } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useManagedList } from "@/lib/useBoList";
import { DateRange, FilterBar, FilterSelect, Kpi, KpiGrid, ListView, SearchBox, Section, dd, type BoColumn, type RowAction } from "../_components/ui";

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
  const { can } = useBo();
  const [hours, setHours] = useState("24");
  const [s, setS] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const m = useManagedList<Row, { push_status: string; category: string; user: string; from: string; to: string }>("/notifications/", { push_status: "", category: "", user: "", from: "", to: "" });
  const { values: f, list } = m;

  useEffect(() => {
    setError("");
    bo.get<Summary>(`/notifications/summary/?hours=${hours}`).then(setS).catch((e) => setError(boError(e, "La synthèse n’a pas pu être chargée.")));
  }, [hours]);

  const columns: BoColumn<Row>[] = [
    { key: "title", header: "Notification", primary: true, wrap: true, cell: (r) => <span className="font-semibold text-ink">{r.title || r.type}</span> },
    { key: "user", header: "Destinataire", hideOnMobile: true, from: "lg", cell: (r) => `${r.user} (#${r.user_id})` },
    { key: "cat", header: "Catégorie", hideOnMobile: true, from: "xl", cell: (r) => CAT_FR[r.category] ?? r.category },
    { key: "push", header: "Push", cell: (r) => (r.push_status ? <Badge tone={TONE[r.push_status] ?? "gray"}>{PUSH_FR[r.push_status] ?? r.push_status}</Badge> : <span className="text-ash">—</span>) },
    { key: "read", header: "Lue", hideOnMobile: true, cell: (r) => (r.is_read ? "Oui" : "Non") },
    { key: "date", header: "Créée le", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: Row): RowAction[] => [
    { label: "Fiche du destinataire", icon: UserRound, href: `/backoffice/users/${r.user_id}`, hidden: !can("users.view") },
    { label: "Ses autres notifications", icon: Bell, href: `/backoffice/notifications?user=${r.user_id}` },
  ];
  const integ = s?.integrations;
  return (
    <>
      <PageHeader title="Notifications" description="État réel des envois. Aucun jeton d’appareil, corps de message ni code SMS n’est affiché ici : seulement des comptes et des statuts." />
      <FilterBar activeCount={0}>
        <FilterSelect label="Fenêtre d’observation" value={hours} onChange={setHours} options={[["24", "24 heures"], ["72", "3 jours"], ["168", "7 jours"], ["720", "30 jours"]]} />
      </FilterBar>
      {error ? <Alert tone="danger" className="mb-4">{error}</Alert> : null}
      {!s && !error ? <SkeletonStats count={4} className="mb-6 sm:grid-cols-2 lg:grid-cols-4" /> : null}
      {s ? (
        <>
          {s.push.queued_stuck ? <Alert tone="warning" className="mb-4" title="Envois bloqués">{s.push.queued_stuck} notification(s) sont « en file » depuis plus de 15 minutes : vérifiez que le worker Celery consomme la file.</Alert> : null}
          <KpiGrid className="mb-6">
            <Kpi icon={<Bell className="h-5 w-5" />} label="Notifications créées" value={s.notifications} hint={`sur ${s.window_hours} h`} />
            <Kpi icon={<Send className="h-5 w-5" />} tone="accent" label="Push envoyés" value={s.push.sent} hint={`${s.push.failed} en échec`} />
            <Kpi icon={<Smartphone className="h-5 w-5" />} tone="night" label="Appareils enregistrés" value={s.devices.total} hint={`${s.devices.active_7d} actifs sur 7 jours`} />
            <Kpi icon={<MessageSquareText className="h-5 w-5" />} label="Codes SMS demandés" value={s.otp.requested} hint={`${s.otp.used} utilisés`} />
          </KpiGrid>
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
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Titre ou type…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Push" value={f.push_status} onChange={(v) => m.set({ push_status: v })} options={[["", "Tous"], ...Object.entries(PUSH_FR).filter(([k]) => k !== "none")]} />
        <FilterSelect label="Catégorie" value={f.category} onChange={(v) => m.set({ category: v })} options={[["", "Toutes"], ...Object.entries(CAT_FR)]} />
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
        {f.user ? <button type="button" className="min-h-[40px] rounded-full bg-primarySoft px-3.5 text-sm font-semibold text-primaryDark" onClick={() => m.set({ user: "" })}>Compte #{f.user} ✕</button> : null}
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => r.title || r.type} caption="Historique des notifications" empty="Aucune notification ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
    </>
  );
}
