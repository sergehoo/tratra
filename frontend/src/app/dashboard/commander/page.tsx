"use client";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { UserSearch, Zap } from "lucide-react";
import { Alert, Button, Card, PageHeader, SelectField, TextareaField, TextField } from "@/components/ds";
import { AddressAutocomplete, type AddressPick } from "@/components/flash/AddressAutocomplete";
import { ProCardView, ProPicker, fcfa, type ProChoice } from "@/components/flash/ProPicker";
import { apiErrorMessage, get } from "@/lib/api";
import { createRequest, effectiveMatching, intentKey, listFavorites, priceFromOffer, suggest, type Matching, type Suggestion } from "@/lib/flash";
import { resolveTrades } from "@/lib/trades";
import type { Category, Paginated } from "@/lib/types";

/* Commande unique (Hybrid Matching) : « Trouvez-moi un professionnel » (Smart Dispatch) ou « Choisir mon professionnel » (profils, avis,
   badges, favoris). Le serveur conseille un mode et se souvient du dernier choix ; le choix explicite du client n'est jamais écrasé. */

function ModeCard({ value, current, title, hint, icon, recommended, onSelect }: {
  value: Matching; current: Matching; title: string; hint: string; icon: React.ReactNode; recommended: boolean; onSelect: (m: Matching) => void;
}) {
  const selected = value === current;
  return (
    <button type="button" role="radio" aria-checked={selected} data-testid={`mode-${value}`} onClick={() => onSelect(value)}
      className={`flex-1 rounded-panel border p-4 text-left transition ${selected ? "border-primary bg-primarySoft/60 ring-2 ring-primary/30" : "border-line bg-white hover:border-primary/50"}`}>
      <span className="flex items-center gap-2 text-primaryDark">{icon}{recommended ? <span className="ml-auto rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold text-night">Conseillé</span> : null}</span>
      <span className="mt-2 block font-semibold text-ink">{title}</span>
      <span className="mt-0.5 block text-xs text-ash">{hint}</span>
    </button>
  );
}

function OrderForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [catalog, setCatalog] = useState<Category[]>([]);
  const [categoryId, setCategoryId] = useState<number | null>(Number(params.get("category")) || null);
  const [touched, setTouched] = useState<Matching | null>(params.get("matching") === "direct" ? "direct" : params.get("matching") === "auto" ? "auto" : null);
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [place, setPlace] = useState<AddressPick | null>(null);
  const [commune, setCommune] = useState("");
  const [when, setWhen] = useState("");                 // vide = maintenant
  const [quote, setQuote] = useState(false);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [choice, setChoice] = useState<ProChoice | null>(null);
  const [picker, setPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key] = useState(() => intentKey("flash-req"));
  const matching = effectiveMatching(touched, suggestion);
  const whenIso = when ? new Date(when).toISOString() : null;

  useEffect(() => {
    get<Paginated<Category> | Category[]>("/catalog/").then((d) => setCatalog(Array.isArray(d) ? d : d.results ?? [])).catch(() => setCatalog([]));
  }, []);

  // Réservation rapide d'un favori : ?pro=ID&service=ID
  useEffect(() => {
    const pro = Number(params.get("pro"));
    if (!pro) return;
    listFavorites().then((r) => {
      const p = r.results.find((x) => x.id === pro);
      if (!p) return;
      const offer = p.offers.find((o) => o.id === Number(params.get("service"))) ?? p.offers[0] ?? null;
      pick({ pro: p, offer });
    }).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!categoryId) return;
    suggest({ category: categoryId, when: whenIso, quote, lat: place?.lat, lng: place?.lng, commune }).then(setSuggestion).catch(() => setSuggestion(null));
  }, [categoryId, whenIso, quote, place?.lat, place?.lng, commune]);

  const trades = useMemo(() => resolveTrades(catalog), [catalog]);

  function pick(c: ProChoice) {
    setChoice(c);
    setTouched("direct");
    setPicker(false);
    const price = priceFromOffer(c.offer);
    setQuote(price.quote);
    if (price.amount != null) setAmount(String(price.amount));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = Number(amount.replace(/\D/g, ""));
    const problem = !categoryId ? "Choisissez le métier recherché."
      : !place?.label ? "Indiquez l’adresse de l’intervention."
      : !commune.trim() && place.lat == null ? "Indiquez la commune ou utilisez votre position."
      : matching === "direct" && !choice ? "Choisissez votre professionnel, ou laissez Tratra en trouver un."
      : !quote && !value ? "Indiquez le montant que vous proposez." : "";
    if (problem) { setError(problem); return; }
    setBusy(true);
    setError("");
    try {
      const r = await createRequest({
        category: categoryId, address: place!.label, commune: commune.trim(), mode: quote ? "quote" : "firm", ...(quote ? {} : { amount: value }),
        description: description.trim(), ...(whenIso ? { scheduled_for: whenIso } : {}), ...(place!.lat != null ? { lat: place!.lat, lng: place!.lng } : {}),
        matching, ...(matching === "direct" && choice ? { target: choice.pro.id, ...(choice.offer ? { service: choice.offer.id } : {}) } : {}),
      }, key);
      router.push(`/dashboard/demandes/${r.id}`);
    } catch (err) {
      setError(apiErrorMessage(err, "Votre demande n’a pas pu être envoyée."));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="mx-auto max-w-3xl space-y-6">
      <PageHeader title="Trouver un professionnel" description="Laissez Tratra trouver un professionnel vérifié et disponible, ou choisissez-le vous-même sur ses avis et ses badges." />
      <Card className="space-y-5">
        <SelectField label="Métier ou prestation" required value={categoryId ?? ""} onChange={(e) => { setCategoryId(Number(e.target.value) || null); setChoice(null); }}>
          <option value="">Choisir…</option>
          {trades.map((t) => (
            <optgroup key={t.id} label={t.label}>
              <option value={t.id}>{t.label} (tout le métier)</option>
              {t.prestations.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </optgroup>
          ))}
        </SelectField>

        <fieldset>
          <legend className="text-sm font-semibold text-ink">Comment trouver votre professionnel ?</legend>
          <div role="radiogroup" className="mt-2 flex flex-col gap-3 sm:flex-row">
            <ModeCard value="auto" current={matching} title="Trouvez-moi un professionnel" hint="Le premier pro disponible qui accepte" icon={<Zap aria-hidden className="h-5 w-5" />}
              recommended={suggestion?.suggested === "auto"} onSelect={setTouched} />
            <ModeCard value="direct" current={matching} title="Choisir mon professionnel" hint="Profils, avis et badges" icon={<UserSearch aria-hidden className="h-5 w-5" />}
              recommended={suggestion?.suggested === "direct"} onSelect={setTouched} />
          </div>
          {suggestion?.reason ? <p className="mt-2 text-xs text-inkSoft" data-testid="mode-reason">{suggestion.reason}</p> : null}
          {suggestion?.note ? <p className="mt-1 text-xs text-warningInk">{suggestion.note}</p> : null}
        </fieldset>

        <AddressAutocomplete hint="Communiquée au professionnel seulement quand il a accepté."
          onChange={(p) => { setPlace(p); if (p?.commune) setCommune(p.commune); }} />
        <TextField label="Commune ou quartier" value={commune} onChange={(e) => setCommune(e.target.value)} placeholder="Cocody, Yopougon…"
          hint={place?.lat != null ? "Position connue : les professionnels les plus proches sont sollicités." : undefined} />

        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Quand ?" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} hint="Laissez vide pour « maintenant »." />
          <SelectField label="Prix" value={quote ? "quote" : "firm"} onChange={(e) => setQuote(e.target.value === "quote")}>
            <option value="firm">Je propose un prix</option>
            <option value="quote">Je veux des devis</option>
          </SelectField>
        </div>
        {!quote ? <TextField label="Montant proposé (FCFA, déplacement compris)" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)}
          hint={matching === "auto" ? "Le premier professionnel qui accepte ce montant obtient la mission." : "Montant envoyé au professionnel choisi."} /> : null}

        {matching === "direct" ? (
          <div className="space-y-2">
            {choice ? (
              <>
                <ProCardView pro={choice.pro} onChoose={() => setPicker(true)} chooseLabel="Changer" />
                {choice.offer ? <p className="text-xs text-inkSoft">Prestation : {choice.offer.title}{choice.offer.price != null ? ` — ${fcfa(choice.offer.price)}` : ""}</p> : null}
              </>
            ) : (
              <Button type="button" variant="outline" block disabled={!categoryId} onClick={() => setPicker(true)} leftIcon={<UserSearch aria-hidden className="h-4 w-4" />}>
                Choisir le professionnel
              </Button>
            )}
          </div>
        ) : null}

        <TextareaField label="Décrivez votre besoin" optional rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Button type="submit" size="lg" block loading={busy}>Envoyer ma demande</Button>
      </Card>
      {categoryId ? (
        <ProPicker open={picker} onClose={() => setPicker(false)} onPick={pick} category={categoryId} when={whenIso} lat={place?.lat} lng={place?.lng} commune={commune} />
      ) : null}
    </form>
  );
}

export default function OrderPage() {
  return (
    <Suspense fallback={null}>
      <OrderForm />
    </Suspense>
  );
}
