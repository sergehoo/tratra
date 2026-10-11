"use client";
import { useState } from "react";
import { Eye, Hammer, LifeBuoy, ShieldCheck, UserCheck, UserX, Users } from "lucide-react";
import { Badge, PageHeader } from "@/components/ds";
import { bo } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useDashboardKpis } from "@/lib/boDashboard";
import { useCounts, useManagedList } from "@/lib/useBoList";
import {
  DateRange, ExportButton, FilterBar, FilterSelect, Kpi, KpiGrid, ListView, ReasonModal, SearchBox, StatusChips, dd, postTo, useNotice,
  type BoColumn, type BulkAction, type RowAction,
} from "../_components/ui";

interface Row {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
  city: string | null;
  is_active: boolean;
  is_verified: boolean;
  date_joined: string;
  last_login: string | null;
  is_artisan: boolean;
  artisan_approved: boolean;
  profile_id: number | null;
  bookings: number;
}

export default function UsersPage() {
  const { can } = useBo();
  const m = useManagedList<Row, { type: string; active: string; verified: string; city: string; from: string; to: string }>("/users/", { type: "", active: "", verified: "", city: "", from: "", to: "" });
  const { values: f, list } = m;
  const kpis = useDashboardKpis(can("dashboard.view"))?.users;
  const counts = useCounts("/users/", { _all: "", true: "active=true", false: "active=false" }, list.count);
  const [target, setTarget] = useState<{ row: Row; op: "suspend" | "reactivate" } | null>(null);
  const [notice, setNotice] = useNotice();
  const canManage = can("users.manage");

  const columns: BoColumn<Row>[] = [
    { key: "name", header: "Compte", primary: true, sort: "name", cell: (r) => <span className="font-semibold text-ink">{r.name} <span className="font-normal text-ash">#{r.id}</span></span> },
    { key: "contact", header: "Contact", wrap: true, cell: (r) => <span className="text-inkSoft">{[r.phone, r.email].filter(Boolean).join(" · ") || "—"}</span> },
    { key: "city", header: "Ville", from: "3xl", hideOnMobile: true, cell: (r) => r.city ?? "—" },
    {
      key: "roles", header: "Profil", cell: (r) => (
        <span className="flex flex-wrap gap-1.5">
          {r.is_artisan ? <Badge tone={r.artisan_approved ? "success" : "warning"}>{r.artisan_approved ? "Artisan approuvé" : "Artisan en attente"}</Badge> : <Badge tone="gray">Client</Badge>}
          {!r.is_verified ? <Badge tone="warning">Téléphone non vérifié</Badge> : null}
        </span>
      ),
    },
    { key: "bookings", header: "Réservations", align: "right", sort: "bookings", cell: (r) => r.bookings },
    { key: "last", header: "Dernière connexion", from: "3xl", hideOnMobile: true, sort: "last_login", cell: (r) => dd(r.last_login) },
    { key: "joined", header: "Inscrit le", from: "2xl", hideOnMobile: true, sort: "date_joined", cell: (r) => dd(r.date_joined) },
    { key: "status", header: "Statut", cell: (r) => <Badge tone={r.is_active ? "success" : "danger"}>{r.is_active ? "Actif" : "Suspendu"}</Badge> },
  ];

  const rowActions = (r: Row): RowAction[] => [
    { label: "Ouvrir la fiche", icon: Eye, href: `/backoffice/users/${r.id}` },
    { label: "Dossier KYC", icon: ShieldCheck, href: `/backoffice/kyc/${r.profile_id}`, hidden: !(can("kyc.review") && r.profile_id) },
    { label: "Dossier support", icon: LifeBuoy, href: `/backoffice/support?user=${r.id}`, hidden: !can("support.manage") },
    { label: "Suspendre le compte", icon: UserX, tone: "danger", onClick: () => setTarget({ row: r, op: "suspend" }), hidden: !canManage || !r.is_active },
    { label: "Réactiver le compte", icon: UserCheck, onClick: () => setTarget({ row: r, op: "reactivate" }), hidden: !canManage || r.is_active },
  ];

  const bulk: BulkAction<Row>[] | undefined = canManage
    ? [
        {
          id: "suspend", label: "Suspendre", icon: UserX, tone: "danger", title: "Suspendre les comptes sélectionnés ?", confirmLabel: "Suspendre",
          description: "Chaque compte ne pourra plus se connecter ; ses sessions sont révoquées. Les réservations en cours ne sont PAS annulées.",
          eligible: (r) => r.is_active, run: (r, b) => bo.post(`/users/${r.id}/suspend/`, b),
        },
        { id: "reactivate", label: "Réactiver", icon: UserCheck, title: "Réactiver les comptes sélectionnés ?", confirmLabel: "Réactiver", eligible: (r) => !r.is_active, run: (r, b) => bo.post(`/users/${r.id}/reactivate/`, b) },
      ]
    : undefined;

  return (
    <>
      <PageHeader
        title="Utilisateurs"
        description="Comptes clients, artisans et entreprises. Les coordonnées sont masquées en liste ; la fiche les affiche aux rôles autorisés et le Super Admin les voit complètes ici."
        actions={<ExportButton dataset="users" from={f.from} to={f.to} />}
      />
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}

      {kpis ? (
        <KpiGrid className="mb-5">
          <Kpi icon={<Users className="h-5 w-5" />} label="Comptes" value={kpis.total} hint={`${kpis.new_7d} nouveaux sur 7 jours · ${kpis.new_30d} sur 30 jours`} />
          <Kpi icon={<Hammer className="h-5 w-5" />} tone="accent" label="Artisans approuvés" value={`${kpis.artisans_approved} / ${kpis.artisans}`} hint="Profils approuvés par l’équipe KYC" />
          <Kpi tone="night" icon={<UserX className="h-5 w-5" />} label="Suspendus" value={counts.false ?? "—"} hint="Connexion impossible" />
          <Kpi label="Résultats de cette vue" value={list.loading && !list.rows.length ? "…" : list.count} hint={m.activeCount ? `${m.activeCount} filtre(s) actif(s)` : "Aucun filtre"} />
        </KpiGrid>
      ) : null}

      <StatusChips items={[["", "Tous"], ["true", "Actifs"], ["false", "Suspendus"]]} value={f.active} onChange={(v) => m.set({ active: v })} counts={counts} />

      <FilterBar
        search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Nom, téléphone, e-mail, identifiant…" />}
        activeCount={m.activeCount}
        onReset={m.reset}
        onRefresh={() => void list.reload()}
        refreshing={list.loading}
      >
        <FilterSelect label="Type" value={f.type} onChange={(v) => m.set({ type: v })} options={[["", "Tous"], ["client", "Clients"], ["artisan", "Artisans"], ["company", "Entreprises"]]} />
        <FilterSelect label="Téléphone" value={f.verified} onChange={(v) => m.set({ verified: v })} options={[["", "Tous"], ["true", "Vérifié"], ["false", "Non vérifié"]]} />
        <div className="min-w-[10rem]">
          <label htmlFor="users-city" className="mb-1 block text-xs font-semibold text-ash">Ville</label>
          <input id="users-city" value={f.city} onChange={(e) => m.set({ city: e.target.value })} placeholder="Abidjan…" className="block min-h-[44px] w-full rounded-control border border-line bg-white px-3 text-sm text-ink placeholder:text-fog focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>

      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowHref={(r) => `/backoffice/users/${r.id}`}
        rowLabel={(r) => `${r.name} #${r.id}`}
        caption="Utilisateurs"
        empty="Aucun compte ne correspond à ces filtres."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        ordering={f.ordering}
        onOrdering={(v) => m.set({ ordering: v })}
        rowActions={rowActions}
        bulk={bulk}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />

      <ReasonModal
        open={target?.op === "suspend"}
        title={`Suspendre ${target?.row.name ?? "ce compte"} ?`}
        description="Le compte ne pourra plus se connecter, ses sessions sont révoquées. Ses réservations en cours NE sont PAS annulées : vous devrez les traiter."
        confirmLabel="Suspendre"
        tone="danger"
        onClose={() => setTarget(null)}
        request={target ? postTo(`/users/${target.row.id}/suspend/`) : async () => undefined}
        onDone={() => { setTarget(null); setNotice("Compte suspendu. Pensez à traiter ses réservations en cours."); void list.reload(); }}
      />
      <ReasonModal
        open={target?.op === "reactivate"}
        title={`Réactiver ${target?.row.name ?? "ce compte"} ?`}
        confirmLabel="Réactiver"
        onClose={() => setTarget(null)}
        request={target ? postTo(`/users/${target.row.id}/reactivate/`) : async () => undefined}
        onDone={() => { setTarget(null); setNotice("Compte réactivé. L’utilisateur doit se reconnecter."); void list.reload(); }}
      />
    </>
  );
}
