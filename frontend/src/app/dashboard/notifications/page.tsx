"use client";
import { useState } from "react";
import { Bell, CheckCheck } from "lucide-react";
import { apiErrorMessage, patch, post } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard";
import { useData } from "@/lib/useData";
import type { Paginated } from "@/lib/types";
import { Alert, Button, Card, EmptyState, PageHeader, SkeletonList, cx } from "@/components/ds";
import { formatDateTimeShort } from "../_components/dates";

interface Notif {
  id: number;
  notification_type: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export default function NotificationsPage() {
  const { data, loading, error, reload } = useData<Paginated<Notif>>("/notifications/?ordering=-created_at", "Vos notifications ne peuvent pas être chargées.");
  const dash = useDashboard();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const items = data?.results ?? [];
  const unread = items.filter((n) => !n.is_read).length;

  async function markAll() {
    setBusy(true);
    setFailure("");
    try {
      await post("/me/notifications/read-all/");
      await Promise.all([reload(), dash.reload()]);
    } catch (e) {
      setFailure(apiErrorMessage(e, "L’opération a échoué."));
    } finally {
      setBusy(false);
    }
  }

  async function markOne(n: Notif) {
    if (n.is_read) return;
    try {
      await patch(`/notifications/${n.id}/`, { is_read: true });
      await Promise.all([reload(), dash.reload()]);
    } catch {
      /* non bloquant : l'état se resynchronise au prochain chargement */
    }
  }

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Les événements de vos réservations, missions, messages et avis."
        actions={unread ? <Button variant="outline" size="sm" loading={busy} leftIcon={<CheckCheck aria-hidden className="h-4 w-4" />} onClick={() => void markAll()}>Tout marquer comme lu</Button> : undefined}
      />
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      {loading ? (
        <SkeletonList count={4} />
      ) : error ? (
        <Alert tone="danger" title="Notifications indisponibles" action={<Button size="sm" variant="outline" onClick={() => void reload()}>Réessayer</Button>}>{error}</Alert>
      ) : items.length === 0 ? (
        <EmptyState icon={<Bell />} title="Aucune notification" description="Vous serez prévenu ici dès qu’il se passe quelque chose sur vos réservations ou vos missions." />
      ) : (
        <ul className="grid grid-cols-1 gap-3">
          {items.map((n) => (
            <li key={n.id}>
              <Card padding="sm" radius="panel" className={cx("flex items-start gap-3", !n.is_read && "border-primary/25 bg-primarySoft/40")}>
                <span aria-hidden className={cx("mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-xl", n.is_read ? "bg-lineSoft text-ash" : "bg-primarySoft text-primary")}>
                  <Bell className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className={cx("text-sm leading-snug", n.is_read ? "text-inkSoft" : "font-semibold text-ink")}>{n.message}</p>
                  <p className="mt-1 text-xs text-ash">{formatDateTimeShort(n.created_at)}</p>
                </div>
                {!n.is_read ? (
                  <Button size="sm" variant="ghost" onClick={() => void markOne(n)}>Marquer lu</Button>
                ) : null}
              </Card>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
