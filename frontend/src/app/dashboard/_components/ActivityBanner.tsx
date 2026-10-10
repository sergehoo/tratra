"use client";
import { useState } from "react";
import Link from "next/link";
import { Zap } from "lucide-react";
import { Alert, Badge, Card } from "@/components/ds";
import { activityHref } from "@/lib/continuity";
import { useActivities } from "@/lib/useActivities";
import { formatDateTimeShort } from "./dates";

/**
 * « Activité en cours » : retrouver sa mission ou sa réservation en un geste après une fermeture, une coupure, une
 * déconnexion ou un changement d'appareil. Données du serveur ; hors ligne, le dernier état connu est affiché et
 * clairement signalé comme non vérifié. Rien n'est affiché sans activité.
 */
export function ActivityBanner({ className }: { className?: string }) {
  const { items, primary, offline, syncedAt, notice, clearNotice } = useActivities();
  const [all, setAll] = useState(false);
  const a = primary ?? items[0] ?? null;
  if (!a && !notice) return null;
  return (
    <section aria-label="Activité en cours" className={className}>
      {notice ? (
        <Alert tone="info" className="mb-3" action={<button type="button" onClick={clearNotice} className="text-sm font-semibold underline">Fermer</button>}>
          {notice}
        </Alert>
      ) : null}
      {a ? (
        <Card variant="soft" padding="sm" radius="card">
          <div className="flex items-start gap-3">
            <span aria-hidden className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-primary">
              <Zap className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-bold uppercase tracking-wide text-primaryDark">Activité en cours</p>
                <Badge tone="primary">{a.status_label}</Badge>
              </div>
              <p className="mt-1 font-display text-lg font-bold leading-snug text-ink">{a.title}</p>
              <p className="text-sm text-inkSoft">
                {[a.counterpart, a.city, a.booking_date ? formatDateTimeShort(a.booking_date) : null].filter(Boolean).join(" · ")}
              </p>
              {offline ? (
                <p role="status" className="mt-1 text-xs font-medium text-warningInk">
                  Hors ligne — état connu{syncedAt ? ` à ${new Date(syncedAt).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}` : ""}, non vérifié. Nouvelle tentative automatique.
                </p>
              ) : null}
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Link
                  href={activityHref(a)}
                  className="inline-flex items-center rounded-full bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                >
                  {a.resume_label}
                </Link>
                {items.length > 1 ? (
                  <button type="button" aria-expanded={all} onClick={() => setAll((v) => !v)} className="text-sm font-semibold text-primaryDark underline underline-offset-2">
                    {all ? "Masquer la liste" : `Voir les ${items.length} activités`}
                  </button>
                ) : null}
              </div>
              {all ? (
                <ul className="mt-3 divide-y divide-lineSoft rounded-panel border border-lineSoft bg-white">
                  {items.map((it) => (
                    <li key={`${it.kind}-${it.id}`}>
                      <Link href={activityHref(it)} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm hover:bg-lineSoft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                        <span className="min-w-0">
                          <span className="block truncate font-semibold text-ink">{it.title}</span>
                          <span className="block truncate text-xs text-ash">{[it.status_label, it.counterpart].filter(Boolean).join(" · ")}</span>
                        </span>
                        <span aria-hidden className="text-ash">›</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </div>
        </Card>
      ) : null}
    </section>
  );
}
