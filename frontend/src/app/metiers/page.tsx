import type { Metadata } from "next";
import Link from "next/link";
import { ArrowUpRight, LayoutGrid, Wrench } from "lucide-react";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { CONTAINER } from "@/components/ds/layout";
import { formatCount } from "@/lib/format";
import { publicGet, resultsOf } from "@/lib/public";
import { familiesOf, resolveFamilies, resolveTrades, type ResolvedTrade } from "@/lib/trades";
import type { CatalogPayload, Category, Paginated } from "@/lib/types";
import CatalogFinder from "./CatalogFinder";

const TITLE = "Tous les métiers";
const DESCRIPTION =
  "Le catalogue complet des métiers de Tratra, rangés par familles : informatique, téléphones, électroménager, auto et moto, électricité, plomberie, bâtiment, couture et bien d’autres. Choisissez un métier ou décrivez votre panne.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/metiers" },
  openGraph: { type: "website", locale: "fr_FR", siteName: "Tratra", url: "/metiers", title: `${TITLE} · Tratra`, description: DESCRIPTION },
};

// Catalogue public (métiers, prestations, nombre d'offres) : mis en cache 5 minutes côté serveur.
export const revalidate = 300;

function offers(count: number | null): string {
  if (count === null) return "";
  return count > 0 ? `${formatCount(count)} offre${count > 1 ? "s" : ""}` : "Aucune offre pour l’instant";
}

