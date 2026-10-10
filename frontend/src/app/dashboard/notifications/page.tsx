"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Bell, CheckCheck, SlidersHorizontal } from "lucide-react";
import { apiErrorMessage, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { enqueueSafe } from "@/lib/offlineQueue";
import { useDashboard } from "@/lib/dashboard";
import { NOTIFICATION_CATEGORIES, notificationHref, type Notif, type UnreadCount } from "@/lib/notifications";
import type { Paginated } from "@/lib/types";
import { Alert, Button, ButtonLink, Card, EmptyState, PageHeader, SkeletonList, cx } from "@/components/ds";
import { formatDateTimeShort } from "../_components/dates";

/** Les notifications sont l'historique du serveur : lu sur un appareil = lu partout (Web, Flutter, API). */
export default function NotificationsPage() {
  const router = useRouter();
  const dash = useDashboard();
  const { user } = useAuth();
  const [category, setCategory] = useState<string | null>(null);
  const [items, setItems] = useState<Notif[] | null>(null);
  const [counts, setCounts] = useState<UnreadCount>({ unread: 0, by_category: {} });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [list, unread] = await Promise.all([
        get<Paginated<Notif>>(`/notifications/?ordering=-created_at&page_size=50${category ? `&category=${category}` : ""}`),
        get<UnreadCount>("/notifications/unread-count/"),
      ]);
      setItems(list.results);
      setCounts(unread);
    } catch (e) {
      setError(apiErrorMessage(e, "Vos notifications ne peuvent pas être chargées."));
    }
  }, [category]);

  useEffect(() => {
    setItems(null);
    void load();
  }, [load]);

  async function markAll() {
    setBusy(true);
    setFailure("");
    try {
      await post("/notifications/mark-read/", category ? { category } : {});
      await Promise.all([load(), dash.reload()]);
    } catch (e) {
      setFailure(apiErrorMessage(e, "L’opération a échoué."));
    } finally {
      setBusy(false);
    }
  }

  async function open(n: Notif) {
    if (!n.is_read && user) {
      // Accusé de lecture : action sûre, persistée dans la file hors ligne et rejouée au retour du réseau. La navigation
      // n'attend pas le serveur ; les compteurs se rechargent une fois l'accusé envoyé.
      void enqueueSafe(user.id, "PATCH", `/notifications/${n.id}/`, { is_read: true })
        .then(() => Promise.all([load(), dash.reload()]))
        .catch(() => undefined);
    }
    const href = notificationHref(n);
    if (href) router.push(href);
  }

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Les événements de vos réservations, missions, messages, paiements et avis."
        actions={
          <div className="flex flex-wrap gap-2">
            <ButtonLink href="/dashboard/notifications/preferences" variant="outline" size="sm" leftIcon={<SlidersHorizontal aria-hidden className="h-4 w-4" />}>
              Préférences
            </ButtonLink>
            {counts.unread ? (
              <Button variant="outline" size="sm" loading={busy} leftIcon={<CheckCheck aria-hidden className="h-4 w-4" />} onClick={() => void markAll()}>
                {category ? "Marquer cette catégorie comme lue" : "Tout marquer comme lu"}
              </Button>
            ) : null}
          </div>
        }
      />
      <div role="tablist" aria-label="Catégories de notifications" className="mb-4 flex gap-2 overflow-x-auto pb-1">
        {[{ id: null as string | null, label: "Toutes", n: counts.unread }, ...NOTIFICATION_CATEGORIES.map((c) => ({ ...c, n: counts.by_category[c.id] ?? 0 }))].map((c) => (
          <button
            key={c.id ?? "all"}
            type="button"
            role="tab"
            aria-selected={category === c.id}
            onClick={() => setCategory(c.id)}
            className={cx(
              "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3.5 py-2 text-sm font-semibold transition-colors",
              category === c.id ? "border-primary bg-primarySoft text-primaryDark" : "border-line bg-surface text-inkSoft hover:bg-lineSoft",
            )}
          >
            {c.label}
            {c.n ? <span className="rounded-full bg-accent px-1.5 text-xs font-bold text-ink">{c.n}</span> : null}
          </button>
        ))}
      </div>
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      {error ? (
        <Alert tone="danger" title="Notifications indisponibles" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>
      ) : items === null ? (
        <SkeletonList count={4} />
      ) : items.length === 0 ? (
        <EmptyState icon={<Bell />} title="Aucune notification" description="Vous serez prévenu ici dès qu’il se passe quelque chose sur vos réservations ou vos missions." />
      ) : (
        <ul className="grid grid-cols-1 gap-3">
          {items.map((n) => {
            const href = notificationHref(n);
            return (
              <li key={n.id}>
                <Card padding="sm" radius="panel" className={cx("flex items-start gap-3", !n.is_read && "border-primary/25 bg-primarySoft/40")}>
                  <span aria-hidden className={cx("mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-xl", n.is_read ? "bg-lineSoft text-ash" : "bg-primarySoft text-primary")}>
                    <Bell className="h-5 w-5" />
                  </span>
                  <button type="button" onClick={() => void open(n)} className="min-w-0 flex-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" aria-label={`${n.is_read ? "" : "Non lue : "}${n.title} ${n.message}${href ? " — ouvrir" : ""}`}>
                    {n.title ? <p className={cx("text-sm leading-snug", n.is_read ? "font-semibold text-inkSoft" : "font-bold text-ink")}>{n.title}</p> : null}
                    <p className={cx("text-sm leading-snug", n.is_read ? "text-inkSoft" : "text-ink")}>{n.message}</p>
                    <p className="mt-1 text-xs text-ash">
                      {n.category_label} · {formatDateTimeShort(n.created_at)}
                    </p>
                  </button>
                  {!n.is_read ? <span aria-hidden className="mt-2 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" /> : null}
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-6 text-xs text-ash">
        Les alertes sur votre téléphone se règlent dans <Link className="font-semibold text-primaryDark underline" href="/dashboard/notifications/preferences">Préférences</Link>.
      </p>
    </>
  );
}
