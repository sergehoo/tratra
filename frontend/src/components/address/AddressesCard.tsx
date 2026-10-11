"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import dynamic from "next/dynamic";
import { Crosshair, MapPin, Pencil, Plus, Star, Trash2 } from "lucide-react";
import { apiErrorMessage, ApiError } from "@/lib/api";
import {
  EMPTY_ADDRESS, createAddress, currentPosition, deleteAddress, listAddresses, makePrimary, reverseAddress, searchAddress, updateAddress,
  type Address, type AddressForm, type Suggestion,
} from "@/lib/addresses";
import { Alert, Badge, Button, Card, CardHeader, ConfirmDialog, Modal, Skeleton, TextField } from "@/components/ds";

const AddressPicker = dynamic(() => import("./AddressPicker").then((m) => m.AddressPicker), { ssr: false, loading: () => <Skeleton className="h-64 w-full" /> });

const fromAddress = (a: Address): AddressForm => ({
  label: a.label, country: a.country, city: a.city, commune: a.commune, street: a.street, complement: a.complement,
  latitude: a.latitude, longitude: a.longitude, coords_source: a.coords_source,
});
const line = (a: Pick<Address, "street" | "commune" | "city" | "country">) => [a.street, a.commune, a.city, a.country].filter(Boolean).join(", ");

