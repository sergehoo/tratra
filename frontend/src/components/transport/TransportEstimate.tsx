"use client";
import { useEffect, useRef, useState } from "react";
import { Truck } from "lucide-react";
import { Alert, Skeleton } from "@/components/ds";
import { describeQuote, estimateTransport, fcfa, type TransportEstimateInput, type TransportQuote, type TransportSlot } from "@/lib/transport";

/**
 * Frais de déplacement avant validation : montant et créneaux calculés par le serveur (tarifs, distance routière, heure d'Abidjan).
 * Rien n'est affiché sans réponse du serveur ; `onQuote` remonte le devis que le client a vu (le serveur le recalcule à la réservation).
 */
export function TransportEstimate({ input, quote, onQuote, notice }: { input: TransportEstimateInput | null; quote: TransportQuote | null; onQuote: (q: TransportQuote | null) => void; notice?: string }) {
  const [slots, setSlots] = useState<TransportSlot[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const seq = useRef(0);
  const key = JSON.stringify(input);

  useEffect(() => {
    if (!input) { onQuote(null); setSlots([]); return; }
    const mine = ++seq.current;
    setLoading(true); setError("");
    const t = setTimeout(async () => {
      try {
        const r = await estimateTransport(input);
        if (mine !== seq.current) return;
        onQuote(r.quote);
        setSlots(r.suggestions);
      } catch {
        if (mine === seq.current) { onQuote(null); setSlots([]); setError("Les frais de déplacement ne peuvent pas être estimés pour le moment ; ils seront recalculés à la réservation."); }
      } finally {
        if (mine === seq.current) setLoading(false);
      }
    }, 500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!input) return <p className="text-xs text-ash">Indiquez le lieu (adresse enregistrée ou position) pour voir les frais de déplacement.</p>;
  if (loading && !quote) return <Skeleton className="h-16 w-full" />;
  return (
    <div className="rounded-panel border border-lineSoft bg-canvas p-3" aria-live="polite">
      {notice ? <Alert tone="warning" className="mb-2">{notice}</Alert> : null}
      {error ? <p className="text-xs text-dangerInk">{error}</p> : null}
      {quote ? (
        <>
          <p className="flex items-center gap-2 text-sm font-semibold text-ink">
            <Truck aria-hidden className="h-4 w-4 text-primary" />
            Déplacement : {quote.applicable && quote.amount > 0 ? fcfa(quote.amount) : "0 FCFA"}
          </p>
          <p className="mt-0.5 text-xs text-inkSoft">{describeQuote(quote)}</p>
          {slots.length > 1 ? (
            <ul className="mt-2 grid gap-1 text-xs text-inkSoft sm:grid-cols-2">
              {slots.map((s) => (
                <li key={s.key} className="flex justify-between gap-2 rounded-lg bg-white px-2.5 py-1.5">
                  <span>{s.label}</span><strong className="text-ink">{fcfa(s.amount)}</strong>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
