"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, EmptyState, PageHeader, SkeletonList } from "@/components/ds";
import { ProCardView } from "@/components/flash/ProPicker";
import { apiErrorMessage } from "@/lib/api";
import { listFavorites, removeFavorite, type ProCard } from "@/lib/flash";

/** Mes professionnels favoris : réservation rapide (« Choisir mon professionnel » prérempli). */
export default function FavoritesPage() {
  const router = useRouter();
  const [rows, setRows] = useState<ProCard[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => listFavorites().then((r) => setRows(r.results)).catch((e) => setError(apiErrorMessage(e, "Vos favoris ne peuvent pas être chargés."))), []);
  useEffect(() => { void load(); }, [load]);

  function book(p: ProCard) {
    const offer = p.offers[0];
    if (!offer) { setError("Ce professionnel n’a aucune offre active pour le moment."); return; }
    router.push(`/dashboard/commander?matching=direct&category=${offer.category}&pro=${p.id}&service=${offer.id}`);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title="Mes professionnels favoris" description="Retrouvez vos professionnels de confiance et réservez-les en deux gestes." />
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {rows === null && !error ? <SkeletonList /> : rows && !rows.length ? (
        <EmptyState title="Aucun favori" description="Touchez le cœur d’un professionnel lors d’une demande pour le retrouver ici." />
      ) : (
        <div className="grid gap-3">
          {rows?.map((p) => (
            <ProCardView key={p.id} pro={p} chooseLabel="Réserver" onChoose={p.bookable ? () => book(p) : undefined}
              onFavorite={() => void removeFavorite(p.id).then(load).catch((e) => setError(apiErrorMessage(e, "Le favori n’a pas pu être retiré.")))} />
          ))}
        </div>
      )}
    </div>
  );
}
