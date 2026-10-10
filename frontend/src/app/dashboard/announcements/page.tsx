"use client";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Megaphone } from "lucide-react";
import { apiErrorMessage } from "@/lib/api";
import { Alert, Button, EmptyState, PageHeader, SkeletonList } from "@/components/ds";
import { AnnouncementCard, signalAnnouncement, useAnnouncements, useSeenOnce } from "../_components/Announcements";

/** Annonces de Tratra : le serveur décide de la visibilité (audience, expiration, consentement marketing). */
function AnnouncementsList() {
  const params = useSearchParams();
  const focus = Number(params.get("a")) || null;
  const { items, error, reload, dismiss } = useAnnouncements();
  const [failure, setFailure] = useState("");
  const opened = useRef(false);

  const ordered = useMemo(() => (items ? [...items].sort((a, b) => Number(b.id === focus) - Number(a.id === focus)) : null), [items, focus]);
  useSeenOnce(ordered?.map((a) => a.id) ?? []);

  useEffect(() => {
    // Une notification touchée vers cette annonce compte comme une ouverture.
    if (focus && !opened.current && items?.some((a) => a.id === focus)) {
      opened.current = true;
      void signalAnnouncement(focus, "open");
    }
  }, [focus, items]);

  return (
    <>
      <PageHeader title="Annonces" description="Les informations importantes de Tratra et, si vous l’avez accepté, ses offres." />
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      {error ? (
        <Alert tone="danger" title="Annonces indisponibles" action={<Button size="sm" variant="outline" onClick={() => void reload()}>Réessayer</Button>}>{error}</Alert>
      ) : ordered === null ? (
        <SkeletonList count={3} />
      ) : ordered.length === 0 ? (
        <EmptyState icon={<Megaphone />} title="Aucune annonce" description="Les informations importantes de Tratra et, si vous l’avez accepté, ses offres apparaîtront ici." />
      ) : (
        <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {ordered.map((a) => (
            <li key={a.id}>
              <AnnouncementCard
                a={a}
                highlighted={a.id === focus}
                onDismiss={() => {
                  setFailure("");
                  dismiss(a.id).catch((e) => setFailure(apiErrorMessage(e, "Impossible de masquer cette annonce.")));
                }}
              />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export default function AnnouncementsPage() {
  return (
    <Suspense fallback={<SkeletonList count={3} />}>
      <AnnouncementsList />
    </Suspense>
  );
}
