"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useParams, useRouter } from "next/navigation";
import { Clock, LocateFixed, SearchX } from "lucide-react";
import { apiErrorMessage, apiJson, get, post } from "@/lib/api";
import {
  bookingIdempotencyKey,
  discardDraft,
  duplicateBookingId,
  isNetworkFailure,
  loadDraft,
  randomHex,
  saveDraft,
  type BookingDraft,
} from "@/lib/continuity";
import { ESCROW_ENABLED, PAYMENT_METHODS, type PaymentMethod } from "@/lib/config";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  Checkbox,
  EmptyState,
  Field,
  Input,
  PageHeader,
  SelectField,
  SkeletonPage,
  TextField,
  TextareaField,
} from "@/components/ds";
import { useAuth } from "@/lib/auth";
import { formatDuration, priceLabel } from "@/lib/format";
import type { Service } from "@/lib/types";
import { TransportEstimate } from "@/components/transport/TransportEstimate";
import { listAddresses, type Address } from "@/lib/addresses";
import { changedTransportQuote, fcfa, type TransportQuote } from "@/lib/transport";
import { ArtisanLine } from "../../_components/ArtisanLine";
import { formatDateTimeLong, parseDate } from "../../_components/dates";
import { ServiceCover } from "../../_components/ServiceCover";
import { StickyActionBar } from "../../_components/StickyActionBar";
import { useReveal } from "../../_components/useReveal";
import { artisanDisplayName } from "@/lib/artisan";

interface PaymentInitiation {
  payment_id: number;
  provider: string;
  provider_ref?: string;
  redirect_url?: string;
  client_secret?: string;
  status?: string;
  instructions?: string;
}

const DATE_ERROR = "Choisissez une date et une heure futures pour la réservation.";

