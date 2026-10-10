"use client";
import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Alert, Badge, Button, ConfirmDialog, Modal, PageHeader, Tabs, TextField, TextareaField, type Column } from "@/components/ds";
import { bo, boError, fieldErrors, moneyLabel } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { FilterBar, FilterSelect, ListView, ReasonModal, SearchBox, dt, postTo, useNotice, useTabParam } from "../_components/ui";

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

export default function ServicesPage() {
  const { can } = useBo();
  const [tab, setTab] = useTabParam(["services", "categories"] as const, "services");
  const [notice, setNotice] = useNotice();
  const [q, setQ] = useState("");
  const [active, setActive] = useState("");
  const [category, setCategory] = useState("");
  const services = useBoList<Service>("/services/", { q: useDebounced(q), active, category });
  const cats = useBoList<Category>("/services/categories/", {}, 100);
  const [hide, setHide] = useState<Service | null>(null);
  const [restore, setRestore] = useState<Service | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [form, setForm] = useState<{ open: boolean; category: Category | null }>({ open: false, category: null });
  const [toggle, setToggle] = useState<Category | null>(null);
  const manage = can("services.moderate");

  const sColumns: Column<Service>[] = [
    { key: "title", header: "Service", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.title}</span> },
    { key: "artisan", header: "Artisan", cell: (r) => r.artisan },
    { key: "cat", header: "Catégorie", hideOnMobile: true, cell: (r) => r.category ?? "—" },
    { key: "price", header: "Tarif", hideOnMobile: true, cell: (r) => (r.price_type === "quote" ? "Sur devis" : `${moneyLabel(r.price)} ${PRICE_FR[r.price_type] ?? ""}`) },
    { key: "status", header: "Visibilité", cell: (r) => <span className="flex flex-wrap gap-1.5"><Badge tone={r.is_active ? "success" : "gray"}>{r.is_active ? "Actif" : "Masqué"}</Badge>{r.is_active && !r.published ? <Badge tone="warning">Non publié (artisan inéligible)</Badge> : null}</span> },
    { key: "bk", header: "Réservations", align: "right", hideOnMobile: true, cell: (r) => r.bookings },
    { key: "created", header: "Créé le", hideOnMobile: true, cell: (r) => dt(r.created_at) },
    { key: "act", header: "", align: "right", cell: (r) => (manage ? (r.is_active ? <Button size="sm" variant="danger" onClick={() => setHide(r)}>Masquer</Button> : <Button size="sm" variant="outline" onClick={() => setRestore(r)}>Republier</Button>) : null) },
  ];
  const cColumns: Column<Category>[] = [
    { key: "name", header: "Catégorie", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.parent ? "↳ " : ""}{r.name} <span className="font-normal text-ash">({r.slug})</span></span> },
    { key: "svc", header: "Services", align: "right", cell: (r) => r.services },
    { key: "art", header: "Artisans", align: "right", hideOnMobile: true, cell: (r) => r.artisans },
    { key: "status", header: "Statut", cell: (r) => <Badge tone={r.is_active ? "success" : "gray"}>{r.is_active ? "Active" : "Désactivée"}</Badge> },
    { key: "act", header: "", align: "right", cell: (r) => (manage ? <span className="flex justify-end gap-2"><Button size="sm" variant="outline" onClick={() => setForm({ open: true, category: r })}>Modifier</Button><Button size="sm" variant="outline" onClick={() => setToggle(r)}>{r.is_active ? "Désactiver" : "Activer"}</Button></span> : null) },
  ];

  return (
    <>
      <PageHeader title="Services" description="Modération des services publiés et gestion des catégories. Masquer un service le retire du catalogue sans toucher à son contenu."
        actions={tab === "categories" && manage ? <Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => setForm({ open: true, category: null })}>Nouvelle catégorie</Button> : null} />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      <Tabs ariaLabel="Sections" value={tab} onChange={setTab} className="mb-4" items={[{ id: "services", label: "Services" }, { id: "categories", label: "Catégories" }]} />
      {tab === "services" ? (
        <>
          <FilterBar>
            <SearchBox value={q} onChange={setQ} placeholder="Titre de service ou artisan…" />
            <FilterSelect label="Visibilité" value={active} onChange={setActive} options={[["", "Tous"], ["true", "Actifs"], ["false", "Masqués"]]} />
            <FilterSelect label="Catégorie" value={category} onChange={setCategory} options={[["", "Toutes"], ...cats.rows.map((c): [string, string] => [String(c.id), c.name])]} />
          </FilterBar>
          <ListView list={services} columns={sColumns} rowKey={(r) => r.id} caption="Services" empty="Aucun service ne correspond." />
        </>
      ) : (
        <ListView list={cats} columns={cColumns} rowKey={(r) => r.id} caption="Catégories" empty="Aucune catégorie." />
      )}

      <ReasonModal open={Boolean(hide)} title={`Masquer « ${hide?.title ?? ""} » ?`} description="Le service disparaît du catalogue public. L’artisan en est informé." confirmLabel="Masquer" tone="danger"
        onClose={() => setHide(null)} request={postTo(`/services/${hide?.id}/hide/`)} onDone={() => { setHide(null); setNotice("Service masqué."); services.reload(); }} />
      <ConfirmDialog open={Boolean(restore)} onClose={() => setRestore(null)} title={`Republier « ${restore?.title ?? ""} » ?`} description="Le service redevient visible s’il remplit les conditions de publication." confirmLabel="Republier" loading={restoring}
        onConfirm={async () => { setRestoring(true); try { await bo.post(`/services/${restore?.id}/restore/`, {}); setRestore(null); setNotice("Service republié."); services.reload(); } catch (e) { setRestore(null); setNotice(boError(e, "Impossible de republier ce service.")); } finally { setRestoring(false); } }} />
      <ConfirmDialog open={Boolean(toggle)} onClose={() => setToggle(null)} title={`${toggle?.is_active ? "Désactiver" : "Activer"} « ${toggle?.name ?? ""} » ?`} confirmLabel={toggle?.is_active ? "Désactiver" : "Activer"} tone={toggle?.is_active ? "danger" : "primary"} loading={restoring}
        description={toggle?.is_active ? "La catégorie n’est plus proposée aux visiteurs ; ses services existants ne sont pas supprimés." : "La catégorie redevient visible."}
        onConfirm={async () => { setRestoring(true); try { await bo.patch(`/services/categories/${toggle?.id}/`, { is_active: !toggle?.is_active }); setToggle(null); setNotice("Catégorie mise à jour."); cats.reload(); } catch (e) { setToggle(null); setNotice(boError(e, "Mise à jour impossible.")); } finally { setRestoring(false); } }} />
      <CategoryForm open={form.open} category={form.category} parents={cats.rows} onClose={() => setForm({ open: false, category: null })} onSaved={() => { setForm({ open: false, category: null }); setNotice("Catégorie enregistrée."); cats.reload(); }} />
    </>
  );
}