/** Formulaire d'adresse : autocomplétion, position actuelle (consentement explicite, lecture unique), carte, saisie manuelle toujours possible. */
function AddressDialog({ initial, onClose, onSaved }: { initial: Address | null; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<AddressForm>(initial ? fromAddress(initial) : EMPTY_ADDRESS);
  const [primary, setPrimary] = useState(false);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<Suggestion[]>([]);
  const [manual, setManual] = useState(false);
  const [showMap, setShowMap] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState("");
  const [failure, setFailure] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const seq = useRef(0);
  const set = (patch: Partial<AddressForm>) => setF((v) => ({ ...v, ...patch }));

  useEffect(() => {
    const q = query.trim();
    if (q.length < 3) { setOptions([]); return; }
    const mine = ++seq.current;
    const t = setTimeout(async () => {
      try {
        const r = await searchAddress(q);
        if (mine !== seq.current) return;
        setOptions(r.results);
        setManual(r.manual);
      } catch {
        if (mine === seq.current) setManual(true);
      }
    }, 400);
    return () => clearTimeout(t);
  }, [query]);

  const apply = (s: Suggestion, source: AddressForm["coords_source"], keepLabel = true) => {
    setF((v) => ({ ...v, street: s.street || v.street, commune: s.commune || v.commune, city: s.city || v.city, country: s.country || v.country, latitude: s.latitude, longitude: s.longitude, coords_source: source, label: keepLabel ? v.label : s.label.slice(0, 60) }));
    setOptions([]);
    setQuery("");
  };

  async function useMyPosition() {
    setFailure(""); setInfo("");
    if (!consent) { setFailure("Cochez la case pour autoriser l’utilisation ponctuelle de votre position."); return; }
    setBusy(true);
    try {
      const p = await currentPosition();
      const found = await reverseAddress(p.lat, p.lng);
      if (found) apply(found, "device");
      else { set({ latitude: p.lat, longitude: p.lng, coords_source: "device" }); setInfo("Position enregistrée ; complétez la rue et le quartier."); }
    } catch (e) {
      setFailure(e instanceof Error ? e.message : "Position indisponible.");
    } finally { setBusy(false); }
  }

  async function onMapPick(lat: number, lng: number) {
    set({ latitude: lat, longitude: lng, coords_source: "map" });
    const found = await reverseAddress(lat, lng).catch(() => null);
    if (found) setF((v) => ({ ...v, street: found.street || v.street, commune: found.commune || v.commune, city: found.city || v.city, latitude: lat, longitude: lng, coords_source: "map" }));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setFailure(""); setErrors({});
    try {
      const body = { ...f, location_consent: f.coords_source === "device" ? true : undefined };
      if (initial) await updateAddress(initial.id, body);
      else await createAddress({ ...body, is_primary: primary });
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 400 && err.data && typeof err.data === "object") setErrors(err.data as Record<string, string>);
      else setFailure(apiErrorMessage(err, "L’adresse n’a pas pu être enregistrée."));
    } finally { setBusy(false); }
  }

  const point = f.latitude !== null && f.longitude !== null ? { lat: f.latitude, lng: f.longitude } : null;
  return (
    <Modal open onClose={onClose} dismissible={!busy} size="lg" title={initial ? "Modifier l’adresse" : "Nouvelle adresse"} description="Seul vous voyez vos adresses. Elles ne sont communiquées qu’à l’artisan d’une réservation que vous confirmez.">
      <form onSubmit={submit} noValidate className="space-y-4">
        <div className="relative">
          <TextField label="Rechercher une adresse" optional value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rue, quartier, repère…" autoComplete="off" hint={manual ? "Recherche indisponible : saisissez l’adresse dans les champs ci-dessous." : undefined} />
          {options.length ? (
            <ul role="listbox" aria-label="Suggestions d’adresses" className="absolute inset-x-0 top-full z-popover mt-1 max-h-60 overflow-auto rounded-panel border border-line bg-white p-1 shadow-strong">
              {options.map((s, i) => (
                <li key={`${s.latitude},${s.longitude},${i}`}>
                  <button type="button" role="option" aria-selected="false" onClick={() => apply(s, "geocoder")} className="flex min-h-[44px] w-full items-start gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-canvas focus-visible:bg-canvas focus-visible:outline-none">
                    <MapPin aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><span>{s.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        <div className="rounded-panel bg-canvas p-3">
          <label className="flex items-start gap-2 text-sm text-inkSoft">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1 h-4 w-4 accent-[#2e8b57]" />
            <span>J’autorise Tratra à utiliser ma position <strong>une seule fois</strong> pour renseigner cette adresse. Aucun suivi n’est activé.</span>
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => void useMyPosition()} disabled={busy || !consent} leftIcon={<Crosshair aria-hidden className="h-4 w-4" />}>Utiliser ma position actuelle</Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setShowMap((v) => !v)} leftIcon={<MapPin aria-hidden className="h-4 w-4" />}>{showMap ? "Masquer la carte" : "Choisir sur la carte"}</Button>
          </div>
        </div>
        {showMap ? <AddressPicker value={point} onPick={(la, ln) => void onMapPick(la, ln)} /> : null}
        {point ? <p className="text-xs text-ash">Point enregistré pour le calcul du déplacement ({f.coords_source === "device" ? "position de l’appareil" : f.coords_source === "map" ? "choisi sur la carte" : "adresse trouvée"}). Il n’est jamais montré aux autres comptes.</p> : null}

        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="Nom de l’adresse" optional value={f.label} onChange={(e) => set({ label: e.target.value })} placeholder="Maison, bureau…" maxLength={60} />
          <TextField label="Pays" value={f.country} onChange={(e) => set({ country: e.target.value })} error={errors.country} />
          <TextField label="Ville" value={f.city} onChange={(e) => set({ city: e.target.value })} error={errors.city} required />
          <TextField label="Commune / quartier" value={f.commune} onChange={(e) => set({ commune: e.target.value })} error={errors.commune} />
        </div>
        <TextField label="Rue / localisation" value={f.street} onChange={(e) => set({ street: e.target.value })} error={errors.street} />
        <TextField label="Complément d’adresse" optional value={f.complement} onChange={(e) => set({ complement: e.target.value })} placeholder="Bâtiment, étage, porte…" />
        {!initial ? (
          <label className="flex items-center gap-2 text-sm text-inkSoft">
            <input type="checkbox" checked={primary} onChange={(e) => setPrimary(e.target.checked)} className="h-4 w-4 accent-[#2e8b57]" /> Définir comme adresse principale
          </label>
        ) : null}
        {errors.location_consent ? <Alert tone="danger">{errors.location_consent}</Alert> : null}
        {errors.detail ? <Alert tone="danger">{errors.detail}</Alert> : null}
        {failure ? <Alert tone="danger">{failure}</Alert> : null}
        {info ? <Alert tone="info">{info}</Alert> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>Annuler</Button>
          <Button type="submit" loading={busy}>Enregistrer</Button>
        </div>
      </form>
    </Modal>
  );
}

/** Carte « Adresses » du profil : principale, secondaires, favorites ; ajout, modification, suppression. */
export function AddressesCard() {
  const [rows, setRows] = useState<Address[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Address | "new" | null>(null);
  const [removing, setRemoving] = useState<Address | null>(null);
  const [busy, setBusy] = useState(false);
  const [max, setMax] = useState(10);

  const load = useCallback(async () => {
    setError("");
    try { const r = await listAddresses(); setRows(r.results); setMax(r.max); }
    catch (e) { setError(apiErrorMessage(e, "Vos adresses n’ont pas pu être chargées.")); }
  }, []);
  useEffect(() => void load(), [load]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await fn(); await load(); } catch (e) { setError(apiErrorMessage(e, "L’action a échoué.")); } finally { setBusy(false); }
  };

  return (
    <Card>
      <CardHeader title="Mes adresses" description="Principale, secondaires et favorites. L’adresse principale est demandée avant votre première demande ou prestation." icon={<MapPin className="h-5 w-5" />}
        action={rows && rows.length < max ? <Button size="sm" variant="outline" onClick={() => setEditing("new")} leftIcon={<Plus aria-hidden className="h-4 w-4" />}>Ajouter</Button> : undefined} />
      {error ? <Alert tone="danger" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert> : null}
      {rows === null && !error ? <Skeleton className="mt-4 h-20 w-full" /> : null}
      {rows && rows.length === 0 ? <p className="mt-4 rounded-panel bg-canvas p-4 text-sm text-inkSoft">Aucune adresse enregistrée. Ajoutez votre adresse principale pour faciliter vos demandes.</p> : null}
      <ul className="mt-4 space-y-3">
        {rows?.map((a) => (
          <li key={a.id} className="rounded-panel border border-lineSoft p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">
                  {a.label || "Adresse"}
                  {a.is_primary ? <Badge tone="success">Principale</Badge> : null}
                  {a.is_favorite ? <Badge tone="accent">Favorite</Badge> : null}
                </p>
                <p className="mt-1 break-words text-sm text-inkSoft">{line(a)}{a.complement ? ` — ${a.complement}` : ""}</p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {!a.is_primary ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => makePrimary(a.id))}>Principale</Button> : null}
                <Button size="sm" variant="ghost" disabled={busy} aria-pressed={a.is_favorite} onClick={() => void run(() => updateAddress(a.id, { is_favorite: !a.is_favorite }))} leftIcon={<Star aria-hidden className="h-4 w-4" />}>{a.is_favorite ? "Retirer des favorites" : "Favorite"}</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(a)} leftIcon={<Pencil aria-hidden className="h-4 w-4" />}>Modifier</Button>
                <Button size="sm" variant="ghost" onClick={() => setRemoving(a)} leftIcon={<Trash2 aria-hidden className="h-4 w-4" />}>Supprimer</Button>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {editing ? <AddressDialog initial={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void load(); }} /> : null}
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} title="Supprimer cette adresse ?" description={removing ? line(removing) : undefined} confirmLabel="Supprimer" tone="danger" loading={busy}
        onConfirm={() => void run(async () => { if (removing) await deleteAddress(removing.id); setRemoving(null); })} />
    </Card>
  );
}
