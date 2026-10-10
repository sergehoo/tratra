"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  CalendarDays,
  FileText,
  MapPin,
  MessageSquareText,
  SearchX,
  UserRound,
  Users,
  Wallet,
  XCircle,
} from "lucide-react";
import { ApiError, apiErrorMessage, get, post } from "@/lib/api";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  PageHeader,
  SkeletonPage,
  StatusBadge,
} from "@/components/ds";
import { formatFCFA, priceLabel } from "@/lib/format";
import type { Booking, ReplacementSuggestion } from "@/lib/types";
import { ArtisanLine } from "../../_components/ArtisanLine";
import { BookingProgress } from "../../_components/BookingProgress";
import { DetailList, type DetailItem } from "../../_components/DetailList";
import { MessageButton } from "../../_components/MessageButton";
import { IdentityVerifyCard } from "@/components/trust/IdentityVerifyCard";
import { formatDateTimeLong } from "../../_components/dates";
import { useReveal } from "../../_components/useReveal";
import { artisanDisplayName } from "@/lib/artisan";

/** Champs renvoyés par l'API de réservation mais absents du type partagé `Booking`. */
type BookingView = Booking & {
  description?: string | null;
  handyman_comment?: string | null;
};

/** Texte libre saisi par un utilisateur : retours à la ligne conservés. */
function FreeText({ children }: { children: string }) {
  return <span className="whitespace-pre-line font-normal text-inkSoft">{children}</span>;
}

