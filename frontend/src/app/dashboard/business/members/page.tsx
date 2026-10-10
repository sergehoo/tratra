"use client";
import { useState, type FormEvent } from "react";
import { Copy, KeyRound, UserPlus } from "lucide-react";
import { Alert, Badge, Button, Card, CardHeader, ConfirmDialog, DataTable, EmptyState, Modal, PageHeader, SelectField, TextField, type Column } from "@/components/ds";
import { apiErrorMessage, del, patch, post } from "@/lib/api";
import { ROLES, shortDate, useBusiness, useOrgData, type Site } from "@/lib/business";

interface Member { id: number; user_id: number; display_name: string; role: string; role_label: string; sites: number[]; is_active: boolean; created_at: string }
interface Invitation { id: number; role: string; label: string; expires_at: string; status: string }

export default function MembersPage() {
  const { path } = useBusiness();
  const members = useOrgData<Member[]>("members/", "Les membres ne peuvent pas être chargés.");
  const invitations = useOrgData<Invitation[]>("invitations/");
  const sites = useOrgData<Site[]>("sites/");
  const [invite, setInvite] = useState(false);
  const [code, setCode] = useState<{ code: string; role: string; expires_at: string } | null>(null);
  const [form, setForm] = useState({ role: "requester", label: "", site: "" });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [removing, setRemoving] = useState<Member | null>(null);
  const [copied, setCopied] = useState(false);

  async function createInvite(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFailure("");
    try {
      const res = await post<{ code: string; role: string; expires_at: string }>(path("invitations/"), { role: form.role, label: form.label.trim(), sites: form.site ? [Number(form.site)] : [] });
      setCode(res);
      setInvite(false);
      setForm({ role: "requester", label: "", site: "" });
      void invitations.reload();
    } catch (err) {
      setFailure(apiErrorMessage(err, "L’invitation n’a pas pu être créée."));
    } finally {
      setBusy(false);
    }
  }
  async function changeRole(m: Member, role: string) {
    setFailure("");
    try {
      await patch(path(`members/${m.id}/`), { role });
      await members.reload();
    } catch (err) {
      setFailure(apiErrorMessage(err, "Le rôle n’a pas pu être modifié."));
    }
  }
  async function remove(m: Member) {
    try {
      await del(path(`members/${m.id}/`));
      setRemoving(null);
      await members.reload();
    } catch (err) {
      setRemoving(null);
      setFailure(apiErrorMessage(err, "Le membre n’a pas pu être retiré."));
    }
  }
  async function revoke(i: Invitation) {
    try {
      await del(path(`invitations/${i.id}/`));
      await invitations.reload();
    } catch {
      setFailure("L’invitation n’a pas pu être révoquée.");
    }
  }
  const active = (members.data ?? []).filter((m) => m.is_active);
  const columns: Column<Member>[] = [
    { key: "n", header: "Membre", primary: true, cell: (m) => <span className="font-semibold text-ink">{m.display_name}</span> },
    { key: "r", header: "Rôle", cell: (m) => m.role === "owner" ? <Badge tone="primary">Propriétaire</Badge> : (
      <label className="block"><span className="sr-only">Rôle de {m.display_name}</span>
        <select className="rounded-control border border-line bg-white px-2 py-1.5 text-sm" value={m.role} onChange={(e) => changeRole(m, e.target.value)}>{ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select></label>) },
    { key: "s", header: "Périmètre", hideOnMobile: true, cell: (m) => m.sites.length ? m.sites.map((id) => (sites.data ?? []).find((s) => s.id === id)?.name ?? `#${id}`).join(", ") : "Tous les sites" },
    { key: "d", header: "Depuis", hideOnMobile: true, cell: (m) => shortDate(m.created_at) },
    { key: "x", header: "", align: "right", cell: (m) => m.role === "owner" ? null : <Button size="sm" variant="ghost" onClick={() => setRemoving(m)}>Retirer</Button> },
  ];
  return (
    <>
      <PageHeader eyebrow="Tratra Business" title="Membres et rôles" description="Chaque rôle ouvre des capacités précises, contrôlées par le serveur. Un membre peut être limité à certains sites." actions={<Button leftIcon={<UserPlus aria-hidden className="h-4 w-4" />} onClick={() => setInvite(true)}>Inviter</Button>} />
      {failure ? <Alert tone="danger" className="mb-4" onDismiss={() => setFailure("")}>{failure}</Alert> : null}
      <DataTable caption="Membres" columns={columns} rows={active} rowKey={(m) => m.id} loading={members.loading} empty={<EmptyState title="Aucun membre" />} />
      <Card as="section" aria-label="Invitations" className="mt-6">
        <CardHeader icon={<KeyRound className="h-5 w-5" />} title="Invitations" description="Le code n’est affiché qu’une fois, à la création. L’invité le saisit après connexion." />
        {invitations.data?.length ? (
          <ul className="divide-y divide-lineSoft">{invitations.data.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
              <span><strong>{i.label || "Invitation"}</strong> · {ROLES.find((r) => r.value === i.role)?.label ?? i.role}</span>
              <span className="flex items-center gap-2"><Badge tone={i.status === "pending" ? "info" : i.status === "accepted" ? "success" : "gray"}>{({ pending: "En attente", accepted: "Acceptée", revoked: "Révoquée", expired: "Expirée" } as Record<string, string>)[i.status] ?? i.status}</Badge>
                {i.status === "pending" ? <Button size="sm" variant="ghost" onClick={() => revoke(i)}>Révoquer</Button> : null}</span>
            </li>))}</ul>
        ) : <p className="text-sm text-ash">Aucune invitation.</p>}
      </Card>

      <Modal open={invite} onClose={() => setInvite(false)} title="Inviter un collaborateur" size="md">
        <form onSubmit={createInvite} className="space-y-4" noValidate>
          <TextField label="Nom ou repère (facultatif)" optional value={form.label} onChange={(e) => setForm((s) => ({ ...s, label: e.target.value }))} />
          <SelectField label="Rôle" value={form.role} onChange={(e) => setForm((s) => ({ ...s, role: e.target.value }))} hint={ROLES.find((r) => r.value === form.role)?.help}>{ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</SelectField>
          <SelectField label="Limiter à un site" optional value={form.site} onChange={(e) => setForm((s) => ({ ...s, site: e.target.value }))}><option value="">Tous les sites</option>{(sites.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</SelectField>
          <Button type="submit" block loading={busy}>Créer le code d’invitation</Button>
        </form>
      </Modal>
      <Modal open={Boolean(code)} onClose={() => setCode(null)} title="Code d’invitation" description="Transmettez-le à la personne : il est valable 7 jours et ne s’affichera plus." size="sm"
        footer={<Button onClick={() => setCode(null)}>J’ai noté le code</Button>}>
        <div className="space-y-3 text-center">
          <p className="rounded-panel bg-canvas p-4 font-mono text-2xl font-bold tracking-wider text-ink">{code?.code}</p>
          <Button variant="outline" leftIcon={<Copy aria-hidden className="h-4 w-4" />} onClick={async () => { try { await navigator.clipboard.writeText(code?.code ?? ""); setCopied(true); } catch { setCopied(false); } }}>{copied ? "Copié" : "Copier"}</Button>
        </div>
      </Modal>
      <ConfirmDialog open={Boolean(removing)} onClose={() => setRemoving(null)} tone="danger" title={`Retirer ${removing?.display_name ?? ""} ?`} description="Il perd l’accès à l’organisation ; l’historique de ses demandes est conservé." confirmLabel="Retirer" onConfirm={() => removing && remove(removing)} />
    </>
  );
}
