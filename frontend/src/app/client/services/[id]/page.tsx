"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiErrorMessage, get, post } from "@/lib/api";
import { PAYMENT_METHODS, type PaymentMethod } from "@/lib/config";
import { Card, Badge, Button, Input } from "@/components/ui";
import type { Service } from "@/lib/types";

interface PaymentInitiation {
  payment_id: number;
  provider: string;
  provider_ref?: string;
  redirect_url?: string;
  client_secret?: string;
  status?: string;
  instructions?: string;
}

export default function ServiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [svc, setSvc] = useState<Service | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState({ booking_date: "", address: "", city: "", postal_code: "", description: "" });
  const [pay, setPay] = useState(true);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>(PAYMENT_METHODS[0].value);
  const [createdBookingId, setCreatedBookingId] = useState<number | null>(null);
  const [paymentNotice, setPaymentNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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

    const scheduledAt = new Date(form.booking_date);
    if (!form.booking_date || Number.isNaN(scheduledAt.getTime()) || scheduledAt.getTime() <= Date.now()) {
      setError("Choisissez une date et une heure futures pour la réservation.");
      return;
    }

    setError("");
    setBusy(true);
    let bookingId = createdBookingId;

    try {
      if (!bookingId) {
        const booking = await post<{ id: number }>("/bookings/", {
          service: svc.id,
          handyman: svc.handyman ?? svc.handyman_detail?.id,
          booking_date: scheduledAt.toISOString(),
          address: form.address,
          city: form.city,
          postal_code: form.postal_code || "00000",
          description: form.description,
          type: "scheduled",
          minutes: 60,
          category_id: svc.category ?? svc.category_detail?.id,
        });
        bookingId = booking.id;
        setCreatedBookingId(booking.id);
      }

      if (pay) {
        await initiatePayment(bookingId);
      } else {
        router.push(`/client/bookings/${bookingId}`);
      }
    } catch (requestError) {
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

  if (loading) return <p className="text-ash" role="status">Chargement…</p>;
  if (loadError) {
    return (
      <Card>
        <p className="text-ash" role="alert">{loadError}</p>
        <Button className="mt-4" onClick={() => void loadService()}>Réessayer</Button>
      </Card>
    );
  }
  if (!svc) return <Card><p className="text-ash">Service introuvable.</p></Card>;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        {svc.category_detail && <Badge>{svc.category_detail.name}</Badge>}
        <h2 className="mt-2 text-2xl font-bold">{svc.title}</h2>
        <p className="mt-2 text-ash">{svc.description}</p>
        <p className="mt-4 text-xl font-extrabold text-primary">
          {svc.price ? `${Number(svc.price).toLocaleString("fr-FR")} FCFA` : "Sur devis"}
        </p>
        <p className="mt-1 text-sm text-ash">
          Artisan : {svc.handyman_detail?.first_name ?? svc.handyman_detail?.username ?? "—"}
        </p>
      </Card>

      <Card>
        <h3 className="mb-3 text-lg font-bold">Réserver</h3>
        <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
          <label className="text-sm text-ash" htmlFor="booking-date">
            Date et heure
          </label>
          <Input
            id="booking-date"
            type="datetime-local"
            value={form.booking_date}
            onChange={set("booking_date")}
            required
            disabled={bookingCreated}
          />

          <label className="text-sm text-ash" htmlFor="booking-address">Adresse</label>
          <Input id="booking-address" value={form.address} onChange={set("address")} required disabled={bookingCreated} />

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm text-ash" htmlFor="booking-city">Ville</label>
              <Input id="booking-city" value={form.city} onChange={set("city")} required disabled={bookingCreated} />
            </div>
            <div>
              <label className="text-sm text-ash" htmlFor="booking-postal-code">Code postal</label>
              <Input id="booking-postal-code" value={form.postal_code} onChange={set("postal_code")} disabled={bookingCreated} />
            </div>
          </div>

          <label className="text-sm text-ash" htmlFor="booking-description">Décrivez votre besoin</label>
          <textarea
            id="booking-description"
            value={form.description}
            onChange={set("description")}
            disabled={bookingCreated}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:bg-slate-50"
            rows={3}
          />

          <label className="flex items-center gap-2 text-sm text-ash" htmlFor="pay-now">
            <input
              id="pay-now"
              type="checkbox"
              checked={pay}
              onChange={(event) => setPay(event.target.checked)}
              disabled={bookingCreated}
            />
            {paymentMethod === "cash"
              ? "Enregistrer un paiement à effectuer sur place"
              : "Régler maintenant (paiement sous séquestre)"}
          </label>

          {pay && (
            <div>
              <label className="text-sm text-ash" htmlFor="payment-method">Moyen de paiement</label>
              <select
                id="payment-method"
                value={paymentMethod}
                onChange={(event) => setPaymentMethod(event.target.value as PaymentMethod)}
                disabled={bookingCreated}
                className="mt-1 w-full rounded-xl border border-slate-200 px-4 py-2.5 outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:bg-slate-50"
              >
                {PAYMENT_METHODS.map((method) => (
                  <option key={method.value} value={method.value}>{method.label}</option>
                ))}
              </select>
            </div>
          )}

          {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
          {paymentNotice && <p className="text-sm text-emerald-700" role="status">{paymentNotice}</p>}

          {bookingCreated && (
            <Link className="text-center text-sm font-semibold text-primary underline" href={`/client/bookings/${createdBookingId}`}>
              Voir ma réservation
            </Link>
          )}

          <Button type="submit" disabled={busy || Boolean(paymentNotice)}>
            {busy
              ? "Traitement…"
              : paymentNotice
                ? "Paiement enregistré"
                : bookingCreated
                  ? "Réessayer le paiement"
                  : "Confirmer la réservation"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
