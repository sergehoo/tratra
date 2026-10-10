"use client";
import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Alert, Badge, Button, Checkbox, ConfirmDialog, Input, Modal, PageHeader, Tabs, type Column } from "@/components/ds";
import { bo, boError, fieldErrors } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { DateRange, FilterBar, FilterSelect, ListView, ReasonModal, SearchBox, Section, dt, postTo, useNotice, useTabParam } from "../_components/ui";

interface Staff { id: number; name: string; email: string | null; is_active: boolean; is_superuser: boolean; roles: string[]; last_login: string | null; date_joined: string }
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
  const list = useBoList<Staff>("/security/staff/", {});
  const [edit, setEdit] = useState<Staff | null>(null);
  const [sel, setSel] = useState<string[]>([]);
  const [add, setAdd] = useState(false);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState<UserHit | null>(null);
  const [hits, setHits] = useState<UserHit[]>([]);
  const [remove, setRemove] = useState<Staff | null>(null);
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
    try { await bo.put(`/security/staff/${edit.id}/roles/`, { roles: sel }); setEdit(null); setNotice("Rôles mis à jour : l’effet est immédiat."); list.reload(); }
    catch (e) { setFieldErr(fieldErrors(e)); setError(boError(e, "Les rôles n’ont pas pu être modifiés.")); } finally { setBusy(false); }
  }
  async function addStaff() {
    if (!pick) return;
    setBusy(true); setError(""); setFieldErr({});
    try { await bo.post("/security/staff/", { user_id: pick.id, roles: sel }); setAdd(false); setNotice("Accès d’administration accordé."); list.reload(); }
    catch (e) { setFieldErr(fieldErrors(e)); setError(boError(e, "L’accès n’a pas pu être accordé.")); } finally { setBusy(false); }
  }

  const columns: Column<Staff>[] = [
    { key: "name", header: "Administrateur", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.name} <span className="font-normal text-ash">#{r.id}{r.id === me?.user.id ? " (vous)" : ""}</span></span> },
    { key: "email", header: "E-mail", hideOnMobile: true, cell: (r) => r.email ?? "—" },
    { key: "roles", header: "Rôles", cell: (r) => <span className="flex flex-wrap gap-1.5">{r.roles.map((x) => <Badge key={x} tone={x === "super_admin" ? "accent" : "primary"}>{ROLE_FR[x] ?? x}</Badge>)}{!r.roles.length ? <Badge tone="warning">Aucun rôle</Badge> : null}{r.is_superuser ? <Badge tone="night">Superutilisateur</Badge> : null}</span> },
    { key: "login", header: "Dernière connexion", hideOnMobile: true, cell: (r) => dt(r.last_login) },
    { key: "state", header: "Statut", cell: (r) => <Badge tone={r.is_active ? "success" : "danger"}>{r.is_active ? "Actif" : "Suspendu"}</Badge> },
    { key: "act", header: "", align: "right", cell: (r) => (r.id !== me?.user.id ? <span className="flex justify-end gap-2"><Button size="sm" variant="outline" onClick={() => { setSel(r.roles); setError(""); setFieldErr({}); setEdit(r); }}>Rôles</Button><Button size="sm" variant="danger" onClick={() => setRemove(r)}>Retirer</Button></span> : null) },
  ];

  return (
    <>
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      <Section title="Personnel d’administration" actions={<Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => { setSel([]); setPick(null); setQ(""); setError(""); setFieldErr({}); setAdd(true); }}>Ajouter un administrateur</Button>}>
        <p className="mb-3 text-xs text-ash">Vous ne pouvez pas modifier vos propres rôles ni retirer votre propre accès : il reste ainsi toujours un super administrateur. Aucune double authentification n’est encore disponible : limitez les comptes au strict nécessaire.</p>
        <ListView list={list} columns={columns} rowKey={(r) => r.id} caption="Personnel d’administration" empty="Aucun compte d’administration." />
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
        request={postTo(`/security/staff/${remove?.id}/remove/`)} onDone={() => { setRemove(null); setNotice("Accès retiré."); list.reload(); }} />
    </>
  );
}

