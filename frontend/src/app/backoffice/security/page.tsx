"use client";
import { useEffect, useState } from "react";
import { KeyRound, LogOut, Plus, ScrollText, ShieldCheck, ShieldOff, UserCog, UserMinus, Users } from "lucide-react";
import { Alert, Badge, Button, Checkbox, ConfirmDialog, Input, Modal, PageHeader, Tabs } from "@/components/ds";
import { bo, boError, fieldErrors } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useCounts, useDebounced, useManagedList } from "@/lib/useBoList";
import { DateRange, ExportButton, FilterBar, FilterSelect, Kpi, KpiGrid, ListView, ReasonModal, SearchBox, Section, StatusChips, dd, dt, postTo, useNotice, useTabParam, type BoColumn, type RowAction } from "../_components/ui";

interface Staff { id: number; name: string; email: string | null; is_active: boolean; is_superuser: boolean; roles: string[]; last_login: string | null; date_joined: string; mfa_enrolled: boolean }
interface RoleInfo { id: string; members: number; permissions: string[] }
interface Roles { roles: RoleInfo[]; permissions: Record<string, string> }
interface SessionRow { id: number; user_id: number; user: string; is_staff: boolean; created_at: string; expires_at: string; fingerprint: string; revoked: boolean; expired: boolean }
interface AuditRow { id: number; at: string; actor_id: number | null; actor: string; action: string; target_type: string; target_id: number | null; data: Record<string, unknown> }
interface UserHit { id: number; name: string; phone: string | null }

const ROLE_FR: Record<string, string> = { super_admin: "Super administrateur", ops: "Opérations", support: "Support", finance: "Finance", marketing: "Marketing", analyst: "Analyste" };

function RolePicker({ roles, selected, onChange }: { roles: RoleInfo[]; selected: string[]; onChange: (r: string[]) => void }) {
  return (
    <fieldset><legend className="mb-1.5 text-sm font-semibold text-ink">Rôles</legend>
      <div className="space-y-2">
        {roles.map((r) => (
          <Checkbox key={r.id} label={`${ROLE_FR[r.id] ?? r.id} — ${r.permissions.length} droit(s)`} checked={selected.includes(r.id)} onChange={(e) => onChange(e.target.checked ? [...selected, r.id] : selected.filter((x) => x !== r.id))} />
        ))}
      </div>
    </fieldset>
  );
}

