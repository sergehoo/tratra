"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { FileText, Gavel, LifeBuoy, LogOut, ShieldCheck, UserCheck, UserX } from "lucide-react";
import { Alert, Badge, Button, ConfirmDialog, PageHeader, SkeletonPage, TextareaField } from "@/components/ds";
import { bo, boError, fieldErrors, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList } from "@/lib/useBoList";
import { DocumentViewer, type Doc } from "../../_components/DocumentViewer";
import { Fiche, Pane, Restricted } from "../../_components/fiche";
import { useCrumb } from "../../_components/crumbs";
import { KV, ListView, ReasonModal, Section, STATUS_FR, Tag, dd, dt, postTo, useNotice, type BoColumn } from "../../_components/ui";

interface Detail {
  id: number;
  name: string;
  username: string;
  phone_full: string | null;
  email_full: string | null;
  city: string | null;
  country: string | null;
  is_active: boolean;
  is_verified: boolean;
  date_joined: string;
  last_login: string | null;
  terms_accepted_at: string | null;
  kinds: string[];
  profile: { id: number; commune: string | null; approved: boolean; online: boolean; trust_score: number | null; trust_badges: string[]; completed_jobs: number; rating: number } | null;
  bookings: { as_client: Record<string, number>; as_artisan: Record<string, number>; active: number };
  disputes: number;
  reports: number;
  devices: { platform: string; last_active: string | null }[];
  marketing_consent: { granted: boolean; granted_at: string | null; revoked_at: string | null; source: string } | null;
  notifications_unread: number;
  history: { action: string; at: string; by: string; reason: string }[];
}
interface BookingRow { id: number; status: string; service: string | null; client: string; artisan: string; booking_date: string; payment_status: string | null; disputes: number }
interface PaymentRow { id: number; booking_id: number; status: string; method: string; amount: string; created_at: string }
interface ContractRow { id: number; title: string; status: string; amount: string; period: string; start_date: string; principal: { name: string }; worker: { name: string } }
interface DisputeRow { id: number; booking_id: number; status: string; reason: string; created_at: string }
interface AuditRow { id: number; at: string; actor: string; action: string; target_type: string; target_id: number | null; data: Record<string, unknown> }
interface Support { notes: { id: number; body: string; author: string; created_at: string }[] }
interface KycDetail { profile_id: number; state_label: string; documents: Doc[] }

const KIND_FR: Record<string, string> = { client: "Client", artisan: "Artisan", company: "Entreprise" };
const METHOD_FR: Record<string, string> = { card: "Carte", transfer: "Virement", cash: "Espèces", check: "Chèque", om: "Orange Money", mtn: "MTN MoMo", moov: "Moov Money", wave: "Wave" };
const CONTRACT_FR: Record<string, string> = { draft: "Brouillon", pending_acceptance: "À accepter", accepted: "Accepté", active: "En cours", suspended: "Suspendu", notice: "Préavis", terminated: "Résilié", completed: "Terminé", cancelled: "Annulé" };
const DOC_TONE = { pending: "warning", approved: "success", rejected: "danger" } as const;
const DOC_FR = { pending: "À examiner", approved: "Approuvée", rejected: "Refusée" } as const;

function Summary({ count, label, href }: { count: number; label: string; href?: string }) {
  return (
    <p className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm text-inkSoft">
      <span><strong className="text-ink">{count}</strong> {label}</span>
      {href ? <Link href={href} className="font-semibold text-primaryDark underline underline-offset-2">Voir tout dans le module</Link> : null}
    </p>
  );
}

