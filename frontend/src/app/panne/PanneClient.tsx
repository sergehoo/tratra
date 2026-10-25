"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ArrowRight, MapPin, Wrench } from "lucide-react";
import { Alert, Button } from "@/components/ds";
import { formatCount } from "@/lib/format";
import { publicGet } from "@/lib/public";
import { DEFAULT_ICON, ICON_BY_KEY } from "@/lib/trades";

/** Réponse de `GET /handy/catalog/match/` : prestations et métiers pertinents pour une description libre (rien n'est enregistré). */
interface MatchResult {
  id: number; name: string; slug: string; kind: "trade" | "service"; icon_key: string | null; trade: number; trade_name: string; trade_slug: string;
  offers_total: number; score: number; matched: string[];
}
interface MatchResponse { query_terms: string[]; results: MatchResult[]; trades: number[] }

const EXAMPLES = ["Mon frigo ne refroidit plus", "L’écran de mon téléphone est cassé", "Fuite d’eau sous l’évier", "Ma clim coule", "Ma voiture ne démarre pas",
  "Plus de courant, le disjoncteur saute"];
const MAX = 300;

function searchHref(slugs: string[], commune: string): string {
  const sp = new URLSearchParams({ metier: slugs.join(",") });
  if (commune.trim()) sp.set("commune", commune.trim());
  return `/search?${sp.toString().replace(/%2C/g, ",")}`;
}

