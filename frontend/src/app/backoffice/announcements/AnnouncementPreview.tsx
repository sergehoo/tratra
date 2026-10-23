"use client";
import { ChevronDown, ChevronUp, ExternalLink, Smartphone } from "lucide-react";
import { Alert } from "@/components/ds";
import { pushText } from "@/lib/announcementPreview";

export interface PreviewProps {
  title: string;
  body: string;
  /** Image choisie (fichier local) ou déjà enregistrée. */
  imageSrc: string | null;
  sendPush: boolean;
  actionKind: string;
  actionLabel: string;
  /** Écran de l'application ouvert (libellé du registre + objet désigné). */
  destination: { label: string; detail?: string } | null;
  linkUrl?: string;
  /** Équivalent sur le site (null : pas de bouton sur le site). */
  webHref?: string | null;
  notes: { tone: "info" | "warning" | "danger"; text: string }[];
}

const SMALL_ICON = "/images/notification/ic_stat_tratra.png";
const LARGE_ICON = "/images/notification/tratra_notification_large.png";

/** Notification Android telle que l'affiche l'application (petite icône Tratra, logo en grande icône, image 2:1 déroulée). */
function AndroidNotification({ title, body, imageSrc, cta, expanded }: { title: string; body: string; imageSrc: string | null; cta: string; expanded: boolean }) {
  return (
    <div className="rounded-[20px] bg-white p-3.5 shadow-soft ring-1 ring-black/5" data-testid={expanded ? "push-expanded" : "push-collapsed"}>
      <div className="flex items-center gap-1.5 text-[11px] text-ash">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={SMALL_ICON} alt="" className="h-3.5 w-3.5" />
        <span className="font-semibold text-primaryDark">Tratra</span>
        <span>· maintenant</span>
        {expanded ? <ChevronUp aria-hidden className="ml-auto h-3.5 w-3.5" /> : <ChevronDown aria-hidden className="ml-auto h-3.5 w-3.5" />}
      </div>
      <div className="mt-1.5 flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className={`text-[13px] font-semibold text-ink ${expanded ? "" : "line-clamp-1"}`}>{title || "Titre de l’annonce"}</p>
          <p className={`mt-0.5 whitespace-pre-line text-[12.5px] leading-snug text-inkSoft ${expanded ? "" : "line-clamp-2"}`}>{body || "Contenu de l’annonce"}</p>
        </div>
        {!expanded || !imageSrc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={LARGE_ICON} alt="" className="h-9 w-9 shrink-0 rounded-full" />
        ) : null}
      </div>
      {expanded && imageSrc ? (
        <div className="mt-2.5 aspect-[2/1] overflow-hidden rounded-xl bg-slate-100">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={imageSrc} alt="" className="h-full w-full object-cover" />
        </div>
      ) : null}
      {expanded && cta ? <p className="mt-2.5 text-[12.5px] font-semibold text-primaryDark">{cta}</p> : null}
    </div>
  );
}

/**
 * Aperçu avant publication : notification (repliée, dépliée) et annonce dans l'application, avec la destination ouverte et les
 * points d'attention. Même texte et même recadrage que l'envoi réel (le serveur limite le texte de la notification à 200 caractères
 * et recadre l'image au format 2:1, centrée).
 */
export function AnnouncementPreview(p: PreviewProps) {
  const push = pushText(p.title, p.body);
  const deeplink = p.actionKind === "deeplink";
  const cta = deeplink ? p.actionLabel.trim() || "Voir" : "";
  const inAppCta = p.actionKind === "none" ? "" : p.actionLabel.trim() || "Voir";
  return (
    <section aria-labelledby="apercu-annonce" className="rounded-panel border border-line bg-surface p-4">
      <h3 id="apercu-annonce" className="flex items-center gap-2 text-sm font-bold text-ink">
        <Smartphone aria-hidden className="h-4 w-4 text-primaryDark" /> Aperçu avant publication
      </h3>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-ash">{p.sendPush ? "Notification (Android)" : "Notification : non envoyée"}</p>
          {p.sendPush ? (
            <div className="space-y-2 rounded-2xl bg-slate-200/70 p-2.5">
              <AndroidNotification title={push.title} body={push.body} imageSrc={p.imageSrc} cta={cta} expanded={false} />
              <AndroidNotification title={push.title} body={push.body} imageSrc={p.imageSrc} cta={cta} expanded />
            </div>
          ) : (
            <p className="rounded-xl bg-white p-3 text-sm text-inkSoft ring-1 ring-line">L’annonce apparaîtra seulement dans l’application et sur le site.</p>
          )}
        </div>
        <div className="space-y-2">
          {/* Même cadrage que l'application : image pleine largeur, 160 px de haut sur un téléphone (≈ 2,1:1). */}
          <p className="text-xs font-semibold uppercase tracking-wide text-ash">Dans l’application</p>
          <div className="overflow-hidden rounded-2xl bg-white shadow-soft ring-1 ring-black/5" data-testid="inapp-card">
            {p.imageSrc ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={p.imageSrc} alt="" className="aspect-[15/7] w-full object-cover" />
            ) : null}
            <div className="space-y-1.5 p-3.5">
              <p className="text-[15px] font-bold text-ink">{p.title || "Titre de l’annonce"}</p>
              <p className="whitespace-pre-line text-[13px] leading-snug text-inkSoft">{p.body || "Contenu de l’annonce"}</p>
              {inAppCta ? <span className="mt-1 inline-flex rounded-full bg-primary px-3.5 py-1.5 text-[13px] font-semibold text-white">{inAppCta}</span> : null}
            </div>
          </div>
        </div>
      </div>
      <dl className="mt-4 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="font-semibold text-ink">Toucher la notification ouvre</dt>
        <dd className="text-inkSoft" data-testid="preview-destination">
          {deeplink && p.destination ? <>{p.destination.label}{p.destination.detail ? ` — ${p.destination.detail}` : ""}</> : "L’annonce dans l’application"}
        </dd>
        {p.actionKind === "link" && p.linkUrl ? (
          <>
            <dt className="font-semibold text-ink">Bouton de l’annonce</dt>
            <dd className="flex min-w-0 items-center gap-1 text-inkSoft"><ExternalLink aria-hidden className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{p.linkUrl}</span></dd>
          </>
        ) : null}
        {deeplink ? (
          <>
            <dt className="font-semibold text-ink">Sur le site</dt>
            <dd className="text-inkSoft">{p.webHref ? <code className="text-xs">{p.webHref}</code> : "Pas de page équivalente : le bouton n’apparaît que dans l’application."}</dd>
          </>
        ) : null}
      </dl>
      {p.notes.length ? (
        <ul className="mt-3 space-y-1.5">
          {p.notes.map((n) => (
            <li key={n.text}><Alert tone={n.tone}>{n.text}</Alert></li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