export default function BookingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [b, setB] = useState<BookingView | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);
  const [acceptingId, setAcceptingId] = useState<number | null>(null);
  const [repl, setRepl] = useState<ReplacementSuggestion[]>([]);
  /** idle : rien demandé · loading : requête en cours · loaded : réponse reçue (peut être vide). */
  const [replState, setReplState] = useState<"idle" | "loading" | "loaded">("idle");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const feedbackRef = useRef<HTMLDivElement>(null);

  useReveal(feedbackRef, actionError || notice);

  /**
   * `initial` : premier chargement (squelette, erreur plein écran, « introuvable »).
   * Sinon : actualisation silencieuse après une action — la page reste affichée.
   */
  const load = useCallback(
    async (initial = false) => {
      if (initial) {
        setLoading(true);
        setLoadError("");
        setNotFound(false);
      }
      try {
        setB(await get<BookingView>(`/bookings/${id}/`));
      } catch (requestError) {
        if (initial) {
          setB(null);
          if (requestError instanceof ApiError && requestError.status === 404) setNotFound(true);
          else setLoadError(apiErrorMessage(requestError, "Cette réservation ne peut pas être chargée pour le moment."));
        } else {
          setActionError(
            apiErrorMessage(requestError, "L’affichage n’a pas pu être actualisé. Rechargez la page pour voir l’état à jour."),
          );
        }
      } finally {
        if (initial) setLoading(false);
      }
    },
    [id],
  );

  useEffect(() => {
    void load(true);
  }, [load]);

  async function cancel() {
    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      await post(`/bookings/${id}/transition/`, { status: "cancelled" });
      setNotice("Votre réservation a été annulée.");
      await load();
    } catch (requestError) {
      setActionError(apiErrorMessage(requestError, "La réservation n’a pas pu être annulée."));
    } finally {
      setBusy(false);
      setConfirmCancel(false);
    }
  }

  async function loadReplacements() {
    setActionError("");
    setNotice("");
    setReplState("loading");
    try {
      const data = await get<ReplacementSuggestion[]>(`/bookings/${id}/replacements/`);
      setRepl(Array.isArray(data) ? data : []);
      setReplState("loaded");
    } catch (requestError) {
      setRepl([]);
      setReplState("idle");
      setActionError(apiErrorMessage(requestError, "Les artisans de remplacement ne peuvent pas être chargés pour le moment."));
    }
  }

  async function accept(suggestionId: number) {
    setBusy(true);
    setAcceptingId(suggestionId);
    setActionError("");
    setNotice("");
    try {
      await post(`/bookings/${id}/accept-replacement/`, { suggestion_id: suggestionId });
      setRepl([]);
      setReplState("idle");
      setNotice("Votre réservation est confiée à l’artisan que vous avez choisi.");
      await load();
    } catch (requestError) {
      setActionError(apiErrorMessage(requestError, "Le remplacement n’a pas pu être appliqué."));
    } finally {
      setBusy(false);
      setAcceptingId(null);
    }
  }

  if (loading) return <SkeletonPage />;

  if (loadError) {
    return (
      <>
        <PageHeader title="Réservation indisponible" back={{ href: "/dashboard/bookings", label: "Mes réservations" }} />
        <Alert
          tone="danger"
          title="Chargement impossible"
          action={
            <Button size="sm" variant="outline" onClick={() => void load(true)}>
              Réessayer
            </Button>
          }
        >
          {loadError}
        </Alert>
      </>
    );
  }

  if (notFound || !b) {
    return (
      <>
        <PageHeader title="Réservation introuvable" back={{ href: "/dashboard/bookings", label: "Mes réservations" }} />
        <EmptyState
          icon={<SearchX aria-hidden />}
          title="Cette réservation n’existe pas ou n’est plus accessible"
          description="Retrouvez la liste de vos réservations pour accéder à celle que vous cherchez."
          actions={<ButtonLink href="/dashboard/bookings">Mes réservations</ButtonLink>}
        />
      </>
    );
  }

  const svc = b.service_detail;
  const title = svc?.title ?? `Réservation n° ${b.id}`;
  const cancellable = ["pending", "confirmed"].includes(b.status);
  const finished = b.status === "completed" || b.status === "cancelled";

  const publicName = artisanDisplayName(svc);
  const firstName = b.handyman_detail?.first_name;
  const artisan = svc && publicName ? <ArtisanLine service={svc} size={44} /> : firstName || "Non renseigné";
  const when = formatDateTimeLong(b.booking_date);
  const place = [b.address, b.city].filter(Boolean).join(", ");
  const proposed = formatFCFA(b.proposed_price);

  const details: DetailItem[] = [
    { label: "Artisan", icon: UserRound, value: artisan },
    { label: "Date et heure", icon: CalendarDays, value: when ?? "Non renseignée" },
    { label: "Adresse", icon: MapPin, value: place || "Non renseignée" },
  ];
  if (svc) details.push({ label: "Tarif du service", icon: Wallet, value: priceLabel(svc) });
  if (proposed) details.push({ label: "Prix proposé", icon: Wallet, value: proposed });
  if (b.description?.trim()) {
    details.push({ label: "Votre demande", icon: FileText, value: <FreeText>{b.description.trim()}</FreeText> });
  }
  if (b.handyman_comment?.trim()) {
    details.push({ label: "Message de l’artisan", icon: MessageSquareText, value: <FreeText>{b.handyman_comment.trim()}</FreeText> });
  }

  return (
    <>
      <PageHeader
        eyebrow={svc?.category_detail?.name}
        title={title}
        description={`Réservation n° ${b.id}`}
        back={{ href: "/dashboard/bookings", label: "Mes réservations" }}
        actions={<StatusBadge kind="booking" status={b.status} />}
      />

      <div ref={feedbackRef} className="mb-6 space-y-3 empty:hidden">
        {notice ? (
          <Alert tone="success" onDismiss={() => setNotice("")}>
            {notice}
          </Alert>
        ) : null}
        {actionError ? (
          <Alert tone="danger" onDismiss={() => setActionError("")}>
            {actionError}
          </Alert>
        ) : null}
      </div>

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="Avancement" />
            <BookingProgress status={b.status} />
          </Card>

          <Card>
            <CardHeader title="Détails de l’intervention" />
            <DetailList items={details} />
          </Card>
        </div>

        <div className="space-y-6">
          {cancellable ? (
            <Card>
              <CardHeader title="Gérer la réservation" description="Cette réservation n’a pas encore démarré." />
              <div className="space-y-3">
                <Button
                  variant="soft"
                  block
                  onClick={() => void loadReplacements()}
                  loading={replState === "loading"}
                  disabled={busy}
                  leftIcon={<Users aria-hidden className="h-4 w-4" />}
                >
                  Voir des artisans de remplacement
                </Button>
                <Button
                  variant="outline"
                  block
                  onClick={() => setConfirmCancel(true)}
                  disabled={busy}
                  leftIcon={<XCircle aria-hidden className="h-4 w-4 text-danger" />}
                >
                  Annuler la réservation
                </Button>
              </div>
            </Card>
          ) : null}

          {cancellable && replState === "loaded" && repl.length === 0 ? (
            <Alert tone="info" title="Aucun remplaçant disponible">
              Aucun artisan de remplacement n’est disponible pour le moment. Votre réservation reste inchangée.
            </Alert>
          ) : null}

          {cancellable && repl.length > 0 ? (
            <Card>
              <CardHeader
                title="Artisans de remplacement"
                description="Choisissez l’artisan qui reprendra cette intervention."
              />
              <ul className="grid grid-cols-1 gap-3">
                {repl.map((r) => {
                  const suggested = r.suggested_service_detail;
                  const name = artisanDisplayName(suggested);
                  return (
                    <li key={r.id} className="animate-rise space-y-3 rounded-panel border border-lineSoft bg-canvas p-4">
                      <p className="font-display text-base font-bold leading-snug text-ink">{suggested?.title ?? "Service"}</p>
                      {suggested ? <ArtisanLine service={suggested} size={36} /> : null}
                      <div className="flex items-center justify-between gap-3">
                        {suggested ? (
                          <span className="font-display text-base font-extrabold text-primaryDark">{priceLabel(suggested)}</span>
                        ) : (
                          <span />
                        )}
                        <Button
                          size="sm"
                          onClick={() => void accept(r.id)}
                          disabled={busy}
                          loading={acceptingId === r.id}
                          aria-label={name ? `Choisir ${name} pour cette réservation` : "Choisir cet artisan pour cette réservation"}
                        >
                          Choisir
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Card>
          ) : null}

          {["confirmed", "in_progress", "completed"].includes(b.status) ? (
            <IdentityVerifyCard bookingId={b.id} active={b.status !== "completed"} />
          ) : null}

          {b.handyman_detail && b.status !== "cancelled" ? (
            <Card>
              <p className="font-display text-base font-bold text-ink">Un message à l’artisan ?</p>
              <p className="mt-1 mb-4 text-sm text-ash">Précisez l’accès, l’heure ou un détail de la prestation.</p>
              <MessageButton bookingId={b.id} label="Écrire à l’artisan" />
            </Card>
          ) : null}

          {svc?.id ? (
            <Card variant="soft">
              <p className="font-display text-base font-bold text-ink">
                {finished ? "Besoin d’un nouveau passage ?" : "Le service réservé"}
              </p>
              <p className="mt-1 text-sm text-ash">
                {finished
                  ? "Refaites une demande pour ce service depuis sa fiche."
                  : "Retrouvez la fiche complète du service."}
              </p>
              <ButtonLink href={`/dashboard/services/${svc.id}`} variant="outline" block className="mt-4">
                {finished ? "Réserver à nouveau" : "Voir le service"}
              </ButtonLink>
            </Card>
          ) : null}
        </div>
      </div>

      <ConfirmDialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        onConfirm={() => void cancel()}
        tone="danger"
        loading={busy}
        title="Annuler cette réservation ?"
        description="Une réservation annulée ne peut pas être rétablie : il faudra faire une nouvelle demande pour retrouver un créneau."
        confirmLabel="Oui, annuler"
        cancelLabel="Garder la réservation"
      />
    </>
  );
}
