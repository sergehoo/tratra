"use client";
import { useEffect, useState, useCallback, type ReactNode } from "react";
import { useParams } from "next/navigation";
import {
  Banknote,
  CalendarClock,
  Check,
  ClipboardList,
  Flag,
  MapPin,
  Play,
  UserRound,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { ApiError, get, post } from "@/lib/api";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  EmptyState,
  PageHeader,
  SkeletonPage,
  StatusBadge,
  cx,
} from "@/components/ds";
import { statusView } from "@/lib/status";
import type { Booking } from "@/lib/types";
import { clientName, formatPlace, formatWhen } from "../../_components/format";
import { MessageButton } from "../../../_components/MessageButton";
import { MissionQrCard } from "@/components/trust/MissionQrCard";
import { ArtisanLiveControls } from "@/components/live/ArtisanLiveControls";

// Transitions proposées à l'ouvrier selon le statut courant
const NEXT: Record<string, { status: string; label: string; variant?: "primary" | "ghost" }[]> = {
  pending: [
    { status: "confirmed", label: "Accepter" },
    { status: "cancelled", label: "Refuser", variant: "ghost" },
  ],
  confirmed: [{ status: "in_progress", label: "Démarrer la mission" }],
  in_progress: [{ status: "completed", label: "Marquer terminée" }],
};

// Affichage uniquement : icône du bouton selon le statut visé, étapes de la frise.
const ACTION_ICON: Record<string, LucideIcon> = {
  confirmed: Check,
  cancelled: X,
  in_progress: Play,
  completed: Flag,
};
const PROGRESS = ["pending", "confirmed", "in_progress", "completed"] as const;

const HINT: Record<string, string> = {
  pending: "Cette demande attend votre réponse : acceptez-la ou refusez-la.",
  confirmed: "Démarrez la mission lorsque l’intervention commence.",
  in_progress: "Marquez la mission comme terminée une fois l’intervention achevée.",
  completed: "Cette mission est terminée.",
  cancelled: "Cette mission est annulée : aucune action n’est disponible.",
};

function DetailRow({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3.5 py-4 first:pt-0 last:pb-0">
      <span
        aria-hidden
        className="grid h-10 w-10 shrink-0 place-items-center rounded-panel bg-primarySoft text-primary [&>svg]:h-5 [&>svg]:w-5"
      >
        {icon}
      </span>
      <div className="min-w-0">
        <dt className="text-[11px] font-bold uppercase tracking-[0.16em] text-ash">{label}</dt>
        <dd className="mt-1 break-words text-base font-medium text-ink">{children}</dd>
      </div>
    </div>
  );
}