function SessionsTab() {
  const [staffOnly, setStaffOnly] = useState("true");
  const [active, setActive] = useState("true");
  const [user, setUser] = useState("");
  const list = useBoList<SessionRow>("/security/sessions/", { staff: staffOnly === "true" ? "true" : "", active: active === "true" ? "true" : "", user: user.replace(/\D/g, "") });
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
      setConfirm(null); setNotice("Session(s) révoquée(s) : l’appareil devra se reconnecter."); list.reload();
    } catch (e) { setConfirm(null); setFailure(boError(e, "La révocation a échoué.")); } finally { setBusy(false); }
  }
  const columns: Column<SessionRow>[] = [
    { key: "user", header: "Compte", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.user} <span className="font-normal text-ash">#{r.user_id}</span> {r.is_staff ? <Badge tone="accent">Administration</Badge> : null}</span> },
    { key: "fp", header: "Session", hideOnMobile: true, cell: (r) => <span className="font-mono text-xs text-inkSoft">{r.fingerprint}</span> },
    { key: "created", header: "Ouverte le", cell: (r) => dt(r.created_at) },
    { key: "exp", header: "Expire le", hideOnMobile: true, cell: (r) => dt(r.expires_at) },
    { key: "state", header: "État", cell: (r) => <Badge tone={r.revoked ? "danger" : r.expired ? "gray" : "success"}>{r.revoked ? "Révoquée" : r.expired ? "Expirée" : "Active"}</Badge> },
    { key: "act", header: "", align: "right", cell: (r) => (!r.revoked && !r.expired ? <span className="flex justify-end gap-2"><Button size="sm" variant="outline" onClick={() => setConfirm({ type: "one", row: r })}>Révoquer</Button><Button size="sm" variant="danger" onClick={() => setConfirm({ type: "all", userId: r.user_id, name: r.user })}>Tout révoquer</Button></span> : null) },
  ];
  return (
    <>
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      <FilterBar>
        <FilterSelect label="Comptes" value={staffOnly} onChange={setStaffOnly} options={[["true", "Administration"], ["", "Tous les comptes"]]} />
        <FilterSelect label="État" value={active} onChange={setActive} options={[["true", "Actives"], ["", "Toutes"]]} />
        <div className="min-w-[10rem]"><label className="mb-1 block text-xs font-semibold text-ash" htmlFor="sess-user">N° de compte</label><Input id="sess-user" inputMode="numeric" value={user} onChange={(e) => setUser(e.target.value)} placeholder="ex. 42" /></div>
      </FilterBar>
      <p className="mb-3 text-xs text-ash">Aucun jeton n’est affiché : seulement une empreinte courte pour distinguer les sessions.</p>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} caption="Sessions" empty="Aucune session ne correspond." />
      <ConfirmDialog open={Boolean(confirm)} onClose={() => setConfirm(null)} onConfirm={() => void run()} loading={busy} tone="danger" confirmLabel="Révoquer"
        title={confirm?.type === "all" ? `Déconnecter ${confirm.name} partout ?` : "Révoquer cette session ?"}
        description={confirm?.type === "all" ? "Toutes les sessions de ce compte sont révoquées : il devra se reconnecter sur chaque appareil." : "L’appareil concerné ne pourra plus renouveler sa connexion."} />
    </>
  );
}

function AuditTab() {
  const [q, setQ] = useState("");
  const [actions, setActions] = useState<string[]>([]);
  const [action, setAction] = useState("");
  const [backoffice, setBackoffice] = useState("true");
  const [actor, setActor] = useState("");
  const [targetType, setTargetType] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [open, setOpen] = useState<AuditRow | null>(null);
  const prefix = useDebounced(q.trim());
  const list = useBoList<AuditRow>("/security/audit/", { action: action || prefix, backoffice, actor: actor.replace(/\D/g, ""), target_type: targetType, from, to }, 50);
  useEffect(() => { bo.get<{ actions: string[] }>("/security/audit/actions/").then((r) => setActions(r.actions)).catch(() => setActions([])); }, []);
  const columns: Column<AuditRow>[] = [
    { key: "at", header: "Date", primary: true, cell: (r) => <span className="font-semibold text-ink">{dt(r.at)}</span> },
    { key: "actor", header: "Auteur", cell: (r) => r.actor },
    { key: "action", header: "Action", cell: (r) => <span className="font-mono text-xs">{r.action}</span> },
    { key: "target", header: "Cible", hideOnMobile: true, cell: (r) => `${r.target_type}${r.target_id ? ` #${r.target_id}` : ""}` },
    { key: "data", header: "", align: "right", cell: (r) => (Object.keys(r.data).length ? <Button size="sm" variant="outline" onClick={() => setOpen(r)}>Détail</Button> : null) },
  ];
  return (
    <>
      <FilterBar>
        <SearchBox value={q} onChange={setQ} label="Préfixe d’action" placeholder="Préfixe d’action (ex. backoffice.kyc)" />
        <FilterSelect label="Action exacte" value={action} onChange={setAction} options={[["", "Toutes"], ...actions.map((a): [string, string] => [a, a])]} />
        <FilterSelect label="Périmètre" value={backoffice} onChange={setBackoffice} options={[["true", "Back-Office"], ["", "Toute la plateforme"]]} />
        <div className="min-w-[9rem]"><label className="mb-1 block text-xs font-semibold text-ash" htmlFor="aud-actor">N° d’auteur</label><Input id="aud-actor" inputMode="numeric" value={actor} onChange={(e) => setActor(e.target.value)} /></div>
        <div className="min-w-[9rem]"><label className="mb-1 block text-xs font-semibold text-ash" htmlFor="aud-type">Type de cible</label><Input id="aud-type" value={targetType} onChange={(e) => setTargetType(e.target.value)} placeholder="ex. booking" /></div>
        <DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} caption="Journal d’audit" empty="Aucun événement ne correspond." />
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
