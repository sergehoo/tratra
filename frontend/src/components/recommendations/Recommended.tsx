"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Sparkles, Star, Truck } from "lucide-react";
import { post } from "@/lib/api";
import { Badge, Card, CardHeader, Skeleton } from "@/components/ds";
import { fcfa } from "@/lib/transport";

interface Reco {
  service_id: number; title: string; category: string | null; provider_name: string; price: number | null; price_type: string; score: number;
  distance_km: number | null; available: boolean | null; reasons: string[]; rating: number | null; reviews: number;
  transport: { amount: number; applicable: boolean; fallback: boolean; distance_unavailable: boolean } | null;
}
interface Result { results: Reco[]; located: boolean; used_primary_address: boolean }

/** Services recommandés : moteur déterministe côté serveur (besoin, lieu, disponibilité, réputation vérifiable, prix), jamais de prestataire non éligible. */
export function Recommended({ query }: { query?: string }) {
  const [data, setData] = useState<Result | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    setFailed(false);
    post<Result>("/recommendations/", { q: query || undefined, limit: 4 }).then((r) => alive && setData(r)).catch(() => alive && setFailed(true));
    return () => { alive = false; };
  }, [query]);

  if (failed) return null;                                           // un bloc d'aide : son absence ne bloque jamais l'exploration
  if (!data) return <Skeleton className="mb-6 h-32 w-full" />;
  if (data.results.length === 0) return null;
  return (
    <Card className="mb-6">
      <CardHeader title="Recommandés pour vous" description={data.located ? "Classés selon votre besoin, la distance, la disponibilité, la réputation et le prix." : "Ajoutez votre adresse principale dans votre profil pour tenir compte de la distance."} icon={<Sparkles className="h-5 w-5" />} />
      <ul className="mt-4 grid gap-3 sm:grid-cols-2">
        {data.results.map((r) => (
          <li key={r.service_id}>
            <Link href={`/dashboard/services/${r.service_id}`} className="block h-full rounded-panel border border-lineSoft p-3 transition hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
              <p className="truncate font-display text-[15px] font-bold text-ink">{r.title}</p>
              <p className="text-xs text-ash">{r.provider_name}{r.category ? ` · ${r.category}` : ""}</p>
              <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-inkSoft">
                {r.rating !== null ? <Badge tone="success" icon={<Star />}>{r.rating} · {r.reviews} avis</Badge> : <Badge tone="gray">Peu d’avis</Badge>}
                {r.distance_km !== null ? <Badge tone="gray">≈ {r.distance_km} km</Badge> : null}
                {r.available === true ? <Badge tone="success">Disponible</Badge> : r.available === false ? <Badge tone="warning">Indisponible à ce moment</Badge> : null}
              </p>
              <p className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="font-semibold text-ink">{r.price !== null ? fcfa(r.price) : "Sur devis"}</span>
                {r.transport && r.transport.applicable ? <span className="flex items-center gap-1 text-xs text-inkSoft"><Truck aria-hidden className="h-3.5 w-3.5" />déplacement {fcfa(r.transport.amount)}{r.transport.fallback ? " (forfait)" : ""}</span> : null}
              </p>
              <details className="mt-1 text-xs text-ash" onClick={(e) => e.stopPropagation()}><summary className="cursor-pointer">Pourquoi ce choix ?</summary><ul className="mt-1 list-disc pl-4">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul></details>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
