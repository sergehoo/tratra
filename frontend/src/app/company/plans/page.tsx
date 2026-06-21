"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { get, post } from "@/lib/api";
import { Card, Button, Badge } from "@/components/ui";
import type { SubscriptionPlan, Paginated } from "@/lib/types";

export default function PlansPage() {
  const router = useRouter();
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    get<Paginated<SubscriptionPlan> | SubscriptionPlan[]>("/subscription-plans/?audience=business")
      .then((d) => setPlans(Array.isArray(d) ? d : d.results ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function subscribe(planId: number) {
    setBusy(planId);
    try {
      await post("/subscriptions/", { plan: planId });
      router.push("/company");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <h2 className="text-xl font-bold">Offres entreprise (B2B)</h2>
      {loading ? (
        <p className="text-ash">Chargement…</p>
      ) : plans.length === 0 ? (
        <Card><p className="text-ash">Aucune offre disponible pour le moment.</p></Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {plans.map((p) => (
            <Card key={p.id}>
              <Badge tone="accent">{p.interval === "yearly" ? "Annuel" : "Mensuel"}</Badge>
              <h3 className="mt-2 text-lg font-bold">{p.name}</h3>
              <p className="mt-1 text-2xl font-extrabold text-primary">
                {Number(p.price).toLocaleString("fr-FR")} FCFA
              </p>
              <ul className="mt-3 space-y-1 text-sm text-ash">
                {(p.features ?? []).map((f, i) => <li key={i}>• {f}</li>)}
              </ul>
              <Button className="mt-4 w-full" disabled={busy === p.id} onClick={() => subscribe(p.id)}>
                {busy === p.id ? "…" : "Souscrire"}
              </Button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