/** Frise d'avancement dérivée du statut courant (aucune donnée supplémentaire). */
function Progress({ status }: { status: string }) {
  const current = PROGRESS.indexOf(status as (typeof PROGRESS)[number]);
  if (current < 0) return null;
  const finished = status === "completed";
  return (
    <ol aria-label="Avancement de la mission">
      {PROGRESS.map((s, i) => {
        const done = i < current || finished;
        const active = i === current && !finished;
        return (
          <li key={s} aria-current={active ? "step" : undefined} className="relative flex items-center gap-3 pb-5 last:pb-0">
            {i < PROGRESS.length - 1 ? (
              <span
                aria-hidden
                className={cx("absolute left-4 top-8 -ml-px h-[calc(100%-2rem)] w-0.5", i < current || finished ? "bg-primary" : "bg-line")}
              />
            ) : null}
            <span
              aria-hidden
              className={cx(
                "relative grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-bold transition duration-300 ease-emphasized",
                done && "bg-primaryDark text-white",
                active && "bg-accent text-ink ring-4 ring-accentSoft",
                !done && !active && "bg-lineSoft text-ash",
              )}
            >
              {done ? <Check className="h-4 w-4" /> : i + 1}
            </span>
            <span className={cx("text-sm", active ? "font-bold text-ink" : done ? "font-semibold text-inkSoft" : "font-medium text-ash")}>
              {statusView("booking", s).label}
              <span className="sr-only">{done ? " (étape terminée)" : active ? " (étape en cours)" : " (étape à venir)"}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export default function MissionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [b, setB] = useState<Booking | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    get<Booking>(`/bookings/${id}/`)
      .then((d) => {
        setB(d);
        setLoadFailed(false);
      })
      // 404/403 : mission introuvable ; panne réseau ou serveur : message distinct, avec « Réessayer ».
      .catch((e) => setLoadFailed(!(e instanceof ApiError) || e.status >= 500))
      .finally(() => setLoading(false));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  async function transition(status: string) {
    setBusy(true);
    setPendingStatus(status);
    setError("");
    setNotice("");
    try {
      await post(`/bookings/${id}/transition/`, { status });
      setNotice(`Mission mise à jour : ${statusView("booking", status).label}.`);
      load();
    } catch {
      setError("Transition impossible.");
    } finally {
      setBusy(false);
      setPendingStatus(null);
    }
  }

  const back = { href: "/dashboard/provider", label: "Mes prestations" };

  if (loading) return <SkeletonPage />;
  if (!b) {
    return (
      <>
        <PageHeader title="Détail de la mission" back={back} />
        {loadFailed ? (
          <Alert
            tone="danger"
            title="Impossible de charger la mission"
            action={
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setLoading(true);
                  load();
                }}
              >
                Réessayer
              </Button>
            }
          >
            Vérifiez votre connexion puis réessayez.
          </Alert>
        ) : (
          <EmptyState
            icon={<ClipboardList />}
            title="Mission introuvable"
            description="Cette mission n’existe pas ou n’est pas accessible avec votre compte."
            actions={<ButtonLink href="/dashboard/provider">Retour à mes prestations</ButtonLink>}
          />
        )}
      </>
    );
  }

  const actions = NEXT[b.status] ?? [];
  const title = b.service_detail?.title ?? `Mission #${b.id}`;
  const when = formatWhen(b.booking_date, "long");
  const place = formatPlace(b);
  const price = b.proposed_price !== null && b.proposed_price !== undefined && b.proposed_price !== "" ? Number(b.proposed_price) : NaN;
  const kind = b.type === "instant" ? "Intervention immédiate" : b.type === "scheduled" ? "Intervention planifiée" : null;

  return (
    <>
      <PageHeader
        back={back}
        eyebrow={b.service_detail?.title ? `Mission #${b.id}` : "Mission"}
        title={title}
        actions={<StatusBadge kind="booking" status={b.status} />}
      />

      <div className="grid grid-cols-1 animate-rise gap-6 lg:grid-cols-3">
        <Card className="lg:col-start-3 lg:row-start-1">
          <CardHeader title="Prochaine étape" description={HINT[b.status]} icon={<Flag className="h-5 w-5" />} />
          {b.status !== "cancelled" ? <Progress status={b.status} /> : null}

          {actions.length > 0 ? (
            <div className="mt-6 flex flex-col gap-3">
              {actions.map((a) => {
                const Icon = ACTION_ICON[a.status];
                return (
                  <Button
                    key={a.status}
                    size="lg"
                    block
                    variant={a.variant === "ghost" ? "outline" : "primary"}
                    disabled={busy}
                    loading={pendingStatus === a.status}
                    leftIcon={Icon ? <Icon aria-hidden className="h-4 w-4" /> : undefined}
                    onClick={() => transition(a.status)}
                  >
                    {a.label}
                  </Button>
                );
              })}
            </div>
          ) : null}

          {error ? <Alert tone="danger" className="mt-4">{error}</Alert> : null}
          {notice && !error ? <Alert tone="success" className="mt-4">{notice}</Alert> : null}
        </Card>

        {b.status === "confirmed" ? (
          <div className="lg:col-start-3 lg:row-start-3">
            <ArtisanLiveControls bookingId={b.id} />
          </div>
        ) : null}

        {b.status === "confirmed" || b.status === "in_progress" ? (
          <div className="lg:col-start-3 lg:row-start-4">
            <MissionQrCard bookingId={b.id} />
          </div>
        ) : null}

        {b.status !== "cancelled" ? (
          <Card className="lg:col-start-3 lg:row-start-2">
            <p className="font-display text-base font-bold text-ink">Contacter le client</p>
            <p className="mb-4 mt-1 text-sm text-ash">Confirmez l’accès, l’heure ou un détail avant l’intervention.</p>
            <MessageButton bookingId={b.id} label="Écrire au client" />
          </Card>
        ) : null}

        <Card className="lg:col-span-2 lg:col-start-1 lg:row-start-1">
          <CardHeader title="Détails de la mission" icon={<ClipboardList className="h-5 w-5" />} />
          <dl className="divide-y divide-lineSoft">
            <DetailRow icon={<UserRound />} label="Client">
              {clientName(b) ?? "—"}
            </DetailRow>
            <DetailRow icon={<CalendarClock />} label="Date">
              {when ?? "—"}
            </DetailRow>
            <DetailRow icon={<MapPin />} label="Lieu">
              {place ?? "—"}
            </DetailRow>
            {kind ? (
              <DetailRow icon={<Zap />} label="Type de demande">
                {kind}
              </DetailRow>
            ) : null}
            {Number.isFinite(price) && price > 0 ? (
              <DetailRow icon={<Banknote />} label="Prix proposé">
                {price.toLocaleString("fr-FR")} FCFA
              </DetailRow>
            ) : null}
          </dl>
        </Card>
      </div>
    </>
  );
}
