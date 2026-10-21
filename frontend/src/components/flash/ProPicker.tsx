"use client";
import { useCallback, useEffect, useState } from "react";
import { Heart, MapPin, Star } from "lucide-react";
import { Alert, Avatar, Badge, Button, EmptyState, Modal, SkeletonList } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { addFavorite, listPros, removeFavorite, type ProCard } from "@/lib/flash";

const BADGE_FR: Record<string, string> = { VERIFIE: "Vérifié", EXPERT: "Expert", SUR: "Sûr", NOUVEAU: "Nouveau" };
export const fcfa = (n: number) => `${n.toLocaleString("fr-FR")} FCFA`;

/** Carte d'un professionnel : nom, badges, score Trust, avis, distance, prix « à partir de », favori. */
export function ProCardView({ pro, onChoose, chooseLabel = "Choisir", onFavorite }: { pro: ProCard; onChoose?: () => void; chooseLabel?: string; onFavorite?: () => void }) {
  return (
    <div className="rounded-panel border border-line bg-white p-4" data-testid={`pro-${pro.id}`}>
      <div className="flex items-start gap-3">
        <Avatar name={pro.name} photo={pro.photo} size={44} />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-ink">{pro.name}</p>
          <p className="text-xs text-ash">
            {pro.rating != null ? <><Star aria-hidden className="inline h-3.5 w-3.5 text-accentDark" /> {pro.rating.toFixed(1).replace(".", ",")} ({pro.reviews} avis)</> : pro.reviews ? `${pro.reviews} avis` : "Nouveau sur Tratra"}
            {pro.distance_km != null ? <> · <MapPin aria-hidden className="inline h-3.5 w-3.5" /> {pro.distance_km.toFixed(1).replace(".", ",")} km</> : null}
            {pro.trust_score != null ? ` · Trust ${pro.trust_score}/100` : ""}
          </p>
          {pro.badges.length ? <p className="mt-1.5 flex flex-wrap gap-1">{pro.badges.map((b) => <Badge key={b} tone={b === "VERIFIE" ? "success" : b === "EXPERT" ? "accent" : "primary"}>{BADGE_FR[b] ?? b}</Badge>)}</p> : null}
        </div>
        {onFavorite ? (
          <button type="button" onClick={onFavorite} aria-pressed={pro.favorite} aria-label={pro.favorite ? "Retirer des favoris" : "Ajouter aux favoris"} className="rounded-full p-2 text-danger hover:bg-dangerSoft">
            <Heart aria-hidden className="h-5 w-5" fill={pro.favorite ? "currentColor" : "none"} />
          </button>
        ) : null}
      </div>
      {pro.why.length ? (
        <details className="mt-2 text-xs text-ash">
          <summary className="cursor-pointer font-semibold text-inkSoft">Pourquoi ce professionnel ?</summary>
          <ul className="mt-1 space-y-0.5">{pro.why.map((w) => <li key={w.label}>{w.label} : {w.detail}</li>)}</ul>
        </details>
      ) : null}
      {onChoose ? (
        <div className="mt-3 flex items-center justify-between gap-3">
          <span className="text-sm font-semibold text-primaryDark">{pro.price_from != null ? `À partir de ${fcfa(pro.price_from)}` : "Prix sur devis ou à proposer"}</span>
          <Button size="sm" onClick={onChoose}>{chooseLabel}</Button>
        </div>
      ) : null}
    </div>
  );
}

export interface ProChoice { pro: ProCard; offer: ProCard["offers"][number] | null }

/** « Choisir mon professionnel » : professionnels réellement disponibles pour ce métier et ce créneau (aucun profil inventé). */
export function ProPicker({ open, onClose, onPick, category, when, lat, lng, commune, exclude = [] }: {
  open: boolean; onClose: () => void; onPick: (c: ProChoice) => void; category: number; when?: string | null; lat?: number | null; lng?: number | null; commune?: string; exclude?: number[];
}) {
  const [sort, setSort] = useState("recommended");
  const [favorites, setFavorites] = useState(false);
  const [topRated, setTopRated] = useState(false);
  const [rows, setRows] = useState<ProCard[] | null>(null);
  const [error, setError] = useState("");
  const [offerFor, setOfferFor] = useState<ProCard | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const r = await listPros({ category, when, lat, lng, commune, sort, favorites, minRating: topRated ? 4 : null });
      setRows(r.results.filter((p) => !exclude.includes(p.id)));
    } catch (e) {
      setError(apiErrorMessage(e, "Les professionnels ne peuvent pas être chargés."));
    }
  }, [category, when, lat, lng, commune, sort, favorites, topRated, exclude]);

  useEffect(() => { if (open) void load(); }, [open, load]);

  async function toggleFavorite(p: ProCard) {
    try {
      if (p.favorite) await removeFavorite(p.id); else await addFavorite(p.id);
      void load();
    } catch (e) {
      setError(apiErrorMessage(e, "Le favori n’a pas pu être modifié."));
    }
  }

  function choose(p: ProCard) {
    if (p.offers.length > 1) setOfferFor(p);
    else onPick({ pro: p, offer: p.offers[0] ?? null });
  }

  const chip = (active: boolean, label: string, onClick: () => void) => (
    <button type="button" onClick={onClick} aria-pressed={active}
      className={`min-h-[36px] rounded-full px-3 text-sm ring-1 ring-inset ${active ? "bg-primarySoft font-semibold text-primaryDark ring-primary/40" : "bg-white text-inkSoft ring-line"}`}>{label}</button>
  );

  return (
    <Modal open={open} onClose={onClose} size="lg" title="Choisir mon professionnel" description="Professionnels vérifiés et disponibles pour ce métier et ce créneau.">
      <div className="mb-3 flex flex-wrap gap-2">
        {([["recommended", "Recommandés"], ["distance", "Plus proches"], ["rating", "Mieux notés"], ["price", "Prix"]] as const).map(([v, l]) => <span key={v}>{chip(sort === v, l, () => setSort(v))}</span>)}
        {chip(favorites, "Favoris", () => setFavorites((f) => !f))}
        {chip(topRated, "4★ et plus", () => setTopRated((t) => !t))}
      </div>
      {error ? <Alert tone="danger" className="mb-3">{error}</Alert> : null}
      {offerFor ? (
        <div className="space-y-2">
          <p className="text-sm font-semibold text-ink">Quelle prestation de {offerFor.name} ?</p>
          {offerFor.offers.map((o) => (
            <button key={o.id} type="button" onClick={() => { onPick({ pro: offerFor, offer: o }); setOfferFor(null); }}
              className="flex w-full items-center justify-between rounded-panel border border-line px-4 py-3 text-left text-sm hover:border-primary">
              <span>{o.title}</span><span className="font-semibold">{o.price != null ? fcfa(o.price) : "Sur devis"}</span>
            </button>
          ))}
          <Button variant="ghost" size="sm" onClick={() => setOfferFor(null)}>Retour</Button>
        </div>
      ) : rows === null ? <SkeletonList /> : rows.length ? (
        <div className="grid gap-3">{rows.map((p) => <ProCardView key={p.id} pro={p} onChoose={() => choose(p)} onFavorite={() => void toggleFavorite(p)} />)}</div>
      ) : (
        <EmptyState title="Aucun professionnel disponible" description="Personne n’est libre pour ce métier et ce créneau. Changez l’horaire ou laissez Tratra trouver un professionnel." />
      )}
    </Modal>
  );
}
