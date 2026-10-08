"use client";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle,
  BadgeCheck,
  ChevronDown,
  LayoutGrid,
  LoaderCircle,
  LocateFixed,
  MapPin,
  Navigation,
  Search,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import { ESCROW_ENABLED } from "@/lib/config";
import { formatCount } from "@/lib/format";
import { qs } from "@/lib/public";
import { byServicesCount, useLanding, useTrades } from "./LandingData";
import { CONTAINER, btn } from "./kit";
import { Float } from "./Reveal";

/** Visuels livrés dans /public/images/hero (photos décoratives, sans info superposée). */
const HERO_IMAGE = "/images/hero/hero-main.jpg";
const COLLAGE = ["/images/hero/trade-1.jpg", "/images/hero/trade-2.jpg", "/images/hero/trade-3.jpg"] as const;

/**
 * Entrée du hero en CSS pur : le texte s'affiche dès le premier rendu HTML,
 * sans attendre l'hydratation JS (LCP). « Mouvement réduit » : neutralisé par
 * la règle globale de globals.css.
 */
const HERO_CSS = `
@keyframes tt-rise{from{opacity:0;transform:translate3d(0,18px,0)}to{opacity:1;transform:none}}
@keyframes tt-draw{to{stroke-dashoffset:0}}
.tt-rise{animation:tt-rise .9s cubic-bezier(.22,1,.36,1) both}
.tt-draw{stroke-dasharray:1;stroke-dashoffset:1;animation:tt-draw 1.1s cubic-bezier(.65,0,.35,1) .6s forwards}
`;

type Geo =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; lat: string; lng: string }
  | { status: "error"; message: string };

const GEO_ERRORS: Record<number, string> = {
  1: "Accès à votre position refusé. Indiquez plutôt votre commune ou votre quartier.",
  2: "Position introuvable pour le moment. Indiquez votre commune ou votre quartier.",
  3: "La localisation a pris trop de temps. Réessayez ou indiquez votre commune.",
};

const LABEL = "flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.14em] text-primaryDark";