/** « J'ai une panne » : description libre → prestations suggérées (catalogue public) → artisans de la commune ou une demande directe. */
export default function PanneClient() {
  const sp = useSearchParams();
  const ids = { text: useId(), commune: useId() };
  const [text, setText] = useState(() => (sp.get("q") ?? "").slice(0, MAX));
  const [commune, setCommune] = useState(() => (sp.get("commune") ?? "").slice(0, 60));
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [result, setResult] = useState<MatchResponse | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  async function analyse(value: string) {
    const q = value.trim();
    if (q.length < 3) return;
    setState("loading");
    const r = await publicGet<MatchResponse>(`/catalog/match/?q=${encodeURIComponent(q)}`, { timeoutMs: 6000 });
    setResult(r);
    setState(r ? "idle" : "error");
    requestAnimationFrame(() => resultsRef.current?.focus());
  }

  useEffect(() => {
    if (text.trim().length >= 3) void analyse(text);
    // Lien partagé « /panne?q=… » : analyse au chargement, une seule fois.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submit(e: FormEvent) {
    e.preventDefault();
    void analyse(text);
  }

  const results = result?.results ?? [];
  const top = results.slice(0, 3);
  return (
    <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <form onSubmit={submit} className="rounded-3xl border border-slate-100 bg-white p-5 shadow-soft sm:p-6" aria-label="Décrire ma panne">
        <label htmlFor={ids.text} className="block text-sm font-semibold text-ink">Quel est le problème ?</label>
        <textarea id={ids.text} value={text} onChange={(e) => setText(e.target.value.slice(0, MAX))} rows={4} maxLength={MAX} required
          placeholder="Ex. Mon frigo ne refroidit plus depuis hier"
          className="mt-1.5 w-full rounded-2xl border border-line bg-canvas px-4 py-3 text-[15px] text-ink outline-none focus:ring-2 focus:ring-primary/40" />
        <p className="mt-1 text-xs text-ash">{text.length}/{MAX} · votre description n’est pas enregistrée.</p>
        <div className="mt-3 flex flex-wrap gap-2" aria-label="Exemples">
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" onClick={() => { setText(ex); void analyse(ex); }}
              className="rounded-full bg-slate-50 px-3 py-1.5 text-xs text-inkSoft ring-1 ring-inset ring-slate-200 hover:bg-primarySoft hover:text-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
              {ex}
            </button>
          ))}
        </div>
        <label htmlFor={ids.commune} className="mt-5 block text-sm font-semibold text-ink">Commune ou quartier <span className="font-normal text-ash">(facultatif)</span></label>
        <div className="mt-1.5 flex min-h-[48px] items-center gap-2 rounded-2xl border border-line bg-canvas px-4 focus-within:ring-2 focus-within:ring-primary/40">
          <MapPin aria-hidden className="h-4 w-4 text-primary" />
          <input id={ids.commune} value={commune} onChange={(e) => setCommune(e.target.value.slice(0, 60))} placeholder="Cocody, Yopougon, Marcory…"
            className="w-full bg-transparent text-[15px] text-ink outline-none placeholder:text-fog" />
        </div>
        <Button type="submit" size="lg" className="mt-5 w-full" loading={state === "loading"} disabled={text.trim().length < 3}
          leftIcon={<Wrench aria-hidden className="h-5 w-5" />}>
          Trouver le bon artisan
        </Button>
      </form>

      <div ref={resultsRef} tabIndex={-1} aria-live="polite" className="outline-none">
        {state === "error" ? <Alert tone="danger">L’analyse n’a pas pu être faite. Vérifiez votre connexion et réessayez.</Alert> : null}
        {result && !results.length ? (
          <div className="rounded-3xl border border-slate-100 bg-white p-6 shadow-soft">
            <p className="font-display text-lg font-bold text-ink">Nous n’avons pas reconnu ce problème</p>
            <p className="mt-1 text-sm text-ash">Précisez l’appareil ou la pièce concernée (« frigo », « clim », « robinet »…), ou choisissez directement un métier.</p>
            <Link href="/metiers" className="mt-4 inline-flex min-h-[44px] items-center gap-2 rounded-full border border-line px-5 text-sm font-semibold text-ink hover:border-primary/50">
              Voir tous les métiers <ArrowRight aria-hidden className="h-4 w-4" />
            </Link>
          </div>
        ) : null}
        {results.length ? (
          <div className="rounded-3xl border border-slate-100 bg-white p-5 shadow-soft sm:p-6">
            <h2 className="font-display text-lg font-bold text-ink">Prestations correspondant à votre panne</h2>
            <ul className="mt-4 space-y-2">
              {results.map((r) => {
                const Icon = (r.icon_key && ICON_BY_KEY[r.icon_key]) || DEFAULT_ICON;
                return (
                  <li key={r.id}>
                    <Link href={searchHref([r.slug], commune)}
                      className="flex items-center gap-3 rounded-2xl px-3 py-2.5 ring-1 ring-inset ring-slate-100 hover:bg-primarySoft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primarySoft text-primaryDark"><Icon aria-hidden className="h-5 w-5" /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-ink">{r.name}</span>
                        <span className="block text-xs text-ash">
                          {r.kind === "service" ? r.trade_name : "Métier"} · {r.offers_total > 0 ? `${formatCount(r.offers_total)} offre${r.offers_total > 1 ? "s" : ""}` : "aucune offre pour l’instant"}
                        </span>
                      </span>
                      <ArrowRight aria-hidden className="h-4 w-4 text-ash" />
                    </Link>
                  </li>
                );
              })}
            </ul>
            <div className="mt-5 flex flex-wrap gap-2">
              <Link href={searchHref(top.map((r) => r.slug), commune)}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-full bg-primary px-5 text-sm font-semibold text-white hover:bg-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                Voir les artisans {commune.trim() ? `à ${commune.trim()}` : "disponibles"} <ArrowRight aria-hidden className="h-4 w-4" />
              </Link>
              <Link href={`/dashboard/commander?category=${top[0].id}&matching=auto`}
                className="inline-flex min-h-[44px] items-center rounded-full border border-line px-5 text-sm font-semibold text-ink hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                Trouvez-moi un professionnel
              </Link>
            </div>
          </div>
        ) : null}
        {!result && state !== "error" ? (
          <div className="rounded-3xl border border-dashed border-line p-6 text-sm text-ash">
            Décrivez la panne avec vos mots : l’appareil, ce qui ne marche pas, depuis quand. Tratra propose les prestations adaptées, puis les artisans
            vérifiés de votre commune.
          </div>
        ) : null}
      </div>
    </div>
  );
}
