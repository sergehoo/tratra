"use client";
import { useState } from "react";
import { Briefcase, Plus } from "lucide-react";
import { apiErrorMessage, patch } from "@/lib/api";
import { formatFCFA } from "@/lib/format";
import { useData } from "@/lib/useData";
import { Alert, Badge, Button, ButtonLink, Card, EmptyState, SkeletonList } from "@/components/ds";

interface MyService {
  id: number;
  title: string;
  category: string | null;
  price: string | null;
  price_type: string;
  duration: number | null;
  is_active: boolean;
  published: boolean;
  bookings_count: number;
}

const PRICE_SUFFIX: Record<string, string> = { hourly: " / h", fixed: "", quote: "" };

/** Mes services (publiés ou non) — état de publication réel, activation/désactivation. */
export function MyServices() {
  const { data, loading, error, reload } = useData<{ publishable: boolean; results: MyService[] }>(
    "/me/services/",
    "Vos services ne peuvent pas être chargés pour le moment.",
  );
  const [busy, setBusy] = useState<number | null>(null);
  const [failure, setFailure] = useState("");

  async function toggle(s: MyService) {
    setBusy(s.id);
    setFailure("");
    try {
      await patch(`/services/${s.id}/`, { is_active: !s.is_active });
      await reload();
    } catch (e) {
      setFailure(apiErrorMessage(e, "La modification a échoué. Réessayez dans un instant."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="services-title" className="mt-8 sm:mt-10">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <h2 id="services-title" className="font-display text-xl font-extrabold tracking-tight text-ink">
          Mes services
        </h2>
        <ButtonLink href="/dashboard/provider/services/new" size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />}>
          Ajouter un service
        </ButtonLink>
      </div>

      {data && !data.publishable ? (
        <Alert tone="info" title="Vos services ne sont pas encore visibles" className="mb-4"
          action={<ButtonLink href="/dashboard/profile" size="sm" variant="outline">Compléter mon dossier</ButtonLink>}>
          Ils seront publiés dans le catalogue dès que votre profil est complet et que votre identité est vérifiée par
          l’équipe Tratra.
        </Alert>
      ) : null}
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}

      {loading ? (
        <SkeletonList count={2} />
      ) : error ? (
        <Alert tone="danger" title="Services indisponibles" action={<Button size="sm" variant="outline" onClick={() => void reload()}>Réessayer</Button>}>
          {error}
        </Alert>
      ) : !data || data.results.length === 0 ? (
        <EmptyState
          icon={<Briefcase />}
          title="Vous n’avez pas encore de service"
          description="Décrivez ce que vous proposez (métier, tarif, durée). Il sera visible des clients une fois votre profil validé."
          actions={<ButtonLink href="/dashboard/provider/services/new" leftIcon={<Plus aria-hidden className="h-4 w-4" />}>Ajouter un service</ButtonLink>}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-3">
          {data.results.map((s) => {
            const price = s.price_type === "quote" || !s.price ? "Sur devis" : `${formatFCFA(s.price) ?? s.price}${PRICE_SUFFIX[s.price_type] ?? ""}`;
            return (
              <li key={s.id}>
                <Card padding="sm" radius="panel" className="flex flex-wrap items-center gap-3 sm:flex-nowrap">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-display text-[15px] font-bold text-ink">{s.title}</p>
                    <p className="mt-0.5 text-xs text-ash">
                      {[s.category, price, `${s.bookings_count} réservation${s.bookings_count > 1 ? "s" : ""}`].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                  {s.published ? (
                    <Badge tone="success" dot>Publié</Badge>
                  ) : s.is_active ? (
                    <Badge tone="accent" dot>En attente de validation</Badge>
                  ) : (
                    <Badge tone="gray" dot>Désactivé</Badge>
                  )}
                  <Button size="sm" variant="outline" loading={busy === s.id} onClick={() => void toggle(s)}>
                    {s.is_active ? "Désactiver" : "Activer"}
                  </Button>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