export default function Hero() {
  const router = useRouter();
  const uid = useId();
  const { trades, loading: tradesLoading } = useTrades();
  const { data: stats } = useLanding("stats");

  const [metier, setMetier] = useState("");
  const [commune, setCommune] = useState("");
  const [geo, setGeo] = useState<Geo>({ status: "idle" });
  const geoRequest = useRef(0);

  const quick = byServicesCount(trades).slice(0, 6);
  const coords = geo.status === "ready" ? geo : null;
  const online = stats?.artisans_online ?? 0;

  const ids = {
    metier: `${uid}-metier`,
    where: `${uid}-ou`,
    status: `${uid}-geo`,
  };

  function locate() {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setGeo({
        status: "error",
        message: "La géolocalisation n'est pas disponible sur cet appareil. Indiquez votre commune.",
      });
      return;
    }
    const request = ++geoRequest.current;
    setGeo({ status: "loading" });
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (request !== geoRequest.current) return;
        setGeo({
          status: "ready",
          lat: pos.coords.latitude.toFixed(4),
          lng: pos.coords.longitude.toFixed(4),
        });
      },
      (err) => {
        if (request !== geoRequest.current) return;
        setGeo({ status: "error", message: GEO_ERRORS[err.code] ?? GEO_ERRORS[2] });
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 300_000 },
    );
  }

  function clearGeo() {
    geoRequest.current += 1;
    setGeo({ status: "idle" });
  }

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    router.push(
      `/search${qs({
        metier,
        commune: coords ? null : commune.trim(),
        lat: coords?.lat,
        lng: coords?.lng,
      })}`,
    );
  }

  const statusMessage =
    geo.status === "loading"
      ? "Recherche de votre position…"
      : geo.status === "ready"
        ? "Position détectée : les artisans seront recherchés autour de vous."
        : geo.status === "error"
          ? geo.message
          : "";

  return (
    <section aria-labelledby="hero-titre" className="relative isolate overflow-hidden bg-night">
      <style dangerouslySetInnerHTML={{ __html: HERO_CSS }} />

      {/* Fond photo + voiles (contraste AA du texte blanc) */}
      <Image src={HERO_IMAGE} alt="" fill priority sizes="100vw" className="-z-20 object-cover object-center" />
      <div
        aria-hidden
        className="absolute inset-0 -z-10 bg-gradient-to-b from-night/90 via-night/80 to-night/95 lg:bg-gradient-to-r lg:from-night/95 lg:via-night/80 lg:to-night/40"
      />
      <div
        aria-hidden
        className="absolute inset-0 -z-10 bg-[radial-gradient(70%_60%_at_10%_0%,rgba(46,139,87,0.5),transparent_70%)]"
      />
      <div
        aria-hidden
        className="absolute inset-0 -z-10 bg-[radial-gradient(55%_50%_at_95%_100%,rgba(31,106,65,0.6),transparent_70%)]"
      />
      <div
        aria-hidden
        className="absolute inset-0 -z-10 opacity-[0.06] [background-image:linear-gradient(rgba(255,255,255,.7)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.7)_1px,transparent_1px)] [background-size:56px_56px] [mask-image:radial-gradient(ellipse_at_30%_40%,black_20%,transparent_70%)]"
      />

      <div
        className={`${CONTAINER} relative grid min-h-[88vh] items-center gap-12 pb-28 pt-28 sm:pt-32 lg:grid-cols-12 lg:gap-8 lg:pb-36 lg:pt-36`}
      >
        {/* Colonne texte + recherche */}
        <div className="min-w-0 lg:col-span-7">
          <p className="tt-rise inline-flex items-center gap-2 rounded-full bg-white/10 px-3.5 py-1.5 text-xs font-semibold text-white/90 ring-1 ring-inset ring-white/15 backdrop-blur sm:text-[13px]">
            <span aria-hidden className="h-2 w-2 rounded-full bg-accent" />
            Dépannage, travaux &amp; entretien à domicile
          </p>

          <h1
            id="hero-titre"
            className="tt-rise mt-5 font-display text-[2.3rem] font-extrabold leading-[1.06] tracking-tight text-white [text-wrap:balance] sm:text-5xl lg:text-[3.5rem] xl:text-[4rem]"
            style={{ animationDelay: "80ms" }}
          >
            L’artisan qu’il vous faut,{" "}
            <span className="relative inline-block whitespace-nowrap text-accent">
              vérifié
              <svg
                aria-hidden
                viewBox="0 0 200 14"
                preserveAspectRatio="none"
                className="absolute -bottom-2 left-0 h-3 w-full text-accent sm:-bottom-2.5 sm:h-3.5"
              >
                <path
                  d="M3 10 C 45 3, 120 2, 197 7"
                  pathLength={1}
                  className="tt-draw"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={4}
                  strokeLinecap="round"
                  vectorEffect="non-scaling-stroke"
                />
              </svg>
            </span>{" "}
            et disponible près de chez vous
          </h1>

          <p
            className="tt-rise mt-6 max-w-xl text-base leading-relaxed text-white/85 sm:text-lg"
            style={{ animationDelay: "160ms" }}
          >
            Badge «&nbsp;Vérifié&nbsp;» après contrôle d’identité et des documents,{" "}
            {ESCROW_ENABLED
              ? "paiement sécurisé par séquestre jusqu’à la fin de la mission"
              : "paiement à la fin de l’intervention"}
            , suivi en temps réel&nbsp;: faites appel à un professionnel en toute sérénité.
          </p>

          {/* Bloc recherche */}
          <form
            role="search"
            aria-label="Rechercher un artisan"
            onSubmit={submit}
            className="tt-rise mt-8 rounded-[1.75rem] bg-white p-2 shadow-[0_32px_80px_-24px_rgba(0,0,0,.65)] ring-1 ring-white/20 sm:p-2.5"
            style={{ animationDelay: "240ms" }}
          >
            <div className="grid gap-1 md:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] md:gap-0 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto]">
              {/* Métier */}
              <div className="relative rounded-2xl px-4 pb-2.5 pt-3 transition-colors focus-within:bg-slate-50 hover:bg-slate-50">
                <label htmlFor={ids.metier} className={LABEL}>
                  <LayoutGrid aria-hidden className="h-3.5 w-3.5" />
                  Métier
                </label>
                <select
                  id={ids.metier}
                  value={metier}
                  onChange={(e) => setMetier(e.target.value)}
                  className="mt-1 block min-h-[28px] w-full cursor-pointer appearance-none truncate bg-transparent pr-7 text-[15px] font-semibold text-ink outline-none"
                >
                  <option value="">Tous les métiers</option>
                  {trades.map((t) => (
                    <option key={t.key} value={t.categories.map((c) => c.slug).join(",")}>
                      {t.label}
                    </option>
                  ))}
                </select>
                <ChevronDown aria-hidden className="pointer-events-none absolute bottom-4 right-4 h-4 w-4 text-ash" />
              </div>

              {/* Où ? */}
              <div className="relative flex flex-wrap items-center gap-x-2 rounded-2xl px-4 pb-2 pt-3 transition-colors sm:flex-nowrap focus-within:bg-slate-50 hover:bg-slate-50 md:before:absolute md:before:inset-y-3 md:before:left-0 md:before:w-px md:before:bg-slate-200">
                <div className={`min-w-0 flex-1 ${coords ? "" : "max-sm:basis-full"}`}>
                  {coords ? (
                    <>
                      <span className={LABEL}>
                        <MapPin aria-hidden className="h-3.5 w-3.5" />
                        Où ?
                      </span>
                      <p className="mt-1 flex min-h-[28px] items-center gap-1.5 truncate text-[15px] font-semibold text-primaryDark">
                        <Navigation aria-hidden className="h-4 w-4 shrink-0" />
                        Autour de ma position
                      </p>
                    </>
                  ) : (
                    <>
                      <label htmlFor={ids.where} className={LABEL}>
                        <MapPin aria-hidden className="h-3.5 w-3.5" />
                        Où ?
                      </label>
                      <input
                        id={ids.where}
                        type="text"
                        value={commune}
                        onChange={(e) => setCommune(e.target.value)}
                        placeholder="Commune ou quartier"
                        autoComplete="address-level2"
                        enterKeyHint="search"
                        maxLength={80}
                        className="mt-1 block min-h-[28px] w-full truncate bg-transparent text-[15px] font-semibold text-ink outline-none placeholder:font-normal placeholder:text-slate-500"
                      />
                    </>
                  )}
                </div>

                {coords ? (
                  <button
                    type="button"
                    onClick={clearGeo}
                    aria-label="Retirer ma position"
                    className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-slate-100 text-ink transition-colors hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    <X aria-hidden className="h-4 w-4" />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={locate}
                    disabled={geo.status === "loading"}
                    aria-describedby={ids.status}
                    className="inline-flex h-11 shrink-0 items-center justify-center gap-1.5 rounded-full bg-primarySoft px-3.5 text-sm font-semibold max-sm:mb-1 max-sm:mt-2 max-sm:w-full text-primaryDark transition-colors hover:bg-primaryDark hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-wait disabled:opacity-80"
                  >
                    {geo.status === "loading" ? (
                      <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
                    ) : (
                      <LocateFixed aria-hidden className="h-4 w-4" />
                    )}
                    <span className="lg:max-xl:sr-only">
                      {geo.status === "loading" ? "Localisation…" : "Autour de moi"}
                    </span>
                  </button>
                )}
              </div>

              {/* Valider */}
              <div className="p-1 md:col-span-2 2xl:col-span-1 2xl:pl-2">
                <button type="submit" className={btn("primary", "lg", "w-full 2xl:h-full 2xl:px-7")}>
                  <Search aria-hidden className="h-5 w-5" />
                  Rechercher
                </button>
              </div>
            </div>
          </form>

          <p
            id={ids.status}
            role="status"
            aria-live="polite"
            className={`mt-3 flex min-h-[1.5rem] items-start gap-2 text-sm ${
              geo.status === "error" ? "text-accent" : "text-white/85"
            }`}
          >
            {geo.status === "error" ? <AlertCircle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" /> : null}
            {statusMessage}
          </p>

          {/* Accès rapide : familles réelles, triées par nombre de prestations */}
          {tradesLoading || quick.length ? (
            <div
              className="tt-rise mt-3 sm:flex sm:flex-wrap sm:items-center sm:gap-2"
              style={{ animationDelay: "320ms" }}
            >
              <p className="mb-2 text-sm font-medium text-white/75 sm:mb-0 sm:mr-1">Accès rapide&nbsp;:</p>
              <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0 [&::-webkit-scrollbar]:hidden">
                {!quick.length
                  ? Array.from({ length: 4 }, (_, i) => (
                      <span key={i} aria-hidden className="h-11 w-28 shrink-0 rounded-full bg-white/10" />
                    ))
                  : quick.map((t) => (
                      <Link
                        key={t.key}
                        href={t.href}
                        className={`min-h-[44px] items-center gap-2 rounded-full border border-white/15 bg-white/10 px-4 text-sm font-semibold text-white backdrop-blur transition hover:-translate-y-0.5 hover:border-accent/60 hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent inline-flex shrink-0 whitespace-nowrap`}
                      >
                        <t.icon aria-hidden className="h-4 w-4 text-accent" />
                        {t.label}
                      </Link>
                    ))}
              </div>
            </div>
          ) : null}

          {/* Réassurance (fonctionnalités réelles de la plateforme) */}
          <ul
            className="tt-rise mt-8 grid grid-cols-3 gap-2 text-center text-xs font-medium text-white/90 sm:flex sm:flex-wrap sm:gap-x-6 sm:gap-y-3 sm:text-left sm:text-sm"
            style={{ animationDelay: "400ms" }}
          >
            {[
              { icon: BadgeCheck, label: "Artisans vérifiés" },
              ESCROW_ENABLED
                ? { icon: ShieldCheck, label: "Paiement sécurisé" }
                : { icon: Wallet, label: "Paiement après l’intervention" },
              { icon: Navigation, label: "Suivi en temps réel" },
            ].map(({ icon: Icon, label }) => (
              <li key={label} className="flex flex-col items-center gap-2 sm:flex-row sm:gap-2.5">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white/10 ring-1 ring-inset ring-white/15 sm:h-8 sm:w-8">
                  <Icon aria-hidden className="h-4 w-4 text-accent" />
                </span>
                {label}
              </li>
            ))}
          </ul>
        </div>

        {/* Collage décoratif (bureau) — aucune information inventée superposée */}
        <div className="relative hidden h-[560px] lg:col-span-5 lg:block">
          <div aria-hidden className="absolute inset-12 rounded-full bg-primary/35 blur-3xl" />

          <Float className="absolute right-0 top-0 w-[72%]" duration={8.5} distance={14}>
            <div
              aria-hidden
              className="relative aspect-[4/5] rotate-[2.5deg] overflow-hidden rounded-[2rem] bg-nightSoft shadow-[0_40px_90px_-30px_rgba(0,0,0,.8)] ring-1 ring-white/15"
            >
              <Image src={COLLAGE[0]} alt="" fill sizes="(min-width: 1280px) 350px, 27vw" className="object-cover" />
            </div>
          </Float>

          <Float className="absolute left-[4%] top-[6%] w-[36%]" duration={7} delay={0.8} distance={10}>
            <div
              aria-hidden
              className="relative aspect-[3/4] -rotate-[7deg] overflow-hidden rounded-3xl bg-nightSoft shadow-[0_30px_60px_-24px_rgba(0,0,0,.8)] ring-4 ring-night/70"
            >
              <Image src={COLLAGE[2]} alt="" fill sizes="(min-width: 1280px) 180px, 14vw" className="object-cover" />
            </div>
          </Float>

          <Float className="absolute bottom-0 left-0 w-[52%]" duration={9.5} delay={1.6} distance={12}>
            <div
              aria-hidden
              className="relative aspect-square -rotate-[3deg] overflow-hidden rounded-[1.75rem] bg-nightSoft shadow-[0_40px_80px_-28px_rgba(0,0,0,.85)] ring-4 ring-night/70"
            >
              <Image src={COLLAGE[1]} alt="" fill sizes="(min-width: 1280px) 260px, 20vw" className="object-cover" />
            </div>
          </Float>

          {/* Données RÉELLES uniquement */}
          {trades.length > 0 ? (
            <Float className="absolute bottom-8 right-0" duration={6.5} delay={0.4} distance={8}>
              <div className="flex items-center gap-3 rounded-2xl bg-white/95 p-3.5 pr-5 shadow-strong ring-1 ring-black/5 backdrop-blur">
                <span className="grid h-11 w-11 place-items-center rounded-xl bg-primarySoft text-primaryDark">
                  <LayoutGrid aria-hidden className="h-5 w-5" />
                </span>
                <div>
                  <p className="font-display text-2xl font-extrabold leading-none text-ink">{trades.length}</p>
                  <p className="mt-1 text-xs font-medium text-ash">familles de métiers</p>
                </div>
              </div>
            </Float>
          ) : null}

          {online > 0 ? (
            <Float className="absolute right-4 top-6" duration={7.5} delay={1.1} distance={8}>
              <div className="flex items-center gap-2.5 rounded-full bg-white/95 py-2 pl-3 pr-4 text-sm font-semibold text-ink shadow-strong ring-1 ring-black/5 backdrop-blur">
                <span aria-hidden className="relative flex h-2.5 w-2.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
                </span>
                {formatCount(online)} artisan{online > 1 ? "s" : ""} en ligne
              </div>
            </Float>
          ) : null}
        </div>
      </div>
    </section>
  );
}
