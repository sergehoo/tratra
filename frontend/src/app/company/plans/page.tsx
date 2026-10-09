"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { m } from "framer-motion";
import { BadgeDollarSign, Check } from "lucide-react";
import { apiErrorMessage, get, post } from "@/lib/api";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  PageHeader,
  Skeleton,
  fadeUp,
} from "@/components/ds";
import type { SubscriptionPlan, Paginated } from "@/lib/types";
import { intervalView, planPrice, stagger } from "../_lib/format";

function PlanCard({
  plan,
  busy,
  onSubscribe,
}: {
  plan: SubscriptionPlan;
  busy: boolean;
  onSubscribe: () => void;
}) {
  const interval = intervalView(plan.interval);
  const price = planPrice(plan.price);
  const features = plan.features ?? [];
  const titleId = `plan-${plan.id}-titre`;

  return (
    <Card as="article" aria-labelledby={titleId} className="flex w-full flex-col">
      {interval ? (
        <div>
          <Badge tone="accent">{interval.label}</Badge>
        </div>
      ) : null}
      <h2 id={titleId} className="mt-3 font-display text-xl font-extrabold leading-tight tracking-tight text-ink">
        {plan.name}
      </h2>
      {price ? (
        <p className="mt-3 flex flex-wrap items-baseline gap-x-1.5">
          <span className="font-display text-3xl font-extrabold leading-none tracking-tight text-ink">{price}</span>
          {interval && Number(plan.price) > 0 ? (
            <span className="text-sm font-medium text-ash">{interval.per}</span>
          ) : null}
        </p>
      ) : null}

      {features.length > 0 ? (
        <ul className="mt-6 space-y-3 border-t border-lineSoft pt-6">
          {features.map((f, i) => (
            <li key={i} className="flex items-start gap-3 text-sm leading-snug text-inkSoft">
              <span aria-hidden className="mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full bg-accent text-ink">
                <Check className="h-3 w-3" strokeWidth={3} />
              </span>
              <span>{f}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-auto pt-6">
        <Button block loading={busy} onClick={onSubscribe} aria-label={`Souscrire à l’offre ${plan.name}`}>
          Souscrire
        </Button>
      </div>
    </Card>
  );
}

export default function PlansPage() {
  const router = useRouter();
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [subscribeError, setSubscribeError] = useState<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  // En mobile, les cartes sont empilées : on ramène le message d'échec dans le champ de vision.
  useEffect(() => {
    if (subscribeError) errorRef.current?.scrollIntoView({ block: "nearest" });
  }, [subscribeError]);

  const load = useCallback(() => {
    setLoading(true);
    setLoadFailed(false);
    get<Paginated<SubscriptionPlan> | SubscriptionPlan[]>("/subscription-plans/?audience=business")
      .then((d) => setPlans(Array.isArray(d) ? d : d.results ?? []))
      .catch(() => setLoadFailed(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function subscribe(planId: number) {
    setBusy(planId);
    setSubscribeError(null);
    try {
      await post("/subscriptions/", { plan: planId });
      router.push("/company");
    } catch (err) {
      setSubscribeError(apiErrorMessage(err, "Impossible d’activer cette offre pour le moment. Réessayez dans un instant."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Abonnements"
        title="Offres entreprise (B2B)"
        description="Choisissez l’offre qui correspond à votre entreprise."
        back={{ href: "/company", label: "Profil & abonnement" }}
      />

      {subscribeError ? (
        <div ref={errorRef} className="mb-6 scroll-mt-24">
          <Alert tone="danger" title="Souscription impossible" onDismiss={() => setSubscribeError(null)}>
            {subscribeError}
          </Alert>
        </div>
      ) : null}

      {loading ? (
        <div role="status" aria-label="Chargement en cours" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-80 !rounded-card" />
          <Skeleton className="h-80 !rounded-card" />
          <Skeleton className="hidden h-80 !rounded-card lg:block" />
          <span className="sr-only">Chargement…</span>
        </div>
      ) : loadFailed ? (
        <Alert
          tone="danger"
          title="Offres indisponibles"
          action={
            <Button size="sm" variant="outline" onClick={load}>
              Réessayer
            </Button>
          }
        >
          Impossible de charger les offres B2B pour le moment.
        </Alert>
      ) : plans.length === 0 ? (
        <EmptyState
          icon={<BadgeDollarSign aria-hidden />}
          title="Aucune offre disponible pour le moment"
          description="Aucune offre B2B n’est publiée actuellement. Votre profil entreprise reste accessible."
          actions={
            <ButtonLink href="/company" variant="outline">
              Voir mon profil entreprise
            </ButtonLink>
          }
        />
      ) : (
        <m.ul
          role="list"
          variants={stagger}
          initial="hidden"
          animate="show"
          className="grid list-none gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          {plans.map((p) => (
            <m.li key={p.id} variants={fadeUp} className="flex">
              <PlanCard plan={p} busy={busy === p.id} onSubscribe={() => subscribe(p.id)} />
            </m.li>
          ))}
        </m.ul>
      )}
    </>
  );
}
