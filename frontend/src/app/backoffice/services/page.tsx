"use client";
import { useEffect, useState } from "react";
import { EyeOff, Pencil, Plus, Power, Undo2, UserRound } from "lucide-react";
import { Alert, Badge, Button, ConfirmDialog, Modal, PageHeader, Tabs, TextField, TextareaField } from "@/components/ds";
import { bo, boError, fieldErrors, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useCounts, useManagedList } from "@/lib/useBoList";
import { FilterBar, FilterSelect, ListView, ReasonModal, SearchBox, StatusChips, dd, postTo, useNotice, useTabParam, type BoColumn, type BulkAction, type RowAction } from "../_components/ui";

interface Service { id: number; title: string; category: string | null; price_type: string; price: string | null; is_active: boolean; artisan: string; artisan_id: number; created_at: string; published: boolean; bookings: number }
interface Category { id: number; name: string; slug: string; description: string; icon: string; is_active: boolean; parent: number | null; services: number; artisans: number }

const PRICE_FR: Record<string, string> = { hourly: "/ h", fixed: "", quote: "Sur devis" };

function CategoryForm({ open, category, parents, onClose, onSaved }: { open: boolean; category: Category | null; parents: Category[]; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ name: "", slug: "", description: "", icon: "", parent: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setForm({ name: category?.name ?? "", slug: category?.slug ?? "", description: category?.description ?? "", icon: category?.icon ?? "", parent: category?.parent ? String(category.parent) : "" });
      setErrors({});
      setFailure("");
    }
  }, [open, category]);

  async function save() {
    setBusy(true);
    setErrors({});
    setFailure("");
    try {
      if (category) await bo.patch(`/services/categories/${category.id}/`, { name: form.name, description: form.description, icon: form.icon });
      else await bo.post("/services/categories/", { ...form, parent: form.parent || null });
      onSaved();
    } catch (e) {
      setErrors(fieldErrors(e));
      setFailure(boError(e, "La catégorie n’a pas pu être enregistrée."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} dismissible={!busy} title={category ? "Modifier la catégorie" : "Nouvelle catégorie"}
      footer={<><Button variant="outline" onClick={onClose} disabled={busy}>Annuler</Button><Button loading={busy} onClick={() => void save()}>Enregistrer</Button></>}>
      <div className="space-y-4">
        <TextField label="Nom" required value={form.name} error={errors.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        {!category ? <TextField label="Identifiant (URL)" required hint="Lettres, chiffres et tirets : ne changera plus." value={form.slug} error={errors.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} /> : null}
        <TextareaField label="Description" optional value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        <TextField label="Icône" optional hint="Nom d’icône utilisé par les applications." value={form.icon} onChange={(e) => setForm({ ...form, icon: e.target.value })} />
        {!category ? (
          <label className="block text-sm font-semibold text-ink">Catégorie parente <span className="text-xs font-normal text-ash">(facultatif)</span>
            <select className="mt-1.5 min-h-[48px] w-full rounded-control border border-line bg-white px-4 text-[15px]" value={form.parent} onChange={(e) => setForm({ ...form, parent: e.target.value })}>
              <option value="">Aucune</option>
              {parents.filter((p) => !p.parent).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            {errors.parent ? <span role="alert" className="mt-1 block text-xs text-dangerInk">{errors.parent}</span> : null}
          </label>
        ) : null}
        {failure && !Object.keys(errors).length ? <Alert tone="danger">{failure}</Alert> : null}
      </div>
    </Modal>
  );
}

function ServicesTab({ categories, onNotice }: { categories: Category[]; onNotice: (m: string) => void }) {
  const { can } = useBo();
  const manage = can("services.moderate");
  const m = useManagedList<Service, { active: string; category: string; from: string; to: string }>("/services/", { active: "", category: "", from: "", to: "" });
  const { values: f, list } = m;
  const counts = useCounts("/services/", { _all: "", true: "active=true", false: "active=false" }, list.count);
  const [hide, setHide] = useState<Service | null>(null);
  const [restore, setRestore] = useState<Service | null>(null);
  const [restoring, setRestoring] = useState(false);

  const columns: BoColumn<Service>[] = [
    { key: "title", header: "Service", primary: true, sort: "title", wrap: true, cell: (r) => <span className="font-semibold text-ink">{r.title}</span> },
    { key: "artisan", header: "Artisan", cell: (r) => r.artisan },
    { key: "cat", header: "Catégorie", hideOnMobile: true, from: "xl", cell: (r) => r.category ?? "—" },
    { key: "price", header: "Tarif", hideOnMobile: true, from: "xl", cell: (r) => (r.price_type === "quote" ? "Sur devis" : `${moneyLabel(r.price)} ${PRICE_FR[r.price_type] ?? ""}`) },
    { key: "status", header: "Visibilité", cell: (r) => <span className="flex flex-wrap gap-1.5"><Badge tone={r.is_active ? "success" : "gray"}>{r.is_active ? "Actif" : "Masqué"}</Badge>{r.is_active && !r.published ? <Badge tone="warning">Non publié</Badge> : null}</span> },
    { key: "bk", header: "Réservations", align: "right", sort: "bookings", hideOnMobile: true, from: "lg", cell: (r) => r.bookings },
    { key: "created", header: "Créé le", sort: "created_at", hideOnMobile: true, from: "2xl", cell: (r) => dd(r.created_at) },
  ];
  const rowActions = (r: Service): RowAction[] => [
    { label: "Masquer le service", icon: EyeOff, tone: "danger", onClick: () => setHide(r), hidden: !manage || !r.is_active },
    { label: "Republier le service", icon: Undo2, onClick: () => setRestore(r), hidden: !manage || r.is_active },
    { label: "Fiche de l’artisan", icon: UserRound, href: `/backoffice/users/${r.artisan_id}`, hidden: !can("users.view") },
  ];
  const bulk: BulkAction<Service>[] | undefined = manage
    ? [
        { id: "hide", label: "Masquer", icon: EyeOff, tone: "danger", title: "Masquer les services sélectionnés ?", confirmLabel: "Masquer", description: "Chaque service disparaît du catalogue public ; chaque artisan en est informé.", eligible: (r) => r.is_active, run: (r, b) => bo.post(`/services/${r.id}/hide/`, b) },
        { id: "restore", label: "Republier", icon: Undo2, title: "Republier les services sélectionnés ?", confirmLabel: "Republier", description: "Un service redevient visible seulement si l’artisan remplit les conditions de publication.", eligible: (r) => !r.is_active, run: (r, b) => bo.post(`/services/${r.id}/restore/`, b) },
      ]
    : undefined;

  return (
    <>
      <StatusChips items={[["", "Tous"], ["true", "Actifs"], ["false", "Masqués"]]} value={f.active} onChange={(v) => m.set({ active: v })} counts={counts} label="Visibilité" />
      <FilterBar search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Titre de service ou artisan…" />} activeCount={m.activeCount} onReset={m.reset} onRefresh={() => void list.reload()} refreshing={list.loading}>
        <FilterSelect label="Catégorie" value={f.category} onChange={(v) => m.set({ category: v })} options={[["", "Toutes"], ...categories.map((c): [string, string] => [String(c.id), c.name])]} />
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowLabel={(r) => r.title}
        caption="Services"
        empty="Aucun service ne correspond."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        ordering={f.ordering}
        onOrdering={(v) => m.set({ ordering: v })}
        rowActions={rowActions}
        bulk={bulk}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />
      <ReasonModal open={Boolean(hide)} title={`Masquer « ${hide?.title ?? ""} » ?`} description="Le service disparaît du catalogue public. L’artisan en est informé." confirmLabel="Masquer" tone="danger"
        onClose={() => setHide(null)} request={hide ? postTo(`/services/${hide.id}/hide/`) : async () => undefined} onDone={() => { setHide(null); onNotice("Service masqué."); void list.reload(); }} />
      <ConfirmDialog open={Boolean(restore)} onClose={() => setRestore(null)} title={`Republier « ${restore?.title ?? ""} » ?`} description="Le service redevient visible s’il remplit les conditions de publication." confirmLabel="Republier" loading={restoring}
        onConfirm={async () => { setRestoring(true); try { await bo.post(`/services/${restore?.id}/restore/`, {}); setRestore(null); onNotice("Service republié."); void list.reload(); } catch (e) { setRestore(null); onNotice(boError(e, "Impossible de republier ce service.")); } finally { setRestoring(false); } }} />
    </>
  );
}

export default function ServicesPage() {
  const { can } = useBo();
  const [tab, setTab] = useTabParam(["services", "categories"] as const, "services");
  const [notice, setNotice] = useNotice();
  const cats = useBoList<Category>("/services/categories/", {}, 100);
  const [form, setForm] = useState<{ open: boolean; category: Category | null }>({ open: false, category: null });
  const [toggle, setToggle] = useState<Category | null>(null);
  const [busy, setBusy] = useState(false);
  const manage = can("services.moderate");

  const cColumns: BoColumn<Category>[] = [
    { key: "name", header: "Catégorie", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.parent ? "↳ " : ""}{r.name} <span className="font-normal text-ash">({r.slug})</span></span> },
    { key: "svc", header: "Services", align: "right", cell: (r) => r.services },
    { key: "art", header: "Artisans", align: "right", hideOnMobile: true, cell: (r) => r.artisans },
    { key: "status", header: "Statut", cell: (r) => <Badge tone={r.is_active ? "success" : "gray"}>{r.is_active ? "Active" : "Désactivée"}</Badge> },
  ];
  const cActions = (r: Category): RowAction[] => [
    { label: "Modifier la catégorie", icon: Pencil, onClick: () => setForm({ open: true, category: r }), hidden: !manage },
    { label: r.is_active ? "Désactiver" : "Activer", icon: Power, tone: r.is_active ? "danger" : "default", onClick: () => setToggle(r), hidden: !manage },
  ];

  return (
    <>
      <PageHeader title="Services" description="Modération des services publiés et gestion des catégories. Masquer un service le retire du catalogue sans toucher à son contenu."
        actions={tab === "categories" && manage ? <Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => setForm({ open: true, category: null })}>Nouvelle catégorie</Button> : null} />
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "services", label: "Services" }, { id: "categories", label: "Catégories", count: cats.count }]} />
      {tab === "services" ? (
        <ServicesTab categories={cats.rows} onNotice={setNotice} />
      ) : (
        <ListView list={cats} columns={cColumns} rowKey={(r) => r.id} rowLabel={(r) => r.name} caption="Catégories" empty="Aucune catégorie." rowActions={cActions} />
      )}
      <ConfirmDialog open={Boolean(toggle)} onClose={() => setToggle(null)} title={`${toggle?.is_active ? "Désactiver" : "Activer"} « ${toggle?.name ?? ""} » ?`} confirmLabel={toggle?.is_active ? "Désactiver" : "Activer"} tone={toggle?.is_active ? "danger" : "primary"} loading={busy}
        description={toggle?.is_active ? "La catégorie n’est plus proposée aux visiteurs ; ses services existants ne sont pas supprimés." : "La catégorie redevient visible."}
        onConfirm={async () => { setBusy(true); try { await bo.patch(`/services/categories/${toggle?.id}/`, { is_active: !toggle?.is_active }); setToggle(null); setNotice("Catégorie mise à jour."); void cats.reload(); } catch (e) { setToggle(null); setNotice(boError(e, "Mise à jour impossible.")); } finally { setBusy(false); } }} />
      <CategoryForm open={form.open} category={form.category} parents={cats.rows} onClose={() => setForm({ open: false, category: null })} onSaved={() => { setForm({ open: false, category: null }); setNotice("Catégorie enregistrée."); void cats.reload(); }} />
    </>
  );
}
