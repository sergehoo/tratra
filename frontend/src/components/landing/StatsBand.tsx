"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useInView, useIsomorphicLayoutEffect, useReducedMotion } from "framer-motion";
import { ArrowRight, BadgeCheck, CircleCheck, LayoutGrid, Star, Wrench, type LucideIcon } from "lucide-react";
import { formatCount, formatRating } from "@/lib/format";
import type { PublicStats } from "@/lib/types";
import { useLanding } from "./LandingData";
import { CONTAINER } from "./kit";
import { Reveal } from "./Reveal";

interface StatItem {
  key: string;
  value: number;
  decimals?: number;
  suffix?: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
}

/** Ne retient que les chiffres réels non nuls de /public/stats/. */
function itemsFrom(stats: PublicStats): StatItem[] {
  const items: StatItem[] = [];
  if (stats.categories > 0)
    items.push({ key: "categories", value: stats.categories, label: "Catégories de services", icon: LayoutGrid });
  if (stats.services > 0)
    items.push({
      key: "services",
      value: stats.services,
      label: stats.services > 1 ? "Prestations publiées" : "Prestation publiée",
      icon: Wrench,
    });
  if (stats.artisans_verified > 0)
    items.push({
      key: "artisans",
      value: stats.artisans_verified,
      label: stats.artisans_verified > 1 ? "Artisans vérifiés" : "Artisan vérifié",
      icon: BadgeCheck,
    });
  if (stats.missions_completed > 0)
    items.push({
      key: "missions",
      value: stats.missions_completed,
      label: stats.missions_completed > 1 ? "Missions réalisées" : "Mission réalisée",
      icon: CircleCheck,
    });
  if (stats.rating_average !== null && stats.rating_average !== undefined && stats.rating_average > 0)
    items.push({
      key: "rating",
      value: stats.rating_average,
      decimals: 1,
      suffix: "/5",
      label: "Note moyenne",
      hint: stats.reviews_count > 0 ? `sur ${formatCount(stats.reviews_count)} avis` : undefined,
      icon: Star,
    });
  return items;
}

function formatValue(value: number, decimals = 0): string {
  if (decimals) return formatRating(value) ?? value.toFixed(decimals);
  return formatCount(Math.round(value));
}

/**
 * Compteur animé au défilement.
 * Le HTML serveur porte la valeur RÉELLE (lisible sans JS) ; après hydratation,
 * le compteur repart de 0 avant peinture (la carte est alors encore masquée par
 * <Reveal>) puis s'anime à l'entrée dans la vue. Mouvement réduit : valeur fixe.
 */
function CountUp({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.6 });
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(value);
  const [armed, setArmed] = useState(false);

  useIsomorphicLayoutEffect(() => {
    if (reduce) return;
    setDisplay(0);
    setArmed(true);
  }, [reduce]);

  useEffect(() => {
    if (!inView) return;
    if (reduce || !armed) {
      setDisplay(value);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const duration = 1500;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setDisplay(value * (1 - Math.pow(1 - t, 3)));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, reduce, armed, value]);

  const shown = decimals
    ? display.toLocaleString("fr-FR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : formatCount(Math.round(display));

  return (
    <span ref={ref} className="tabular-nums">
      <span aria-hidden>{shown}</span>
      <span className="sr-only">{formatValue(value, decimals)}</span>
    </span>
  );
}

const GRID: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-2",
  3: "grid-cols-2 sm:grid-cols-3",
  4: "grid-cols-2 lg:grid-cols-4",
  5: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5",
};

/** Bandeau de chiffres réels, en chevauchement du hero. */
export default function StatsBand() {
  const { data, loading } = useLanding("stats");
  const items = data ? itemsFrom(data) : [];

  if (!data && !loading) return null; // indisponible : masqué proprement
  if (data && !items.length) return null;

  return (
    <section aria-labelledby="chiffres-titre" className="relative z-10 pt-px">
      <h2 id="chiffres-titre" className="sr-only">
        Tratra en chiffres
      </h2>
      <div className={CONTAINER}>
        <Reveal y={16} amount={0.3}>
          <div className="-mt-[4.0625rem] rounded-3xl bg-white p-5 shadow-strong ring-1 ring-slate-100 sm:-mt-[5.0625rem] sm:p-8">
            {!data ? (
              <div role="status" aria-label="Chargement des chiffres" className="grid grid-cols-2 gap-6 lg:grid-cols-4">
                {Array.from({ length: 4 }, (_, i) => (
                  <div key={i} aria-hidden className="space-y-3">
                    <div className="skeleton h-11 w-11 !rounded-2xl" />
                    <div className="skeleton h-8 w-24" />
                    <div className="skeleton h-3 w-32" />
                  </div>
                ))}
              </div>
            ) : (
              <div className="lg:flex lg:items-center lg:gap-10">
                <dl className={`grid flex-1 gap-x-6 gap-y-8 ${GRID[items.length] ?? GRID[5]}`}>
                  {items.map((item, i) => {
                    const lastOdd = items.length % 2 === 1 && i === items.length - 1 && items.length > 1;
                    return (
                      <div
                        key={item.key}
                        className={`flex flex-col ${lastOdd ? "col-span-2 sm:col-span-1" : ""} ${
                          items.length === 1 ? "items-center text-center" : ""
                        }`}
                      >
                        <dt className="order-2 mt-1 text-sm font-medium text-ash">
                          {item.label}
                          {item.hint ? <span className="block text-xs text-ash/90">{item.hint}</span> : null}
                        </dt>
                        <dd className="order-1 flex items-center gap-3">
                          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-primarySoft text-primaryDark">
                            <item.icon
                              aria-hidden
                              className={`h-5 w-5 ${item.key === "rating" ? "fill-accent text-accent" : ""}`}
                            />
                          </span>
                          <span className="font-display text-3xl font-extrabold tracking-tight text-ink sm:text-[2.5rem]">
                            <CountUp value={item.value} decimals={item.decimals} />
                            {item.suffix ? (
                              <span className="ml-0.5 text-lg font-bold text-ash sm:text-xl">{item.suffix}</span>
                            ) : null}
                          </span>
                        </dd>
                      </div>
                    );
                  })}
                </dl>
                {items.length <= 3 ? (
                  <div className="mt-8 border-t border-slate-100 pt-6 lg:mt-0 lg:w-80 lg:shrink-0 lg:border-l lg:border-t-0 lg:pl-10 lg:pt-0">
                    <p className="text-sm font-semibold text-ink">Chiffres réels de la plateforme</p>
                    <p className="mt-1 text-sm leading-relaxed text-ash">
                      Issus directement du catalogue Tratra et actualisés automatiquement.
                    </p>
                    <Link
                      href="/search"
                      className="mt-2 inline-flex min-h-[44px] items-center gap-1.5 rounded-lg text-sm font-semibold text-primaryDark hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      Explorer les prestations
                      <ArrowRight aria-hidden className="h-4 w-4" />
                    </Link>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