/** Étape numérotée du formulaire de réservation. */
function FormSection({ step, title, children }: { step: number; title: string; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <h3 className="flex items-center gap-2.5 font-display text-base font-bold text-ink">
        <span aria-hidden className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent text-xs font-extrabold text-ink">
          {step}
        </span>
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Ligne du récapitulatif : valeur renseignée, ou invitation à la renseigner. */
function RecapRow({ label, value, placeholder }: { label: string; value?: ReactNode; placeholder?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="shrink-0 text-ash">{label}</dt>
      <dd className="min-w-0 break-words text-right font-medium text-ink">
        {value || <span className="font-normal text-ash">{placeholder ?? "—"}</span>}
      </dd>
    </div>
  );
}

export default function ServiceDetailPage() {
  const { user } = useAuth();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [svc, setSvc] = useState<Service | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState({ booking_date: "", address: "", city: "", postal_code: "", description: "" });
  // Coordonnées FACULTATIVES du lieu (position de l'appareil, avec accord du navigateur) : alimentent l'heure d'arrivée du suivi.
  const [coords, setCoords] = useState<{ lat: number; lng: number; accuracy: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState("");
  // Adresses enregistrées (une différente par réservation), devis de déplacement vu par le client et avis de changement serveur.
  const [saved, setSaved] = useState<Address[]>([]);
  const [addressId, setAddressId] = useState<number | null>(null);
  const [commune, setCommune] = useState("");
  const [quote, setQuote] = useState<TransportQuote | null>(null);
  const [transportNotice, setTransportNotice] = useState("");
  const [pay, setPay] = useState(true);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>(PAYMENT_METHODS[0].value);
  const [createdBookingId, setCreatedBookingId] = useState<number | null>(null);
  const [paymentNotice, setPaymentNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dateError, setDateError] = useState("");
  // Brouillon : la saisie survit à une fermeture, un plantage ou une coupure (stockage local par compte, effacé après
  // confirmation du serveur et à la déconnexion volontaire).
  const draftBase = useRef(randomHex(12));
  const [draftRestored, setDraftRestored] = useState(false);
  const [duplicateId, setDuplicateId] = useState<number | null>(null);
  const draftReady = useRef(false);
  const dateRef = useRef<HTMLInputElement>(null);
  const feedbackRef = useRef<HTMLDivElement>(null);
  const bookingCreated = createdBookingId !== null;

  const set = (key: keyof typeof form) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((current) => ({ ...current, [key]: event.target.value }));

  const loadService = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      setSvc(await get<Service>(`/services/${id}/`));
    } catch (requestError) {
      setSvc(null);
      setLoadError(apiErrorMessage(requestError, "Le service ne peut pas être chargé pour le moment."));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void loadService();
  }, [loadService]);

  useEffect(() => {
    if (!user) return;
    listAddresses().then((r) => setSaved(r.results)).catch(() => setSaved([])); // facultatif : sans adresses enregistrées, la saisie manuelle reste possible
  }, [user]);

  // Restauration du brouillon une fois le compte et le service connus (jamais celui d'un autre compte).
  useEffect(() => {
    if (!user || !svc || draftReady.current) return;
    draftReady.current = true;
    const d = loadDraft(user.id, svc.id);
    if (!d) return;
    draftBase.current = d.base;
    setForm({ booking_date: d.booking_date, address: d.address, city: d.city, postal_code: d.postal_code, description: d.description });
    setDraftRestored(true);
  }, [user, svc]);

  const currentDraft = useCallback(
    (): BookingDraft => ({ base: draftBase.current, ...form, updated_at: new Date().toISOString() }),
    [form],
  );

  useEffect(() => {
    if (!user || !svc || !draftReady.current || createdBookingId !== null) return;
    const timer = setTimeout(() => saveDraft(user.id, svc.id, currentDraft()), 600);
    return () => clearTimeout(timer);
  }, [user, svc, form, createdBookingId, currentDraft]);

  // Le retour d'une action (erreur, paiement enregistré) doit rester visible même quand le bouton est collé en bas d'écran.
  useReveal(feedbackRef, error || paymentNotice);

  async function initiatePayment(bookingId: number) {
    if (!svc) return;

    const payment = await post<PaymentInitiation>("/payments/initiate/", {
      booking_id: bookingId,
      method: paymentMethod,
      minutes: 60,
      category_id: svc.category ?? svc.category_detail?.id,
    });

    if (!payment.payment_id) {
      throw new Error("Réponse de paiement incomplète");
    }

    if (payment.redirect_url) {
      const destination = new URL(payment.redirect_url, window.location.origin);
      const secureProtocol = destination.protocol === "https:" || destination.protocol === "http:";
      if (!secureProtocol || (process.env.NODE_ENV === "production" && destination.protocol !== "https:")) {
        throw new Error("URL de paiement non sûre");
      }
      window.location.assign(destination.toString());
      return;
    }

    // Un client_secret requiert l'intégration explicite du SDK du prestataire.
    // Ne pas l'interpréter comme une confirmation : seul le webhook serveur peut
    // placer les fonds sous séquestre.
    setPaymentNotice(
      payment.instructions ??
        "Votre réservation est enregistrée et la demande de paiement a été créée. " +
          "Le paiement reste en attente de confirmation par le prestataire.",
    );
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!svc || paymentNotice) return;

    setDateError("");
    const scheduledAt = new Date(form.booking_date);
    if (!form.booking_date || Number.isNaN(scheduledAt.getTime()) || scheduledAt.getTime() <= Date.now()) {
      // Le champ date est verrouillé une fois la réservation créée : le message passe alors dans le bandeau d'erreur.
      if (bookingCreated) {
        setError(DATE_ERROR);
      } else {
        setError("");
        setDateError(DATE_ERROR);
        dateRef.current?.focus();
      }
      return;
    }

    setError("");
    setBusy(true);
    let bookingId = createdBookingId;

    try {
      if (!bookingId) {
        // Le brouillon (et donc la clé) est écrit AVANT l'envoi : un plantage pendant la requête ne perd rien, et le
        // renvoi retrouve la même réservation si le serveur l'avait déjà créée.
        const draft = currentDraft();
        if (user) saveDraft(user.id, svc.id, draft);
        const booking = await apiJson<{ id: number }>("/bookings/", {
          method: "POST",
          headers: { "Idempotency-Key": bookingIdempotencyKey(svc.id, draft) },
          body: JSON.stringify({
            service: svc.id,
            handyman: svc.handyman ?? svc.handyman_detail?.id,
            booking_date: scheduledAt.toISOString(),
            address: form.address,
            city: form.city,
            postal_code: form.postal_code || "00000",
            description: form.description,
            type: "scheduled",
            ...(coords ? { lat: coords.lat, lng: coords.lng } : {}),
            ...(commune ? { commune } : {}),
            ...(quote ? { expected_transport_fee: quote.amount } : {}),
            minutes: 60,
            category_id: svc.category ?? svc.category_detail?.id,
          }),
        });
        bookingId = booking.id;
        setCreatedBookingId(booking.id);
        if (user) discardDraft(user.id, svc.id); // confirmée par le serveur : le brouillon n'a plus lieu d'être
      }

      if (pay) {
        await initiatePayment(bookingId);
      } else {
        router.push(`/dashboard/bookings/${bookingId}`);
      }
    } catch (requestError) {
      const changed = changedTransportQuote(requestError);
      if (changed && !bookingId) {
        // Le serveur a recalculé un autre montant : rien n'est réservé, le client confirme le nouveau montant.
        setQuote(changed);
        setTransportNotice(`Les frais de déplacement ont changé : ${fcfa(changed.amount)}. Vérifiez puis confirmez à nouveau.`);
        return;
      }
      const existing = duplicateBookingId(requestError);
      if (existing !== null && !bookingId) {
        // Doublon (double clic, renvoi) : la réservation existe déjà, on la montre au lieu d'en créer une autre.
        setDuplicateId(existing);
        if (user && svc) discardDraft(user.id, svc.id);
        return;
      }
      if (!bookingId && isNetworkFailure(requestError)) {
        // Rien n'est confirmé : jamais présentée comme réussie ; le brouillon reste.
        setError("Réservation non envoyée : connexion indisponible. Votre saisie est conservée, vous pourrez réessayer.");
        return;
      }
      const message = apiErrorMessage(requestError, "La réservation n'a pas pu être finalisée.");
      setError(
        bookingId
          ? `Votre réservation #${bookingId} est enregistrée, mais le paiement n'a pas été initié. ${message}`
          : message,
      );
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <SkeletonPage />;

  if (loadError) {
    return (
      <>
        <PageHeader title="Service indisponible" back={{ href: "/dashboard/services", label: "Retour aux services" }} />
        <Alert
          tone="danger"
          title="Chargement impossible"
          action={
            <Button size="sm" variant="outline" onClick={() => void loadService()}>
              Réessayer
            </Button>
          }
        >
          {loadError}
        </Alert>
      </>
    );
  }

  if (!svc) {
    return (
      <>
        <PageHeader title="Service introuvable" back={{ href: "/dashboard/services", label: "Retour aux services" }} />
        <EmptyState
          icon={<SearchX aria-hidden />}
          title="Ce service n’existe pas ou n’est plus proposé"
          description="Parcourez le catalogue pour trouver un autre service."
          actions={<ButtonLink href="/dashboard/services">Voir les services</ButtonLink>}
        />
      </>
    );
  }

  const isOwnService = Boolean(user && svc.handyman && svc.handyman === user.id);
  const duration = formatDuration(svc.duration);
  const price = priceLabel(svc);
  const artisanName = artisanDisplayName(svc);
  const methodLabel = PAYMENT_METHODS.find((method) => method.value === paymentMethod)?.label;
  const escrowApplies = ESCROW_ENABLED && paymentMethod !== "cash";
  const scheduledLabel = parseDate(form.booking_date) ? formatDateTimeLong(form.booking_date) : null;
  const place = [form.address.trim(), form.city.trim()].filter(Boolean).join(", ");
  const submitLabel = busy
    ? "Traitement…"
    : paymentNotice
      ? "Paiement enregistré"
      : bookingCreated
        ? "Réessayer le paiement"
        : "Confirmer la réservation";

  return (
    <>
      <PageHeader
        eyebrow={svc.category_detail?.name}
        title={svc.title}
        back={{ href: "/dashboard/services", label: "Retour aux services" }}
      />

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-5">
        <Card padding="none" className="overflow-hidden lg:col-span-3">
          <div className="relative">
            <ServiceCover
              service={svc}
              alt={svc.images?.find((image) => image.image)?.alt_text || svc.title}
              className="aspect-[16/9]"
            />
            {svc.category_detail ? (
              <Badge tone="primary" className="absolute left-4 top-4 shadow-hair">
                {svc.category_detail.name}
              </Badge>
            ) : null}
          </div>

          <div className="space-y-6 p-5 sm:p-6">
            <div className="flex flex-wrap gap-3">
              <div className="min-w-[10rem] flex-1 rounded-panel bg-primarySoft/60 p-4">
                <p className="text-eyebrow uppercase text-ash">Tarif</p>
                <p className="mt-1.5 font-display text-2xl font-extrabold leading-none text-primaryDark">{price}</p>
              </div>
              {duration ? (
                <div className="min-w-[10rem] flex-1 rounded-panel bg-canvas p-4">
                  <p className="text-eyebrow uppercase text-ash">Durée</p>
                  <p className="mt-1.5 flex items-center gap-2 font-display text-2xl font-extrabold leading-none text-ink">
                    <Clock aria-hidden className="h-5 w-5 text-primary" />
                    {duration}
                  </p>
                </div>
              ) : null}
            </div>

            {svc.description ? (
              <div>
                <h2 className="font-display text-lg font-bold text-ink">Description</h2>
                <p className="mt-2 whitespace-pre-line text-body text-inkSoft">{svc.description}</p>
              </div>
            ) : null}

            <div className="border-t border-lineSoft pt-5">
              <h2 className="mb-3 text-eyebrow uppercase text-ash">Votre artisan</h2>
              {artisanName ? (
                <ArtisanLine service={svc} size={48} />
              ) : (
                <p className="text-sm text-ash">Artisan non renseigné.</p>
              )}
            </div>
          </div>
        </Card>

        {isOwnService ? (
          <Card className="lg:col-span-2">
            <Alert tone="info" title="C’est votre prestation">
              Vous ne pouvez pas réserver votre propre service. Gérez-le depuis vos prestations.
            </Alert>
            <ButtonLink href="/dashboard/provider" variant="outline" block className="mt-4">
              Gérer mes prestations
            </ButtonLink>
          </Card>
        ) : (
        <form onSubmit={submit} noValidate aria-label="Réserver ce service" className="lg:col-span-2">
          <Card>
            <CardHeader
              title="Réserver"
              description="Indiquez quand et où l’artisan doit intervenir."
              className="!mb-6"
            />

            <div className="space-y-7">
              <FormSection step={1} title="Quand ?">
                <Field label="Date et heure" required error={dateError}>
                  {(c) => (
                    <Input
                      {...c}
                      ref={dateRef}
                      type="datetime-local"
                      value={form.booking_date}
                      onChange={(event) => {
                        setDateError("");
                        set("booking_date")(event);
                      }}
                      required
                      disabled={bookingCreated}
                    />
                  )}
                </Field>
              </FormSection>

              <FormSection step={2} title="Où ?">
                <TextField
                  label="Adresse"
                  autoComplete="street-address"
                  value={form.address}
                  onChange={set("address")}
                  required
                  disabled={bookingCreated}
                />
                {saved.length ? (
                  <div>
                    <label htmlFor="saved-address" className="mb-1 block text-sm font-semibold text-ink">Utiliser une de mes adresses</label>
                    <select
                      id="saved-address"
                      value={addressId ?? ""}
                      disabled={bookingCreated}
                      onChange={(e) => {
                        const a = saved.find((x) => x.id === Number(e.target.value));
                        setAddressId(a?.id ?? null);
                        if (a) {
                          setForm((f) => ({ ...f, address: [a.street, a.commune].filter(Boolean).join(", ") || f.address, city: a.city }));
                          setCommune(a.commune);
                          setCoords(a.latitude !== null && a.longitude !== null ? { lat: a.latitude, lng: a.longitude, accuracy: 0 } : null);
                        }
                      }}
                      className="block min-h-[44px] w-full rounded-control border border-line bg-white px-3 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
                    >
                      <option value="">Saisir une autre adresse</option>
                      {saved.map((a) => <option key={a.id} value={a.id}>{(a.label || "Adresse") + (a.is_primary ? " (principale)" : "")} — {[a.street || a.commune, a.city].filter(Boolean).join(", ")}</option>)}
                    </select>
                  </div>
                ) : null}
                <div className="space-y-1.5">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    loading={locating}
                    disabled={bookingCreated}
                    leftIcon={<LocateFixed aria-hidden className="h-4 w-4" />}
                    onClick={() => {
                      setLocateError("");
                      if (!navigator.geolocation) return setLocateError("La localisation n’est pas disponible sur cet appareil.");
                      setLocating(true);
                      navigator.geolocation.getCurrentPosition(
                        (p) => {
                          setCoords({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: Math.round(p.coords.accuracy) });
                          setLocating(false);
                        },
                        () => {
                          setLocating(false);
                          setLocateError("Position introuvable ou refusée : vous pouvez réserver sans elle.");
                        },
                        { enableHighAccuracy: true, timeout: 15000 },
                      );
                    }}
                  >
                    {coords ? "Mettre à jour ma position" : "Localiser le lieu avec ma position"}
                  </Button>
                  {coords ? (
                    <p className="text-xs text-successInk">Lieu localisé (±{coords.accuracy} m) : l’heure d’arrivée de l’artisan sera calculée.</p>
                  ) : (
                    <p className="text-xs text-ash">Facultatif : permet d’afficher l’heure d’arrivée estimée de l’artisan. Utilisez-le seulement si vous êtes sur le lieu.</p>
                  )}
                  {locateError ? <p className="text-xs text-dangerInk">{locateError}</p> : null}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <TextField
                    label="Ville"
                    autoComplete="address-level2"
                    value={form.city}
                    onChange={set("city")}
                    required
                    disabled={bookingCreated}
                  />
                  <TextField
                    label="Code postal"
                    autoComplete="postal-code"
                    optional
                    value={form.postal_code}
                    onChange={set("postal_code")}
                    disabled={bookingCreated}
                  />
                </div>
                {svc ? (
                  <TransportEstimate
                    quote={quote}
                    onQuote={setQuote}
                    notice={transportNotice}
                    input={
                      coords || addressId
                        ? {
                            service: svc.id,
                            ...(addressId ? { address_id: addressId } : coords ? { lat: coords.lat, lng: coords.lng } : {}),
                            ...(commune ? { commune } : {}),
                            city: form.city,
                            ...(form.booking_date && !Number.isNaN(new Date(form.booking_date).getTime()) ? { when: new Date(form.booking_date).toISOString() } : {}),
                          }
                        : null
                    }
                  />
                ) : null}
              </FormSection>

              <FormSection step={3} title="Votre besoin">
                <TextareaField
                  label="Décrivez votre besoin"
                  rows={3}
                  value={form.description}
                  onChange={set("description")}
                  disabled={bookingCreated}
                />
              </FormSection>

              <FormSection step={4} title="Paiement">
                <Checkbox
                  id="pay-now"
                  checked={pay}
                  onChange={(event) => setPay(event.target.checked)}
                  disabled={bookingCreated}
                  label={
                    paymentMethod === "cash"
                      ? "Enregistrer un paiement à effectuer sur place"
                      : ESCROW_ENABLED
                        ? "Régler maintenant (paiement sous séquestre)"
                        : "Régler maintenant"
                  }
                />
                {pay ? (
                  <SelectField
                    label="Moyen de paiement"
                    hint={escrowApplies ? "Les fonds sont conservés sous séquestre jusqu’à la fin de l’intervention." : undefined}
                    value={paymentMethod}
                    onChange={(event) => setPaymentMethod(event.target.value as PaymentMethod)}
                    disabled={bookingCreated}
                  >
                    {PAYMENT_METHODS.map((method) => (
                      <option key={method.value} value={method.value}>{method.label}</option>
                    ))}
                  </SelectField>
                ) : null}
              </FormSection>

              <div className="rounded-panel bg-canvas p-4">
                <h3 className="mb-3 text-eyebrow uppercase text-ash">Récapitulatif</h3>
                <dl className="space-y-2.5 text-sm">
                  <RecapRow label="Service" value={svc.title} />
                  {artisanName ? <RecapRow label="Artisan" value={artisanName} /> : null}
                  <RecapRow label="Quand" value={scheduledLabel} placeholder="À choisir" />
                  <RecapRow label="Où" value={place} placeholder="À renseigner" />
                  <RecapRow label="Tarif" value={price} />
                  <RecapRow
                    label="Paiement"
                    value={
                      pay
                        ? `${methodLabel ?? "—"}${escrowApplies ? " · séquestre" : ""}`
                        : "Aucun paiement enregistré maintenant"
                    }
                  />
                </dl>
              </div>

              <div ref={feedbackRef} className="space-y-3 empty:hidden">
                {draftRestored && !bookingCreated ? (
                  <Alert
                    tone="info"
                    onDismiss={() => setDraftRestored(false)}
                    action={
                      <button
                        type="button"
                        className="text-sm font-semibold underline"
                        onClick={() => {
                          if (user && svc) discardDraft(user.id, svc.id);
                          draftBase.current = randomHex(12);
                          setForm({ booking_date: "", address: "", city: "", postal_code: "", description: "" });
                          setDraftRestored(false);
                        }}
                      >
                        Effacer le brouillon
                      </button>
                    }
                  >
                    Votre brouillon a été retrouvé : vérifiez les informations puis envoyez votre demande.
                  </Alert>
                ) : null}
                {duplicateId !== null ? (
                  <Alert tone="info" title="Cette réservation existe déjà">
                    <ButtonLink href={`/dashboard/bookings/${duplicateId}`} variant="outline" size="sm">Voir la réservation existante</ButtonLink>
                  </Alert>
                ) : null}
                {error ? <Alert tone="danger">{error}</Alert> : null}
                {paymentNotice ? <Alert tone="success" title="Réservation enregistrée">{paymentNotice}</Alert> : null}
                {bookingCreated ? (
                  <ButtonLink href={`/dashboard/bookings/${createdBookingId}`} variant="outline" block>
                    Voir ma réservation
                  </ButtonLink>
                ) : null}
              </div>
            </div>
          </Card>

          <StickyActionBar className="lg:mt-4">
            <div className="flex items-center gap-4">
              <div className="min-w-0 flex-1 lg:hidden">
                <p className="text-eyebrow uppercase text-ash">Tarif</p>
                <p className="truncate font-display text-base font-extrabold text-primaryDark">{price}</p>
              </div>
              <Button
                type="submit"
                loading={busy}
                disabled={Boolean(paymentNotice)}
                className="shrink-0 lg:w-full lg:min-h-[52px] lg:text-base"
              >
                {submitLabel}
              </Button>
            </div>
          </StickyActionBar>
        </form>
        )}
      </div>
    </>
  );
}