function StaffTab({ roles }: { roles: Roles | null }) {
  const { me } = useBo();
  const [notice, setNotice] = useNotice();
  const m = useManagedList<Staff, { role: string; active: string; mfa: string }>("/security/staff/", { role: "", active: "", mfa: "" });
  const { values: f, list } = m;
  const counts = useCounts("/security/staff/", { _all: "", enrolled: "mfa=enrolled", missing: "mfa=missing" }, list.version);
  const [edit, setEdit] = useState<Staff | null>(null);
  const [sel, setSel] = useState<string[]>([]);
  const [add, setAdd] = useState(false);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState<UserHit | null>(null);
  const [hits, setHits] = useState<UserHit[]>([]);
  const [remove, setRemove] = useState<Staff | null>(null);
  const [resetMfa, setResetMfa] = useState<Staff | null>(null);
  const [error, setError] = useState("");
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const dq = useDebounced(q);

  useEffect(() => {
    if (!add || dq.trim().length < 2) { setHits([]); return; }
    bo.get<{ results: UserHit[] }>(`/users/?q=${encodeURIComponent(dq)}&page_size=6`).then((r) => setHits(r.results)).catch(() => setHits([]));
  }, [add, dq]);

  async function saveRoles() {
    if (!edit) return;
    setBusy(true); setError(""); setFieldErr({});
    try { await bo.put(`/security/staff/${edit.id}/roles/`, { roles: sel }); setEdit(null); setNotice("Rôles mis à jour : l’effet est immédiat."); void list.reload(); }
    catch (e) { setFieldErr(fieldErrors(e)); setError(boError(e, "Les rôles n’ont pas pu être modifiés.")); } finally { setBusy(false); }
  }
  async function addStaff() {
    if (!pick) return;
    setBusy(true); setError(""); setFieldErr({});
    try { await bo.post("/security/staff/", { user_id: pick.id, roles: sel }); setAdd(false); setNotice("Accès d’administration accordé."); void list.reload(); }
    catch (e) { setFieldErr(fieldErrors(e)); setError(boError(e, "L’accès n’a pas pu être accordé.")); } finally { setBusy(false); }
  }

  const columns: BoColumn<Staff>[] = [
    { key: "name", header: "Administrateur", primary: true, sort: "name", cell: (r) => <span className="font-semibold text-ink">{r.name} <span className="font-normal text-ash">#{r.id}{r.id === me?.user.id ? " (vous)" : ""}</span></span> },
    { key: "email", header: "E-mail", hideOnMobile: true, from: "xl", cell: (r) => r.email ?? "—" },
    { key: "roles", header: "Rôles", cell: (r) => <span className="flex flex-wrap gap-1.5">{r.roles.map((x) => <Badge key={x} tone={x === "super_admin" ? "accent" : "primary"}>{ROLE_FR[x] ?? x}</Badge>)}{!r.roles.length ? <Badge tone="warning">Aucun rôle</Badge> : null}{r.is_superuser ? <Badge tone="night">Superutilisateur</Badge> : null}</span> },
    { key: "login", header: "Dernière connexion", hideOnMobile: true, from: "2xl", cell: (r) => dd(r.last_login) },
    { key: "state", header: "Statut", cell: (r) => <Badge tone={r.is_active ? "success" : "danger"}>{r.is_active ? "Actif" : "Suspendu"}</Badge> },
    { key: "mfa", header: "MFA", hideOnMobile: true, cell: (r) => (r.mfa_enrolled ? <Badge tone="success">Activée</Badge> : <Badge tone="warning">Non activée</Badge>) },
  ];
  const rowActions = (r: Staff): RowAction[] => [
    { label: "Journal d’audit de cet administrateur", icon: ScrollText, href: `/backoffice/security?tab=audit&actor=${r.id}` },
    { label: "Modifier les rôles", icon: UserCog, onClick: () => { setSel(r.roles); setError(""); setFieldErr({}); setEdit(r); }, hidden: r.id === me?.user.id },
    { label: "Révoquer toutes ses sessions", icon: LogOut, href: `/backoffice/security?tab=sessions&user=${r.id}`, hidden: r.id === me?.user.id },
    { label: "Réinitialiser la double authentification", icon: KeyRound, tone: "danger", onClick: () => setResetMfa(r), hidden: r.id === me?.user.id || !r.mfa_enrolled },
    { label: "Retirer l’accès d’administration", icon: UserMinus, tone: "danger", onClick: () => setRemove(r), hidden: r.id === me?.user.id },
  ];

  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <KpiGrid className="mb-5">
        <Kpi icon={<Users className="h-5 w-5" />} label="Comptes d’administration" value={counts._all ?? "—"} hint="Chaque accès est nominatif" />
        <Kpi icon={<ShieldCheck className="h-5 w-5" />} tone="accent" label="Double authentification activée" value={counts.enrolled ?? "—"} hint="Exigée de chaque compte" />
        <Kpi icon={<ShieldOff className="h-5 w-5" />} tone={counts.missing ? "danger" : "night"} label="Sans double authentification" value={counts.missing ?? "—"} hint="À activer à leur prochaine connexion" />
      </KpiGrid>
      <Section title="Personnel d’administration" actions={<Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => { setSel([]); setPick(null); setQ(""); setError(""); setFieldErr({}); setAdd(true); }}>Ajouter un administrateur</Button>}>
        <p className="mb-3 text-xs text-ash">Vous ne pouvez pas modifier vos propres rôles ni retirer votre propre accès : il reste ainsi toujours un super administrateur. La double authentification est exigée de chaque compte d’administration ; un appareil perdu se réinitialise par un autre super administrateur, après vérification de l’identité. Limitez les comptes au strict nécessaire.</p>
        <StatusChips items={[["", "Tous"], ["enrolled", "MFA activée"], ["missing", "Sans MFA"]]} value={f.mfa} onChange={(v) => m.set({ mfa: v })} counts={counts} label="Double authentification" />
        <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Nom ou e-mail…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
          <FilterSelect label="Rôle" value={f.role} onChange={(v) => m.set({ role: v })} options={[["", "Tous"], ...Object.entries(ROLE_FR)]} />
          <FilterSelect label="Statut" value={f.active} onChange={(v) => m.set({ active: v })} options={[["", "Tous"], ["true", "Actifs"], ["false", "Suspendus"]]} />
        </FilterBar>
        <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => r.name} caption="Personnel d’administration" empty="Aucun compte d’administration ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
          rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      </Section>
      {roles ? (
        <Section title="Rôles et droits" className="mt-6">
          <ul className="grid gap-4 md:grid-cols-2">
            {roles.roles.map((r) => (
              <li key={r.id} className="rounded-panel border border-lineSoft p-4">
                <p className="mb-2 flex items-center justify-between"><strong className="text-ink">{ROLE_FR[r.id] ?? r.id}</strong><span className="text-xs text-ash">{r.members} membre(s)</span></p>
                <p className="flex flex-wrap gap-1.5 text-[11px]">{r.permissions.map((p) => <span key={p} title={roles.permissions[p]} className="rounded-full bg-canvas px-2 py-0.5 text-inkSoft">{p}</span>)}</p>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Modal open={Boolean(edit)} onClose={() => setEdit(null)} dismissible={!busy} title={`Rôles de ${edit?.name ?? ""}`} description="L’effet est immédiat. Un rôle ne donne jamais plus que ses droits listés."
        footer={<><Button variant="outline" onClick={() => setEdit(null)} disabled={busy}>Annuler</Button><Button loading={busy} disabled={!sel.length} onClick={() => void saveRoles()}>Enregistrer</Button></>}>
        <div className="space-y-4">{roles ? <RolePicker roles={roles.roles} selected={sel} onChange={setSel} /> : null}{fieldErr.roles ? <p role="alert" className="text-xs text-dangerInk">{fieldErr.roles}</p> : null}{error && !fieldErr.roles ? <Alert tone="danger">{error}</Alert> : null}</div>
      </Modal>
      <Modal open={add} onClose={() => setAdd(false)} dismissible={!busy} title="Ajouter un administrateur" description="Le compte doit exister, être actif et avoir son téléphone vérifié."
        footer={<><Button variant="outline" onClick={() => setAdd(false)} disabled={busy}>Annuler</Button><Button loading={busy} disabled={!pick || !sel.length} onClick={() => void addStaff()}>Accorder l’accès</Button></>}>
        <div className="space-y-4">
          <SearchBox value={q} onChange={(v) => { setQ(v); setPick(null); }} label="Compte" placeholder="Nom, téléphone ou e-mail…" />
          {pick ? <p className="text-sm font-semibold text-ink">Compte choisi : {pick.name} (#{pick.id})</p> : hits.length ? (
            <ul className="divide-y divide-lineSoft rounded-panel border border-lineSoft">{hits.map((h) => <li key={h.id}><button type="button" onClick={() => setPick(h)} className="flex min-h-[44px] w-full justify-between px-3 py-2 text-left text-sm hover:bg-canvas"><span className="font-semibold">{h.name}</span><span className="text-ash">#{h.id} {h.phone ?? ""}</span></button></li>)}</ul>
          ) : null}
          {fieldErr.user_id ? <p role="alert" className="text-xs text-dangerInk">{fieldErr.user_id}</p> : null}
          {roles ? <RolePicker roles={roles.roles} selected={sel} onChange={setSel} /> : null}
          {error && !fieldErr.user_id && !fieldErr.roles ? <Alert tone="danger">{error}</Alert> : null}
        </div>
      </Modal>
      <ReasonModal open={Boolean(remove)} title={`Retirer l’accès de ${remove?.name ?? ""} ?`} description="Le compte utilisateur est conservé ; il perd son accès d’administration et toutes ses sessions sont révoquées." confirmLabel="Retirer l’accès" tone="danger" onClose={() => setRemove(null)}
        request={postTo(`/security/staff/${remove?.id}/remove/`)} onDone={() => { setRemove(null); setNotice("Accès retiré."); void list.reload(); }} />
      <ReasonModal open={Boolean(resetMfa)} title={`Réinitialiser la double authentification de ${resetMfa?.name ?? ""} ?`} description="À faire après vérification de l’identité (appareil perdu). L’appareil est supprimé, toutes ses sessions sont révoquées : il devra activer un nouvel appareil à sa prochaine connexion." confirmLabel="Réinitialiser" tone="danger"
        onClose={() => setResetMfa(null)} request={postTo(`/security/staff/${resetMfa?.id}/mfa-reset/`)} onDone={() => { setResetMfa(null); setNotice("Double authentification réinitialisée."); void list.reload(); }} />
    </>
  );
}

function SessionsTab() {
  const m = useManagedList<SessionRow, { staff: string; active: string; user: string }>("/security/sessions/", { staff: "true", active: "true", user: "" });
  const { values: f, list } = m;
  const [notice, setNotice] = useNotice();
  const [failure, setFailure] = useState("");
  const [confirm, setConfirm] = useState<{ type: "one"; row: SessionRow } | { type: "all"; userId: number; name: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!confirm) return;
    setBusy(true); setFailure("");
    try {
      if (confirm.type === "one") await bo.post(`/security/sessions/${confirm.row.id}/revoke/`, {});
      else await bo.post(`/security/users/${confirm.userId}/revoke-sessions/`, {});
      setConfirm(null); setNotice("Session(s) révoquée(s) : l’appareil devra se reconnecter."); void list.reload();
    } catch (e) { setConfirm(null); setFailure(boError(e, "La révocation a échoué.")); } finally { setBusy(false); }
  }
  const columns: BoColumn<SessionRow>[] = [
    { key: "user", header: "Compte", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.user} <span className="font-normal text-ash">#{r.user_id}</span> {r.is_staff ? <Badge tone="accent">Administration</Badge> : null}</span> },
    { key: "fp", header: "Session", hideOnMobile: true, from: "xl", cell: (r) => <span className="font-mono text-xs text-inkSoft">{r.fingerprint}</span> },
    { key: "created", header: "Ouverte le", cell: (r) => dt(r.created_at) },
    { key: "exp", header: "Expire le", hideOnMobile: true, from: "2xl", cell: (r) => dt(r.expires_at) },
    { key: "state", header: "État", cell: (r) => <Badge tone={r.revoked ? "danger" : r.expired ? "gray" : "success"}>{r.revoked ? "Révoquée" : r.expired ? "Expirée" : "Active"}</Badge> },
  ];
  const rowActions = (r: SessionRow): RowAction[] => [
    { label: "Révoquer cette session", icon: LogOut, onClick: () => setConfirm({ type: "one", row: r }), hidden: r.revoked || r.expired },
    { label: "Déconnecter ce compte partout", icon: LogOut, tone: "danger", onClick: () => setConfirm({ type: "all", userId: r.user_id, name: r.user }), hidden: r.revoked || r.expired },
  ];
  return (
    <>
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      <StatusChips items={[["true", "Actives"], ["", "Toutes"]]} value={f.active} onChange={(v) => m.set({ active: v })} label="État de la session" />
      <FilterBar activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Comptes" value={f.staff} onChange={(v) => m.set({ staff: v })} options={[["true", "Administration"], ["", "Tous les comptes"]]} />
        <div className="min-w-[10rem]"><label className="mb-1 block text-xs font-semibold text-ash" htmlFor="sess-user">N° de compte</label><Input id="sess-user" inputMode="numeric" value={f.user} onChange={(e) => m.set({ user: e.target.value.replace(/\D/g, "") })} placeholder="ex. 42" /></div>
      </FilterBar>
      <p className="mb-3 text-xs text-ash">Aucun jeton n’est affiché : seulement une empreinte courte pour distinguer les sessions.</p>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `session de ${r.user}`} caption="Sessions" empty="Aucune session ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <ConfirmDialog open={Boolean(confirm)} onClose={() => setConfirm(null)} onConfirm={() => void run()} loading={busy} tone="danger" confirmLabel="Révoquer"
        title={confirm?.type === "all" ? `Déconnecter ${confirm.name} partout ?` : "Révoquer cette session ?"}
        description={confirm?.type === "all" ? "Toutes les sessions de ce compte sont révoquées : il devra se reconnecter sur chaque appareil." : "L’appareil concerné ne pourra plus renouveler sa connexion."} />
    </>
  );
}

function AuditTab() {
  const m = useManagedList<AuditRow, { action: string; backoffice: string; actor: string; target_type: string; target_id: string; from: string; to: string }>("/security/audit/", { action: "", backoffice: "true", actor: "", target_type: "", target_id: "", from: "", to: "" });
  const { values: f, list } = m;
  const [actions, setActions] = useState<string[]>([]);
  const [open, setOpen] = useState<AuditRow | null>(null);
  useEffect(() => { bo.get<{ actions: string[] }>("/security/audit/actions/").then((r) => setActions(r.actions)).catch(() => setActions([])); }, []);
  const columns: BoColumn<AuditRow>[] = [
    { key: "at", header: "Date", primary: true, cell: (r) => <span className="font-semibold text-ink">{dt(r.at)}</span> },
    { key: "actor", header: "Auteur", cell: (r) => r.actor },
    { key: "action", header: "Action", wrap: true, cell: (r) => <span className="font-mono text-xs">{r.action}</span> },
    { key: "target", header: "Cible", hideOnMobile: true, cell: (r) => `${r.target_type}${r.target_id ? ` #${r.target_id}` : ""}` },
  ];
  const rowActions = (r: AuditRow): RowAction[] => [
    { label: "Voir le détail", icon: ScrollText, onClick: () => setOpen(r), hidden: !Object.keys(r.data).length },
    { label: "Toutes les actions de cet auteur", icon: UserCog, onClick: () => m.set({ actor: String(r.actor_id ?? "") }), hidden: !r.actor_id },
    { label: "Tout l’historique de cette cible", icon: ScrollText, onClick: () => m.set({ target_type: r.target_type, target_id: String(r.target_id ?? "") }), hidden: !r.target_id },
  ];
  return (
    <>
      <FilterBar
        search={<SearchBox value={f.action} onChange={(v) => m.set({ action: v })} label="Préfixe d’action" placeholder="Préfixe d’action (ex. backoffice.kyc)" />}
        activeCount={m.activeCount}
        onReset={m.reset}
        onRefresh={() => void list.reload()}
        refreshing={list.loading}
        actions={<ExportButton dataset="audit" from={f.from} to={f.to} />}
      >
        <FilterSelect label="Action exacte" value={actions.includes(f.action) ? f.action : ""} onChange={(v) => m.set({ action: v })} options={[["", "Choisir…"], ...actions.map((a): [string, string] => [a, a])]} />
        <FilterSelect label="Périmètre" value={f.backoffice} onChange={(v) => m.set({ backoffice: v })} options={[["true", "Back-Office"], ["", "Toute la plateforme"]]} />
        <div className="min-w-[9rem]"><label className="mb-1 block text-xs font-semibold text-ash" htmlFor="aud-actor">N° d’auteur</label><Input id="aud-actor" inputMode="numeric" value={f.actor} onChange={(e) => m.set({ actor: e.target.value.replace(/\D/g, "") })} /></div>
        <div className="min-w-[9rem]"><label className="mb-1 block text-xs font-semibold text-ash" htmlFor="aud-type">Type de cible</label><Input id="aud-type" value={f.target_type} onChange={(e) => m.set({ target_type: e.target.value })} placeholder="ex. booking" /></div>
        <div className="min-w-[8rem]"><label className="mb-1 block text-xs font-semibold text-ash" htmlFor="aud-tid">N° de cible</label><Input id="aud-tid" inputMode="numeric" value={f.target_id} onChange={(e) => m.set({ target_id: e.target.value.replace(/\D/g, "") })} /></div>
        <DateRange from={f.from} to={f.to} onFrom={(v) => m.set({ from: v })} onTo={(v) => m.set({ to: v })} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowLabel={(r) => `événement #${r.id}`} caption="Journal d’audit" empty="Aucun événement ne correspond." emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions} pageSize={m.pageSize} onPageSize={(n) => m.set({ size: String(n) })} />
      <Modal open={Boolean(open)} onClose={() => setOpen(null)} title={open?.action ?? ""} description={open ? `${open.actor} · ${dt(open.at)}` : ""}>
        <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-panel bg-canvas p-3 text-xs text-ink">{open ? JSON.stringify(open.data, null, 2) : ""}</pre>
        <p className="mt-2 text-xs text-ash">Le journal ne contient jamais de secret : motifs, montants, identifiants et anciennes / nouvelles valeurs seulement.</p>
      </Modal>
    </>
  );
}

export default function SecurityPage() {
  const [tab, setTab] = useTabParam(["staff", "sessions", "audit"] as const, "staff");
  const [roles, setRoles] = useState<Roles | null>(null);
  useEffect(() => { bo.get<Roles>("/security/roles/").then(setRoles).catch(() => setRoles(null)); }, []);
  return (
    <>
      <PageHeader title="Sécurité et audit" description="Rôles du personnel, sessions et journal des opérations sensibles." />
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "staff", label: "Personnel et rôles" }, { id: "sessions", label: "Sessions" }, { id: "audit", label: "Journal d’audit" }]} />
      {tab === "staff" ? <StaffTab roles={roles} /> : null}
      {tab === "sessions" ? <SessionsTab /> : null}
      {tab === "audit" ? <AuditTab /> : null}
    </>
  );
}
