"use client";
import { useCallback, useEffect, useState } from "react";
import { Compass, Eye, Plus, Trash2 } from "lucide-react";
import { apiErrorMessage, apiJson, del, get, post } from "@/lib/api";
import { Alert, Avatar, Button, Card, EmptyState, PageHeader, SkeletonList, Tabs, cx } from "@/components/ds";
import { Ring } from "@/components/statuses/StatusBar";
import { StatusComposer } from "@/components/statuses/StatusComposer";
import { StatusViewer } from "@/components/statuses/StatusViewer";
import { useInboxEvents } from "@/lib/inbox";
import { timeLeft, type StatusFeed, type StatusGroup, type StatusLimits } from "@/lib/statuses";

interface DiscoverPage { results: StatusGroup[]; has_more: boolean; next_page: number | null }
interface Contact { user: number; name: string; excluded: boolean }
interface Settings { audience: "contacts" | "extended"; allow_replies: boolean; limits: StatusLimits }

function Discover() {
  const [groups, setGroups] = useState<StatusGroup[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [viewer, setViewer] = useState<number | null>(null);

  const load = useCallback(async (page = 1) => {
    try {
      const r = await get<DiscoverPage>(`/statuses/discover/?page=${page}`);
      setGroups((g) => (page === 1 ? r.results : [...(g ?? []), ...r.results]));
      setNext(r.next_page);
      setError("");
    } catch (e) {
      setError(apiErrorMessage(e, "Les statuts à découvrir n’ont pas pu être chargés."));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (error) return <Alert tone="danger" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>;
  if (!groups) return <SkeletonList count={3} />;
  if (!groups.length) return <EmptyState icon={<Compass />} title="Rien à découvrir pour le moment" description="Les statuts que des membres choisissent de partager avec tous apparaîtront ici." />;
  return (
    <>
      <ul className="grid grid-cols-3 gap-4 sm:grid-cols-5 lg:grid-cols-6">
        {groups.map((g, i) => (
          <li key={g.author.id}>
            <button type="button" onClick={() => setViewer(i)} aria-label={`Statuts de ${g.author.name}`} className="flex w-full flex-col items-center gap-1.5 rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
              <Ring unseen={!g.seen} size={72}><Avatar name={g.author.name} photo={g.author.avatar} size={58} /></Ring>
              <span className={cx("w-full truncate text-center text-xs", g.seen ? "text-ash" : "font-bold text-ink")}>{g.author.name}</span>
              <span className="text-[11px] text-ash">{g.statuses.length} statut{g.statuses.length > 1 ? "s" : ""}</span>
            </button>
          </li>
        ))}
      </ul>
      {next ? <div className="mt-5 text-center"><Button variant="outline" onClick={() => void load(next)}>Voir plus</Button></div> : null}
      {viewer !== null ? <StatusViewer groups={groups} startGroup={viewer} onClose={() => { setViewer(null); void load(); }} /> : null}
    </>
  );
}

function Mine({ onCompose, refresh }: { onCompose: () => void; refresh: number }) {
  const [feed, setFeed] = useState<StatusFeed | null>(null);
  const [error, setError] = useState("");
  const [viewer, setViewer] = useState(false);
  const load = useCallback(async () => {
    try { setFeed(await get<StatusFeed>("/statuses/feed/")); setError(""); } catch (e) { setError(apiErrorMessage(e, "Vos statuts n’ont pas pu être chargés.")); }
  }, []);
  useEffect(() => { void load(); }, [load, refresh]);
  useInboxEvents((e) => { if (e.type === "status_view") void load(); });

  async function remove(id: number) {
    if (!window.confirm("Supprimer ce statut ? Cette action est définitive.")) return;
    try { await del(`/statuses/${id}/`); await load(); } catch (e) { setError(apiErrorMessage(e, "Le statut n’a pas pu être supprimé.")); }
  }
  if (error && !feed) return <Alert tone="danger">{error}</Alert>;
  if (!feed) return <SkeletonList count={2} />;
  const { mine } = feed;
  return (
    <div className="space-y-4">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={onCompose}>Nouveau statut</Button>
      {!mine.count ? <EmptyState icon={<Eye />} title="Aucun statut actif" description={`Un statut reste visible ${feed.limits.ttl_hours} h puis disparaît automatiquement.`} /> : (
        <ul className="space-y-2">
          {mine.statuses.map((s) => (
            <li key={s.id}>
              <Card padding="sm" className="flex items-center gap-3">
                <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-primarySoft text-xs font-bold uppercase text-primaryDark">{s.kind === "text" ? "Aa" : s.kind === "photo" ? "Photo" : "Vidéo"}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ink">{s.text || (s.kind === "photo" ? "Photo" : "Vidéo")}</p>
                  <p className="text-xs text-ash">Expire dans {timeLeft(s.expires_at)} · {s.audience === "extended" ? "Tous les membres" : "Mes contacts"}</p>
                </div>
                <button type="button" onClick={() => setViewer(true)} className="flex min-h-11 items-center gap-1.5 rounded-full bg-lineSoft px-3 text-sm font-semibold text-ink hover:bg-line"><Eye aria-hidden className="h-4 w-4" />{s.views?.unique ?? 0}</button>
                <button type="button" aria-label="Supprimer ce statut" onClick={() => void remove(s.id)} className="grid h-11 w-11 place-items-center rounded-full text-ash hover:bg-dangerSoft hover:text-dangerInk"><Trash2 aria-hidden className="h-5 w-5" /></button>
              </Card>
            </li>
          ))}
        </ul>
      )}
      {viewer ? <StatusViewer groups={[{ author: mine.author, statuses: mine.statuses, unseen: 0, seen: true, latest_at: "" }]} onClose={() => { setViewer(false); void load(); }} /> : null}
    </div>
  );
}

function Privacy() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [contacts, setContacts] = useState<Contact[] | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  useEffect(() => {
    get<Settings>("/statuses/settings/").then(setSettings).catch((e) => setError(apiErrorMessage(e, "Vos réglages n’ont pas pu être chargés.")));
    get<{ results: Contact[] }>("/statuses/contacts/").then((r) => setContacts(r.results)).catch(() => setContacts([]));
  }, []);

  async function save(patch: Partial<Pick<Settings, "audience" | "allow_replies">>) {
    try {
      const r = await apiPut(patch);
      setSettings(r);
      setSaved("Réglage enregistré.");
    } catch (e) { setError(apiErrorMessage(e, "Le réglage n’a pas pu être enregistré.")); }
  }
  async function toggle(c: Contact) {
    try {
      if (c.excluded) await del(`/statuses/exclusions/${c.user}/`); else await post("/statuses/exclusions/", { user: c.user });
      setContacts((list) => (list ?? []).map((x) => (x.user === c.user ? { ...x, excluded: !x.excluded } : x)));
    } catch (e) { setError(apiErrorMessage(e, "La modification n’a pas pu être enregistrée.")); }
  }
  if (!settings) return error ? <Alert tone="danger">{error}</Alert> : <SkeletonList count={2} />;
  return (
    <div className="space-y-5">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {saved ? <Alert tone="success">{saved}</Alert> : null}
      <Card padding="md" className="space-y-3">
        <h2 className="font-display text-base font-bold text-ink">Visibilité par défaut</h2>
        {([["contacts", "Mes contacts Tratra", "Membres avec qui vous avez une réservation, un contrat ou une conversation."], ["extended", "Tous les membres", "Visible aussi dans « Découvrir les statuts »."]] as const).map(([v, label, hint]) => (
          <label key={v} className={cx("flex cursor-pointer items-start gap-3 rounded-xl border p-3", settings.audience === v ? "border-primary bg-primarySoft/40" : "border-line")}>
            <input type="radio" name="aud" className="mt-1" checked={settings.audience === v} onChange={() => void save({ audience: v })} />
            <span><span className="block text-sm font-semibold text-ink">{label}</span><span className="block text-xs text-ash">{hint}</span></span>
          </label>
        ))}
        <label className="flex items-center gap-3 text-sm text-ink"><input type="checkbox" checked={settings.allow_replies} onChange={(e) => void save({ allow_replies: e.target.checked })} />Autoriser les réponses par message</label>
      </Card>
      <Card padding="md" className="space-y-3">
        <div><h2 className="font-display text-base font-bold text-ink">Masquer mes statuts à certains contacts</h2><p className="text-xs text-ash">Ces membres ne sont pas prévenus.</p></div>
        {contacts === null ? <SkeletonList count={2} /> : contacts.length === 0 ? <p className="text-sm text-ash">Vous n’avez pas encore de contact Tratra.</p> : (
          <ul className="divide-y divide-lineSoft">
            {contacts.map((c) => (
              <li key={c.user} className="flex items-center gap-3 py-2.5">
                <Avatar name={c.name} size={36} /><span className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">{c.name}</span>
                <Button size="sm" variant={c.excluded ? "primary" : "outline"} onClick={() => void toggle(c)}>{c.excluded ? "Masqué — rétablir" : "Masquer"}</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function apiPut(body: unknown): Promise<Settings> {
  return apiJson<Settings>("/statuses/settings/", { method: "PUT", body: JSON.stringify(body) });
}

export default function StatusesPage() {
  const [tab, setTab] = useState<"discover" | "mine" | "privacy">("discover");
  const [composing, setComposing] = useState(false);
  const [bump, setBump] = useState(0);
  const [limits, setLimits] = useState<StatusLimits | null>(null);
  useEffect(() => { get<StatusFeed>("/statuses/feed/").then((f) => setLimits(f.limits)).catch(() => undefined); }, []);
  return (
    <>
      <PageHeader title="Statuts" description="Partagez un texte, une photo ou une vidéo visible 24 h, et découvrez ceux des membres Tratra." />
      <Tabs ariaLabel="Statuts" value={tab} onChange={setTab} items={[{ id: "discover", label: "Découvrir" }, { id: "mine", label: "Mes statuts" }, { id: "privacy", label: "Confidentialité" }]} />
      <div className="mt-5">
        {tab === "discover" ? <Discover /> : tab === "mine" ? <Mine onCompose={() => setComposing(true)} refresh={bump} /> : <Privacy />}
      </div>
      {limits ? <StatusComposer open={composing} limits={limits} onClose={() => setComposing(false)} onPublished={() => setBump((b) => b + 1)} /> : null}
    </>
  );
}
