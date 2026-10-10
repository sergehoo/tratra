"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Megaphone, X } from "lucide-react";
import { apiErrorMessage, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { enqueueSafe } from "@/lib/offlineQueue";
import { resolveAnnouncementAction, type AnnouncementEvent, type FeedAnnouncement } from "@/lib/announcements";
import { Badge, ButtonLink, Card, cx } from "@/components/ds";
import { useImageFallback } from "@/components/ds";
import { formatDateTimeShort } from "./dates";

/**
 * « Vue » / « ouverte » : passent par la file hors ligne persistante (action sûre, rejouée au retour du réseau) ;
 * jamais bloquant (une statistique manquée ne gêne pas l'utilisateur).
 */
export async function signalAnnouncement(userId: number, id: number, event: Exclude<AnnouncementEvent, "dismiss">): Promise<void> {
  try {
    await enqueueSafe(userId, "POST", `/me/announcements/${id}/${event}/`);
  } catch {
    /* non bloquant */
  }
}

/** Annonces visibles de l'utilisateur ; l'erreur est exposée (la page l'affiche, le bandeau l'ignore). */
export function useAnnouncements() {
  const [items, setItems] = useState<FeedAnnouncement[] | null>(null);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setError("");
    try {
      setItems((await get<{ results: FeedAnnouncement[] }>("/me/announcements/")).results);
    } catch (e) {
      setError(apiErrorMessage(e, "Les annonces ne peuvent pas être chargées."));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const dismiss = useCallback(async (id: number) => {
    await post(`/me/announcements/${id}/dismiss/`, {});
    setItems((list) => (list ? list.filter((a) => a.id !== id) : list));
  }, []);

  return { items, error, reload, dismiss };
}

/** Compte chaque annonce affichée comme « vue » une seule fois par chargement de page. */
export function useSeenOnce(ids: number[]) {
  const { user } = useAuth();
  const sent = useRef(new Set<number>());
  const key = ids.join(",");
  useEffect(() => {
    if (!user) return;
    for (const id of ids) {
      if (!sent.current.has(id)) {
        sent.current.add(id);
        void signalAnnouncement(user.id, id, "seen");
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}

function ActionButton({ a, size = "sm" }: { a: FeedAnnouncement; size?: "sm" | "md" }) {
  const { user } = useAuth();
  const action = resolveAnnouncementAction(a);
  if (!action) return null;
  const onClick = () => {
    if (user) void signalAnnouncement(user.id, a.id, "open");
  };
  return action.external ? (
    <a
      href={action.href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={onClick}
      className="inline-flex items-center rounded-full bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
    >
      {action.label}
    </a>
  ) : (
    <ButtonLink href={action.href} size={size} onClick={onClick}>
      {action.label}
    </ButtonLink>
  );
}

export function AnnouncementCard({ a, highlighted, onDismiss }: { a: FeedAnnouncement; highlighted?: boolean; onDismiss: () => void }) {
  const image = useImageFallback(a.image ?? undefined);
  return (
    <Card padding="none" variant={highlighted ? "soft" : "default"} className="overflow-hidden" aria-label={`${a.kind === "promotion" ? "Offre" : "Information"} : ${a.title}`}>
      {a.image && !image.failed ? (
        // Médias servis par l'API (origine autorisée par la CSP) : <img> natif, masqué si l'URL a expiré.
        // eslint-disable-next-line @next/next/no-img-element
        <img ref={image.ref} src={a.image} onError={image.onError} alt="" loading="lazy" decoding="async" className="h-44 w-full object-cover" />
      ) : null}
      <div className="p-5">
        <div className="flex items-center justify-between gap-3">
          <Badge tone={a.kind === "promotion" ? "accent" : "primary"}>{a.kind === "promotion" ? "Offre" : "Information"}</Badge>
          <span className="text-xs text-ash">{formatDateTimeShort(a.delivered_at)}</span>
        </div>
        <h2 className="mt-3 font-display text-lg font-bold leading-snug text-ink">{a.title}</h2>
        <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-inkSoft">{a.body}</p>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <ActionButton a={a} />
          <button type="button" onClick={onDismiss} className="ml-auto text-sm font-semibold text-ash underline-offset-2 hover:text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
            Masquer
          </button>
        </div>
      </div>
    </Card>
  );
}

/** Bandeau de l'accueil : la première annonce active. Rien n'est affiché sans annonce ni en cas d'erreur réseau. */
export function AnnouncementsBanner({ className }: { className?: string }) {
  const { items, dismiss } = useAnnouncements();
  const first = items?.[0];
  useSeenOnce(first ? [first.id] : []);
  if (!first) return null;
  return (
    <section aria-label="Annonce Tratra" className={cx("rounded-card border border-primary/15 bg-primarySoft/60 p-4 sm:p-5", className)}>
      <div className="flex items-start gap-3">
        <span aria-hidden className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-primary">
          <Megaphone className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold text-ink">{first.title}</p>
          <p className="mt-0.5 line-clamp-3 text-sm text-inkSoft">{first.body}</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <ActionButton a={first} />
            <Link href="/dashboard/announcements" className="text-sm font-semibold text-primaryDark underline underline-offset-2">
              {items && items.length > 1 ? `Toutes les annonces (${items.length})` : "Voir l’annonce"}
            </Link>
          </div>
        </div>
        <button
          type="button"
          aria-label="Masquer l’annonce"
          onClick={() => void dismiss(first.id).catch(() => undefined)}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-ash hover:bg-white hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      </div>
    </section>
  );
}