/** Une carte métier : nom, offres, accès direct (Hybrid Matching) et prestations. */
function TradeCard({ t }: { t: ResolvedTrade }) {
  return (
    <li id={t.key} className="scroll-mt-24 rounded-3xl border border-slate-100 bg-white p-5 shadow-soft">
      <div className="flex items-start gap-4">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-primarySoft text-primaryDark">
          <t.icon aria-hidden className="h-6 w-6" strokeWidth={1.8} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-lg font-bold leading-snug text-ink">
            <Link href={t.href} className="inline-flex items-center gap-1.5 rounded hover:text-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
              {t.label}
              <ArrowUpRight aria-hidden className="h-4 w-4 text-slate-400" />
            </Link>
          </h3>
          <p className="mt-0.5 text-xs font-semibold text-ash">{offers(t.offersTotal)}</p>
        </div>
      </div>
      {t.blurb && t.prestations.length === 0 ? <p className="mt-3 text-sm leading-relaxed text-ash">{t.blurb}</p> : null}
      {/* Hybrid Matching : après le métier, Tratra trouve le professionnel ou le client le choisit. */}
      <div className="mt-4 flex flex-wrap gap-2">
        <Link href={`/dashboard/commander?category=${t.id}&matching=auto`} className="inline-flex min-h-[40px] items-center rounded-full bg-primary px-4 text-sm font-semibold text-white hover:bg-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Trouvez-moi un professionnel
        </Link>
        <Link href={`/dashboard/commander?category=${t.id}&matching=direct`} className="inline-flex min-h-[40px] items-center rounded-full border border-line px-4 text-sm font-semibold text-ink hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Choisir mon professionnel
        </Link>
      </div>
      {t.prestations.length ? (
        <ul aria-label={`Prestations : ${t.label}`} className="mt-4 flex flex-wrap gap-2">
          {t.prestations.map((p) => (
            <li key={p.id}>
              <Link
                href={`/search?metier=${p.slug}`}
                className="inline-flex min-h-[36px] items-center gap-1.5 rounded-full bg-slate-50 px-3 text-sm text-inkSoft ring-1 ring-inset ring-slate-200 transition hover:bg-primarySoft hover:text-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                {p.name}
                {typeof p.offers_total === "number" && p.offers_total > 0 ? <span className="text-xs text-ash">({formatCount(p.offers_total)})</span> : null}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** Catalogue COMPLET, rangé par FAMILLES (navigation compacte) : tous les métiers actifs, avec ou sans offre, et leurs prestations —
 *  la même source que la landing, la recherche et l'application. */
export default async function TradesPage() {
  const data = await publicGet<CatalogPayload | Paginated<Category> | Category[]>("/catalog/", { revalidate: 300, timeoutMs: 4000 });
  const categories = resultsOf(data);
  const trades = resolveTrades(categories);
  const families = resolveFamilies(familiesOf(data), trades);

  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas outline-none">
        <div className={`${CONTAINER} py-10 sm:py-14`}>
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-primaryDark">Catalogue</p>
          <h1 className="mt-2 font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">{TITLE}</h1>
          <p className="mt-3 max-w-2xl text-base leading-relaxed text-ash">
            Les métiers sont rangés par familles ; chaque métier regroupe des prestations, dans lesquelles les artisans publient leurs offres. Choisissez un métier
            ou une prestation pour voir les offres disponibles, ou décrivez directement votre panne.
          </p>

          <Link href="/panne" className="mt-6 flex max-w-2xl items-center gap-4 rounded-3xl bg-ink p-5 text-white shadow-soft hover:bg-ink/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-accent text-ink"><Wrench aria-hidden className="h-6 w-6" /></span>
            <span className="min-w-0">
              <span className="block font-display text-lg font-bold">J’ai une panne</span>
              <span className="block text-sm text-white/80">Décrivez votre problème avec vos mots : Tratra trouve le métier et les artisans près de chez vous.</span>
            </span>
          </Link>
          {categories.length ? <CatalogFinder categories={categories} /> : null}

          {families.length ? (
            <>
              <nav aria-label="Familles de métiers" className="mt-8 flex flex-wrap gap-2">
                {families.map((f) => (
                  <a key={f.key} href={`#famille-${f.key}`} className="inline-flex min-h-[40px] items-center gap-2 rounded-full border border-line bg-white px-4 text-sm font-semibold text-ink hover:border-primary/50 hover:text-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                    <f.icon aria-hidden className="h-4 w-4 text-primaryDark" />
                    {f.label}
                  </a>
                ))}
              </nav>
              {families.map((f) => (
                <section key={f.key} id={`famille-${f.key}`} aria-labelledby={`titre-${f.key}`} className="mt-12 scroll-mt-24">
                  <div className="flex items-center gap-3">
                    <span className="grid h-10 w-10 place-items-center rounded-2xl bg-accent/20 text-ink"><f.icon aria-hidden className="h-5 w-5" /></span>
                    <div>
                      <h2 id={`titre-${f.key}`} className="font-display text-2xl font-extrabold tracking-tight text-ink">{f.label}</h2>
                      {f.description ? <p className="text-sm text-ash">{f.description}</p> : null}
                    </div>
                  </div>
                  <ul className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {f.trades.map((t) => <TradeCard key={t.id} t={t} />)}
                  </ul>
                </section>
              ))}
            </>
          ) : (
            <div role="status" className="mt-10 rounded-3xl border border-slate-100 bg-white p-8 text-center shadow-soft">
              <LayoutGrid aria-hidden className="mx-auto h-8 w-8 text-ash" />
              <p className="mt-3 font-display text-lg font-bold text-ink">{data ? "Le catalogue des métiers arrive" : "Les métiers n’ont pas pu être chargés"}</p>
              <p className="mt-1 text-sm text-ash">
                {data ? "Les premiers métiers seront affichés ici dès leur ouverture." : "La connexion au catalogue a échoué. Rechargez la page ou lancez directement une recherche."}
              </p>
              <Link href="/search" className="mt-5 inline-flex min-h-[44px] items-center rounded-full border border-line px-5 text-sm font-semibold text-ink hover:border-primary/50">
                Rechercher un artisan
              </Link>
            </div>
          )}
        </div>
      </main>
      <SiteFooter trades={trades.slice(0, 6).map(({ label, href }) => ({ label, href }))} />
    </>
  );
}