function BookingsPane({ id }: { id: number }) {
  const list = useBoList<BookingRow>("/bookings/", { user: id }, 10);
  const columns: BoColumn<BookingRow>[] = [
    { key: "id", header: "Réservation", primary: true, cell: (r) => <span className="font-semibold text-ink">#{r.id}</span> },
    { key: "s", header: "Statut", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "svc", header: "Service", wrap: true, cell: (r) => r.service ?? "—" },
    { key: "who", header: "Client → artisan", hideOnMobile: true, from: "xl", cell: (r) => `${r.client} → ${r.artisan}` },
    { key: "d", header: "Prévue le", cell: (r) => dd(r.booking_date) },
    { key: "disp", header: "Litiges", align: "right", hideOnMobile: true, cell: (r) => (r.disputes ? <Badge tone="danger">{r.disputes}</Badge> : "—") },
  ];
  return (
    <>
      <Summary count={list.count} label="réservation(s) ou mission(s) (client ou artisan)" href={`/backoffice/bookings?user=${id}`} />
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowHref={(r) => `/backoffice/bookings/${r.id}`} rowLabel={(r) => `réservation #${r.id}`} caption="Réservations du compte" empty="Aucune réservation ni mission." />
    </>
  );
}

function DisputesPane({ id }: { id: number }) {
  const list = useBoList<DisputeRow>("/disputes/", { user: id, status: "" }, 10);
  const columns: BoColumn<DisputeRow>[] = [
    { key: "id", header: "Litige", primary: true, cell: (r) => <span className="font-semibold text-ink">#{r.id} · réservation #{r.booking_id}</span> },
    { key: "s", header: "Statut", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "r", header: "Motif", wrap: true, hideOnMobile: true, cell: (r) => <span className="text-inkSoft">{r.reason}</span> },
    { key: "d", header: "Ouvert le", hideOnMobile: true, cell: (r) => dd(r.created_at) },
  ];
  return (
    <>
      <Summary count={list.count} label="litige(s) impliquant ce compte" href={`/backoffice/bookings?tab=disputes&user=${id}&status=`} />
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowHref={(r) => `/backoffice/bookings?tab=disputes&id=${r.id}`} caption="Litiges du compte" empty="Aucun litige." />
    </>
  );
}

function PaymentsPane({ id }: { id: number }) {
  const list = useBoList<PaymentRow>("/finance/payments/", { user: id }, 10);
  const columns: BoColumn<PaymentRow>[] = [
    { key: "id", header: "Paiement", primary: true, cell: (r) => <span className="font-semibold text-ink">#{r.id} · réservation #{r.booking_id}</span> },
    { key: "s", header: "Statut", cell: (r) => <Tag value={r.status} label={STATUS_FR[r.status]} /> },
    { key: "m", header: "Moyen", hideOnMobile: true, cell: (r) => METHOD_FR[r.method] ?? r.method },
    { key: "a", header: "Montant", align: "right", cell: (r) => moneyLabel(r.amount) },
    { key: "d", header: "Le", hideOnMobile: true, cell: (r) => dd(r.created_at) },
  ];
  return (
    <>
      <Summary count={list.count} label="paiement(s) liés à ses réservations" href={`/backoffice/finance?tab=payments&user=${id}`} />
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `paiement #${r.id}`} caption="Paiements du compte" empty="Aucun paiement." />
    </>
  );
}

function ContractsPane({ id }: { id: number }) {
  const list = useBoList<ContractRow>("/engagements/contracts/", { user: id }, 10);
  const columns: BoColumn<ContractRow>[] = [
    { key: "t", header: "Contrat", primary: true, wrap: true, cell: (r) => <span className="font-semibold text-ink">#{r.id} {r.title}</span> },
    { key: "s", header: "État", cell: (r) => <Badge tone={r.status === "active" ? "success" : "gray"}>{CONTRACT_FR[r.status] ?? r.status}</Badge> },
    { key: "p", header: "Parties", hideOnMobile: true, cell: (r) => `${r.principal.name} → ${r.worker.name}` },
    { key: "a", header: "Rémunération", align: "right", cell: (r) => moneyLabel(r.amount) },
    { key: "d", header: "Début", hideOnMobile: true, cell: (r) => r.start_date },
  ];
  return (
    <>
      <Summary count={list.count} label="contrat(s) d’engagement" href={`/backoffice/engagements?tab=contracts&user=${id}`} />
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `contrat #${r.id}`} caption="Contrats du compte" empty="Aucun contrat d’engagement." />
    </>
  );
}

function DocumentsPane({ profileId, canReview }: { profileId: number | null; canReview: boolean }) {
  const [d, setD] = useState<KycDetail | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<Doc | null>(null);
  useEffect(() => {
    if (!profileId || !canReview) return;
    bo.get<KycDetail>(`/kyc/${profileId}/`).then(setD).catch((e) => setError(boError(e, "Les pièces n’ont pas pu être chargées.")));
  }, [profileId, canReview]);
  if (!profileId) return <p className="rounded-panel bg-canvas p-4 text-sm text-inkSoft">Ce compte n’a pas de profil professionnel : aucune pièce justificative n’est demandée aux clients.</p>;
  if (!canReview) return <Restricted right="kyc.review">Les pièces d’identité et justificatifs sont réservés à l’équipe de vérification (KYC).</Restricted>;
  if (error) return <Alert tone="danger">{error}</Alert>;
  if (!d) return <p className="text-sm text-inkSoft" role="status">Chargement…</p>;
  return (
    <Section title="Pièces du dossier KYC" actions={<Link href={`/backoffice/kyc/${profileId}`} className="text-sm font-semibold text-primaryDark underline underline-offset-2">Examiner le dossier</Link>}>
      <p className="mb-3 text-xs text-ash">Dossier : {d.state_label}. Chaque ouverture d’une pièce est journalisée ; elle est lue par un accès protégé, jamais par une adresse publique.</p>
      {d.documents.length ? (
        <ul className="divide-y divide-lineSoft">
          {d.documents.map((doc) => (
            <li key={doc.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-ink">{doc.type_label}{doc.title ? ` — ${doc.title}` : ""}</span>
                <span className="block text-xs text-ash">Déposée le {dt(doc.uploaded_at)}{doc.expires_on ? ` · expire le ${doc.expires_on}` : ""}{doc.rejection_reason ? ` · refus : ${doc.rejection_reason}` : ""}</span>
              </span>
              <span className="flex items-center gap-2">
                <Badge tone={DOC_TONE[doc.status]}>{DOC_FR[doc.status]}</Badge>
                {doc.file_path ? <Button size="sm" variant="outline" leftIcon={<FileText aria-hidden className="h-4 w-4" />} onClick={() => setView(doc)}>Ouvrir l’original</Button> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-inkSoft">Aucune pièce déposée.</p>}
      <DocumentViewer doc={view} onClose={() => setView(null)} />
    </Section>
  );
}

function NotesPane({ id }: { id: number }) {
  const [notes, setNotes] = useState<Support["notes"] | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    bo.get<Support>(`/support/users/${id}/`).then((r) => setNotes(r.notes)).catch((e) => setError(boError(e, "Les notes n’ont pas pu être chargées.")));
  }, [id]);
  useEffect(load, [load]);
  async function add() {
    setBusy(true);
    setErrors({});
    try {
      await bo.post(`/support/users/${id}/notes/`, { body: note });
      setNote("");
      load();
    } catch (e) {
      setErrors(fieldErrors(e));
      if (!Object.keys(fieldErrors(e)).length) setError(boError(e, "La note n’a pas pu être ajoutée."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Section title="Notes internes">
      <p className="mb-3 text-xs text-ash">Jamais visibles de l’utilisateur. Le journal d’audit garde l’auteur et la date, pas le contenu.</p>
      <TextareaField label="Nouvelle note" value={note} error={errors.body} onChange={(e) => setNote(e.target.value)} rows={3} />
      <Button className="mt-2" size="sm" loading={busy} disabled={note.trim().length < 3} onClick={() => void add()}>Ajouter la note</Button>
      {error ? <Alert tone="danger" className="mt-3">{error}</Alert> : null}
      {notes?.length ? <ul className="mt-4 divide-y divide-lineSoft text-sm">{notes.map((n) => <li key={n.id} className="py-2"><p className="whitespace-pre-line text-ink">{n.body}</p><p className="text-xs text-ash">{n.author} · {dt(n.created_at)}</p></li>)}</ul> : notes ? <p className="mt-4 text-sm text-inkSoft">Aucune note.</p> : null}
    </Section>
  );
}

function AuditPane({ id, history, canAudit }: { id: number; history: Detail["history"]; canAudit: boolean }) {
  const list = useBoList<AuditRow>("/security/audit/", canAudit ? { target_type: "user", target_id: id } : {}, 10);
  const columns: BoColumn<AuditRow>[] = [
    { key: "at", header: "Date", primary: true, cell: (r) => <span className="font-semibold text-ink">{dt(r.at)}</span> },
    { key: "actor", header: "Auteur", cell: (r) => r.actor },
    { key: "action", header: "Action", wrap: true, cell: (r) => <span className="font-mono text-xs">{r.action.replace("backoffice.", "")}</span> },
  ];
  return (
    <Section title="Journal d’audit de ce compte">
      {canAudit ? (
        <>
          <p className="mb-3 text-xs text-ash">Toutes les opérations d’administration sur ce compte, y compris les consultations de ses coordonnées.</p>
          <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `événement #${r.id}`} caption="Audit du compte" empty="Aucun événement." />
        </>
      ) : history.length ? (
        <>
          <p className="mb-3 text-xs text-ash">Décisions récentes (le journal complet est réservé au droit « sécurité et audit »).</p>
          <ul className="divide-y divide-lineSoft text-sm">{history.map((h, i) => <li key={i} className="py-2"><strong>{h.action.replace("backoffice.", "")}</strong> — {h.by} · {dt(h.at)}{h.reason ? <span className="block text-inkSoft">Motif : {h.reason}</span> : null}</li>)}</ul>
        </>
      ) : <p className="text-sm text-inkSoft">Aucune décision d’administration sur ce compte.</p>}
    </Section>
  );
}

export default function UserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useBo();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<"suspend" | "reactivate" | null>(null);
  const [revoke, setRevoke] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [notice, setNotice] = useNotice();
  const userId = Number(id);
  useCrumb(d?.name);

  const load = useCallback(async () => {
    setError("");
    try {
      setD(await bo.get<Detail>(`/users/${id}/`));
    } catch (e) {
      setError(boError(e, "Ce compte n’a pas pu être chargé."));
    }
  }, [id]);
  useEffect(() => void load(), [load]);

  if (error && !d) {
    return (
      <>
        <PageHeader title="Compte" back={{ href: "/backoffice/users", label: "Utilisateurs" }} />
        <Alert tone="danger" title="Compte indisponible" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>
      </>
    );
  }
  if (!d) return <SkeletonPage />;
  const sum = (m: Record<string, number>) => Object.values(m).reduce((a, b) => a + b, 0);
  const manage = can("users.manage");
  const profileId = d.profile?.id ?? null;

  const general = (
    <Pane>
      <Section title="Identité et contact">
        <p className="mb-3 text-xs text-ash">Coordonnées complètes : chaque consultation de cette fiche est journalisée.</p>
        <KV items={[
          ["Téléphone", d.phone_full ? <>{d.phone_full} {d.is_verified ? <Badge tone="success">Vérifié</Badge> : <Badge tone="warning">Non vérifié</Badge>}</> : "—"],
          ["E-mail", d.email_full], ["Ville", d.city], ["Pays", d.country], ["Inscrit le", dt(d.date_joined)], ["Dernière connexion", dt(d.last_login)],
          ["Conditions acceptées", dt(d.terms_accepted_at)], ["Identifiant", d.username],
        ]} />
      </Section>
      {d.profile ? (
        <Section title="Profil professionnel" actions={<span className="flex gap-3 text-sm font-semibold">
          {can("kyc.review") ? <Link href={`/backoffice/kyc/${d.profile.id}`} className="text-primaryDark underline underline-offset-2">Dossier KYC</Link> : null}
          {can("trust.manage") ? <Link href={`/backoffice/trust/${d.profile.id}`} className="text-primaryDark underline underline-offset-2">Confiance</Link> : null}
        </span>}>
          <KV items={[
            ["Dossier", <Tag key="a" value={String(d.profile.approved)} label={d.profile.approved ? "Approuvé" : "Non approuvé"} />],
            ["Commune", d.profile.commune], ["En ligne", d.profile.online ? "Oui" : "Non"], ["Missions terminées", d.profile.completed_jobs],
            ["Note moyenne", d.profile.rating ? `${d.profile.rating.toFixed(1)} / 5` : "—"],
            ["Score de confiance", d.profile.trust_score ?? "Pas encore évaluable"], ["Badges", d.profile.trust_badges.length ? d.profile.trust_badges.join(", ") : "Aucun"],
          ]} />
        </Section>
      ) : null}
      <Section title="Appareils et consentements">
        <p className="mb-3 text-xs text-ash">Plateforme et dernière activité seulement : aucun jeton d’appareil n’est affiché.</p>
        {d.devices.length ? <ul className="mb-4 space-y-1 text-sm">{d.devices.map((x, i) => <li key={i}>{x.platform} · actif le {dt(x.last_active)}</li>)}</ul> : <p className="mb-4 text-sm text-inkSoft">Aucun appareil enregistré pour les notifications.</p>}
        <KV items={[["Communications promotionnelles", d.marketing_consent ? (d.marketing_consent.granted ? `Acceptées le ${dt(d.marketing_consent.granted_at)} (${d.marketing_consent.source || "—"})` : `Refusées / retirées le ${dt(d.marketing_consent.revoked_at)}`) : "Aucun choix enregistré"], ["Notifications non lues", d.notifications_unread]]} />
      </Section>
    </Pane>
  );

  const activity = (
    <div className="space-y-5">
      <Section title="Aperçu">
        <KV items={[["Réservations (client)", sum(d.bookings.as_client)], ["Missions (artisan)", sum(d.bookings.as_artisan)], ["En cours", d.bookings.active], ["Litiges", d.disputes], ["Signalements émis", d.reports]]} />
        {Object.keys(d.bookings.as_client).length ? <p className="mt-3 flex flex-wrap gap-1.5">{Object.entries(d.bookings.as_client).map(([s, n]) => <span key={s} className="rounded-full bg-canvas px-2.5 py-0.5 text-xs text-inkSoft">{STATUS_FR[s] ?? s} : {n}</span>)}</p> : null}
      </Section>
      {can("bookings.view") ? (
        <>
          <Section title="Réservations et missions"><BookingsPane id={userId} /></Section>
          <Section title="Litiges"><DisputesPane id={userId} /></Section>
        </>
      ) : <Restricted right="bookings.view" />}
    </div>
  );

  const money = (
    <div className="space-y-5">
      {can("finance.view") ? <Section title="Paiements"><PaymentsPane id={userId} /></Section> : <Restricted right="finance.view">Les montants et paiements sont réservés aux rôles financiers.</Restricted>}
      {can("engagements.view") ? <Section title="Engagements (contrats de longue durée)"><ContractsPane id={userId} /></Section> : <Restricted right="engagements.view" />}
    </div>
  );

  const actions = (
    <Pane>
      <Section title="Décisions sur le compte">
        {manage ? (
          <div className="space-y-3">
            {d.is_active
              ? <><Button variant="danger" leftIcon={<UserX aria-hidden className="h-4 w-4" />} onClick={() => setModal("suspend")}>Suspendre le compte</Button><p className="text-xs text-ash">Connexion impossible, sessions révoquées, appareils retirés. Les réservations en cours ne sont PAS annulées.</p></>
              : <><Button leftIcon={<UserCheck aria-hidden className="h-4 w-4" />} onClick={() => setModal("reactivate")}>Réactiver le compte</Button><p className="text-xs text-ash">L’utilisateur doit se reconnecter.</p></>}
          </div>
        ) : <Restricted right="users.manage">Suspendre ou réactiver un compte.</Restricted>}
      </Section>
      <Section title="Sécurité">
        {can("security.manage") ? (
          <div className="space-y-2">
            <Button variant="outline" leftIcon={<LogOut aria-hidden className="h-4 w-4" />} onClick={() => setRevoke(true)}>Déconnecter partout (révoquer les sessions)</Button>
            <p className="text-xs text-ash">À utiliser en cas de compte compromis : l’utilisateur devra se reconnecter sur chaque appareil.</p>
          </div>
        ) : <Restricted right="security.manage">Révoquer les sessions de ce compte.</Restricted>}
      </Section>
      <Section title="Liens utiles">
        <ul className="space-y-2 text-sm font-semibold text-primaryDark">
          {can("support.manage") ? <li><Link className="inline-flex items-center gap-2 underline underline-offset-2" href={`/backoffice/support?user=${d.id}`}><LifeBuoy aria-hidden className="h-4 w-4" />Dossier support</Link></li> : null}
          {can("kyc.review") && profileId ? <li><Link className="inline-flex items-center gap-2 underline underline-offset-2" href={`/backoffice/kyc/${profileId}`}><ShieldCheck aria-hidden className="h-4 w-4" />Dossier KYC</Link></li> : null}
          {can("notifications.view") ? <li><Link className="inline-flex items-center gap-2 underline underline-offset-2" href={`/backoffice/notifications?user=${d.id}`}>Notifications reçues</Link></li> : null}
          {can("bookings.view") ? <li><Link className="inline-flex items-center gap-2 underline underline-offset-2" href={`/backoffice/bookings?tab=disputes&user=${d.id}&status=`}><Gavel aria-hidden className="h-4 w-4" />Litiges</Link></li> : null}
        </ul>
      </Section>
    </Pane>
  );

  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <Fiche
        name={d.name}
        eyebrow={`Compte #${d.id}`}
        subtitle={d.kinds.map((k) => KIND_FR[k] ?? k).join(" · ")}
        badges={<><Badge tone={d.is_active ? "success" : "danger"}>{d.is_active ? "Actif" : "Suspendu"}</Badge><Badge tone={d.is_verified ? "success" : "warning"}>{d.is_verified ? "Téléphone vérifié" : "Téléphone non vérifié"}</Badge>{d.profile ? <Badge tone={d.profile.approved ? "success" : "warning"}>{d.profile.approved ? "Artisan approuvé" : "Artisan en attente"}</Badge> : null}</>}
        facts={[["Inscrit le", dd(d.date_joined)], ["Dernière connexion", dd(d.last_login)], ["Ville", d.city], ["En cours", d.bookings.active]]}
        actions={manage ? (d.is_active ? <Button variant="danger" size="sm" onClick={() => setModal("suspend")}>Suspendre</Button> : <Button size="sm" onClick={() => setModal("reactivate")}>Réactiver</Button>) : null}
        alert={!d.is_active ? <Alert tone="danger" className="mb-4" title="Compte suspendu">Connexion impossible, sessions révoquées, plus aucune notification push.</Alert> : undefined}
        tabs={[
          { id: "general", label: "Informations générales", content: general },
          { id: "activity", label: "Activités et historique", content: activity },
          { id: "documents", label: "Documents et justificatifs", content: <DocumentsPane profileId={profileId} canReview={can("kyc.review")} /> },
          { id: "money", label: "Paiements et engagements", content: money },
          { id: "notes", label: "Notes internes et audit", content: <div className="space-y-5">{can("support.manage") ? <NotesPane id={userId} /> : <Restricted right="support.manage">Les notes internes sont réservées au support.</Restricted>}<AuditPane id={userId} history={d.history} canAudit={can("security.manage")} /></div> },
          { id: "actions", label: "Actions administratives", content: actions },
        ]}
      />

      <ReasonModal
        open={modal === "suspend"}
        title="Suspendre ce compte ?"
        description="Le compte ne pourra plus se connecter, ses sessions sont révoquées et ses appareils retirés. Ses réservations en cours NE sont PAS annulées : vous devrez les traiter."
        confirmLabel="Suspendre"
        tone="danger"
        onClose={() => setModal(null)}
        request={postTo(`/users/${d.id}/suspend/`)}
        onDone={() => { setModal(null); setNotice("Compte suspendu. Pensez à traiter ses réservations en cours."); void load(); }}
      >
        {d.bookings.active ? <Alert tone="warning">Ce compte a {d.bookings.active} réservation(s) ou mission(s) en cours.</Alert> : null}
      </ReasonModal>
      <ReasonModal
        open={modal === "reactivate"}
        title="Réactiver ce compte ?"
        confirmLabel="Réactiver"
        onClose={() => setModal(null)}
        request={postTo(`/users/${d.id}/reactivate/`)}
        onDone={() => { setModal(null); setNotice("Compte réactivé. L’utilisateur doit se reconnecter."); void load(); }}
      />
      <ConfirmDialog
        open={revoke}
        onClose={() => setRevoke(false)}
        loading={revoking}
        tone="danger"
        confirmLabel="Révoquer les sessions"
        title={`Déconnecter ${d.name} partout ?`}
        description="Toutes les sessions de ce compte sont révoquées : il devra se reconnecter sur chaque appareil. L’opération est journalisée."
        onConfirm={async () => {
          setRevoking(true);
          try { await bo.post(`/security/users/${d.id}/revoke-sessions/`, {}); setRevoke(false); setNotice("Sessions révoquées."); } catch (e) { setRevoke(false); setNotice(boError(e, "La révocation a échoué.")); } finally { setRevoking(false); }
        }}
      />
    </>
  );
}
