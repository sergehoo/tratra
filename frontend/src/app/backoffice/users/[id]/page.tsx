"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Alert, Badge, Button, PageHeader, SkeletonPage } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { KV, ReasonModal, Section, STATUS_FR, Tag, dt, postTo } from "../../_components/ui";

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

const KIND_FR: Record<string, string> = { client: "Client", artisan: "Artisan", company: "Entreprise" };

export default function UserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useBo();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<"suspend" | "reactivate" | null>(null);
  const [notice, setNotice] = useState("");

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
  return (
    <>
      <PageHeader
        title={d.name}
        eyebrow={`Compte #${d.id}`}
        back={{ href: "/backoffice/users", label: "Utilisateurs" }}
        description={d.kinds.map((k) => KIND_FR[k] ?? k).join(" · ")}
        actions={
          can("users.manage") ? (
            d.is_active ? <Button variant="danger" size="sm" onClick={() => setModal("suspend")}>Suspendre le compte</Button> : <Button size="sm" onClick={() => setModal("reactivate")}>Réactiver le compte</Button>
          ) : null
        }
      />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      {!d.is_active ? <Alert tone="danger" className="mb-4" title="Compte suspendu">Connexion impossible, sessions révoquées, plus aucune notification push.</Alert> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Identité">
          <KV items={[
            ["Téléphone", d.phone_full ? <>{d.phone_full} {d.is_verified ? <Badge tone="success">Vérifié</Badge> : <Badge tone="warning">Non vérifié</Badge>}</> : "—"],
            ["E-mail", d.email_full], ["Ville", d.city], ["Pays", d.country], ["Inscrit le", dt(d.date_joined)], ["Dernière connexion", dt(d.last_login)],
            ["Conditions acceptées", dt(d.terms_accepted_at)], ["Identifiant", d.username],
          ]} />
        </Section>

        <Section title="Activité" actions={can("support.manage") ? <Link href={`/backoffice/support?user=${d.id}`} className="text-sm font-semibold text-primaryDark underline underline-offset-2">Dossier support</Link> : undefined}>
          <KV items={[
            ["Réservations (client)", sum(d.bookings.as_client)], ["Missions (artisan)", sum(d.bookings.as_artisan)], ["En cours", d.bookings.active],
            ["Litiges", d.disputes], ["Signalements émis", d.reports], ["Notifications non lues", d.notifications_unread],
          ]} />
          {Object.keys(d.bookings.as_client).length ? (
            <p className="mt-3 flex flex-wrap gap-1.5">{Object.entries(d.bookings.as_client).map(([s, n]) => <span key={s} className="rounded-full bg-canvas px-2.5 py-0.5 text-xs text-inkSoft">{STATUS_FR[s] ?? s} : {n}</span>)}</p>
          ) : null}
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
          {d.devices.length ? (
            <ul className="mb-4 space-y-1 text-sm">{d.devices.map((x, i) => <li key={i}>{x.platform} · actif le {dt(x.last_active)}</li>)}</ul>
          ) : <p className="mb-4 text-sm text-inkSoft">Aucun appareil enregistré pour les notifications.</p>}
          <KV items={[["Communications promotionnelles", d.marketing_consent ? (d.marketing_consent.granted ? `Acceptées le ${dt(d.marketing_consent.granted_at)} (${d.marketing_consent.source || "—"})` : `Refusées / retirées le ${dt(d.marketing_consent.revoked_at)}`) : "Aucun choix enregistré"]]} />
        </Section>

        <Section title="Historique des décisions" className="lg:col-span-2">
          {d.history.length ? (
            <ul className="divide-y divide-lineSoft text-sm">
              {d.history.map((h, i) => <li key={i} className="py-2"><strong>{h.action.replace("backoffice.", "")}</strong> — {h.by} · {dt(h.at)}{h.reason ? <span className="block text-inkSoft">Motif : {h.reason}</span> : null}</li>)}
            </ul>
          ) : <p className="text-sm text-inkSoft">Aucune décision d’administration sur ce compte.</p>}
        </Section>
      </div>

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
    </>
  );
}
