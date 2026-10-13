"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Compass, Plus } from "lucide-react";
import { get } from "@/lib/api";
import { Avatar, cx } from "@/components/ds";
import { useInboxEvents } from "@/lib/inbox";
import type { StatusFeed, StatusGroup } from "@/lib/statuses";
import { StatusComposer } from "./StatusComposer";
import { StatusViewer } from "./StatusViewer";

/** Anneau distinctif : dégradé vert → jaune pour un statut non lu, discret pour un statut déjà vu. */
export function Ring({ unseen, children, size = 64 }: { unseen: boolean; children: React.ReactNode; size?: number }) {
  return (
    <span
      className={cx("grid place-items-center rounded-full p-[3px]", unseen ? "bg-gradient-to-tr from-primary via-primary to-accent" : "bg-line")}
      style={{ width: size, height: size }}
    >
      <span className="grid h-full w-full place-items-center rounded-full bg-white p-[2px]">{children}</span>
    </span>
  );
}

/** Barre horizontale des statuts, juste sous l'en-tête de l'accueil : « Mon statut » d'abord, puis les contacts (non lus avant les consultés). */
export function StatusBar() {
  const [feed, setFeed] = useState<StatusFeed | null>(null);
  const [failed, setFailed] = useState(false);
  const [viewer, setViewer] = useState<{ groups: StatusGroup[]; start: number } | null>(null);
  const [composing, setComposing] = useState(false);

  const load = useCallback(async () => {
    try {
      setFeed(await get<StatusFeed>("/statuses/feed/"));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useInboxEvents((e) => {
    if (e.type === "status" || e.type === "status_view" || e.type === "resync") void load();
  });

  if (failed && !feed) return null;       // une panne des statuts ne doit jamais dégrader l'accueil
  if (!feed) return <div aria-hidden className="mb-5 flex gap-4 overflow-hidden">{Array.from({ length: 5 }, (_, i) => <span key={i} className="h-[88px] w-[68px] shrink-0 animate-pulse rounded-2xl bg-lineSoft" />)}</div>;

  const mine = feed.mine;
  const mineGroup: StatusGroup | null = mine.count ? { author: mine.author, statuses: mine.statuses, unseen: 0, seen: true, latest_at: mine.statuses[mine.statuses.length - 1].created_at } : null;
  const viewerGroups = [...(mineGroup ? [mineGroup] : []), ...feed.contacts];

  return (
    <section aria-label="Statuts" className="mb-5">
      <ul className="scrollbar-none -mx-4 flex gap-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
        <li className="shrink-0">
          <div className="relative flex w-[68px] flex-col items-center gap-1.5">
            <button type="button" onClick={() => (mineGroup ? setViewer({ groups: viewerGroups, start: 0 }) : setComposing(true))} aria-label={mineGroup ? "Voir mes statuts" : "Publier un statut"} className="rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2">
              {mineGroup ? <Ring unseen={false} size={64}><Avatar name={mine.author.name} photo={mine.author.avatar} size={52} /></Ring>
                : <span className="grid h-16 w-16 place-items-center rounded-full border-2 border-dashed border-line bg-white p-[3px]"><Avatar name={mine.author.name} photo={mine.author.avatar} size={52} /></span>}
            </button>
            <button type="button" onClick={() => setComposing(true)} aria-label="Ajouter un statut" className="absolute right-0 top-11 grid h-6 w-6 place-items-center rounded-full bg-accent text-ink ring-2 ring-white hover:bg-accentDark"><Plus aria-hidden className="h-4 w-4" /></button>
            <span className="w-full truncate text-center text-[11px] font-semibold text-ink">Mon statut</span>
          </div>
        </li>
        {feed.contacts.map((g, i) => (
          <li key={g.author.id} className="shrink-0">
            <button type="button" onClick={() => setViewer({ groups: viewerGroups, start: i + (mineGroup ? 1 : 0) })} aria-label={`Statuts de ${g.author.name}${g.unseen ? `, ${g.unseen} non lu${g.unseen > 1 ? "s" : ""}` : ""}`}
              className="flex w-[68px] flex-col items-center gap-1.5 rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2">
              <Ring unseen={!g.seen}><Avatar name={g.author.name} photo={g.author.avatar} size={52} /></Ring>
              <span className={cx("w-full truncate text-center text-[11px]", g.seen ? "font-medium text-ash" : "font-bold text-ink")}>{g.author.name}</span>
            </button>
          </li>
        ))}
        {feed.discover_count > 0 ? (
          <li className="shrink-0">
            <Link href="/dashboard/statuses" aria-label={`Découvrir les statuts : ${feed.discover_count} membre${feed.discover_count > 1 ? "s" : ""} à découvrir`} className="relative flex w-[68px] flex-col items-center gap-1.5 rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2">
              <span className="relative grid h-16 w-16 place-items-center rounded-full bg-primarySoft text-primary"><Compass aria-hidden className="h-6 w-6" /><span aria-hidden className="absolute -right-0.5 top-0 grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-[11px] font-bold text-ink ring-2 ring-white">{feed.discover_count}</span></span>
              <span className="w-full truncate text-center text-[11px] font-semibold text-primaryDark">Découvrir</span>
            </Link>
          </li>
        ) : null}
      </ul>
      {viewer ? <StatusViewer groups={viewer.groups} startGroup={viewer.start} onClose={() => { setViewer(null); void load(); }} /> : null}
      <StatusComposer open={composing} limits={feed.limits} onClose={() => setComposing(false)} onPublished={() => void load()} />
    </section>
  );
}
