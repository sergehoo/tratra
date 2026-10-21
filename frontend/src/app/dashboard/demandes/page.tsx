"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Alert, Badge, ButtonLink, Card, EmptyState, PageHeader, SkeletonList } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { MATCHING_LABEL, STATUS_TONE, listRequests, type FlashRequest } from "@/lib/flash";

/** Mes demandes (commandes Tratra Flash, les deux modes). */
export default function RequestsPage() {
  const [rows, setRows] = useState<FlashRequest[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { listRequests().then((r) => setRows(r.results)).catch((e) => setError(apiErrorMessage(e, "Vos demandes ne peuvent pas être chargées."))); }, []);
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title="Mes demandes" description="Vos demandes de professionnel, trouvé par Tratra ou choisi par vous."
        actions={<ButtonLink href="/dashboard/commander" leftIcon={<Plus aria-hidden className="h-4 w-4" />}>Nouvelle demande</ButtonLink>} />
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {rows === null && !error ? <SkeletonList /> : rows && !rows.length ? (
        <EmptyState title="Aucune demande" description="Décrivez votre besoin : Tratra trouve un professionnel, ou vous le choisissez." />
      ) : (
        <ul className="space-y-3">
          {rows?.map((r) => (
            <li key={r.id}>
              <Link href={`/dashboard/demandes/${r.id}`} className="block">
                <Card className="hover:border-primary/50">
                  <p className="flex items-center justify-between gap-3"><span className="font-semibold text-ink">{r.category.name}</span><Badge tone={STATUS_TONE[r.status]}>{r.status_label}</Badge></p>
                  <p className="mt-1 text-sm text-ash">{r.commune || r.address} · {r.when_label} · {r.amount_label} · {MATCHING_LABEL[r.matching]}</p>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
