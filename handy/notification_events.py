"""Événements métier → notifications transactionnelles automatiques.

Chaque fonction décide QUI est notifié (jamais l'auteur de l'action), de QUOI (texte, objet à ouvrir) et pose une
clé de déduplication : un événement rejoué (tâche Celery relancée, double signal) ne notifie jamais deux fois.
Aucune de ces fonctions ne lève d'exception vers l'appelant : une notification ne doit jamais bloquer une opération métier."""
import logging

from handy.notifications import notify

logger = logging.getLogger(__name__)


def _first(user, fallback: str) -> str:
    return (getattr(user, "first_name", "") or "").strip() or fallback


def _service_title(booking) -> str:
    return booking.service.title if booking.service_id and booking.service else "votre intervention"


def _safe(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # pragma: no cover - garde-fou : jamais d'erreur vers l'opération métier
            logger.exception("Notification %s non créée", fn.__name__)
    wrapper.__name__ = fn.__name__
    return wrapper


def _booking_data(booking, audience: str) -> dict:
    # « mission » = vue artisan, « booking » = vue client : le lien profond ouvre l'écran adapté au destinataire.
    return {"kind": "mission" if audience == "artisan" else "booking", "id": booking.pk, "audience": audience}


@_safe
def booking_created(booking) -> None:
    """Nouvelle demande de réservation : l'artisan est prévenu (le client est l'auteur)."""
    notify(booking.handyman_id, "booking_request",
           f"{_first(booking.client, 'Un client')} demande « {_service_title(booking)} » le {booking.booking_date:%d/%m/%Y à %H:%M}.",
           title="Nouvelle demande de réservation", data=_booking_data(booking, "artisan"),
           dedupe_key=f"booking:{booking.pk}:request", content_object=booking)


@_safe
def booking_status_changed(booking, status: str, actor_id=None) -> None:
    service, artisan, client = _service_title(booking), _first(booking.handyman, "Votre artisan"), _first(booking.client, "Le client")
    plans = {
        "confirmed": ("booking_confirmed", "Réservation confirmée",
                      f"{artisan} a accepté votre réservation « {service} ».", f"Mission confirmée : « {service} » le {booking.booking_date:%d/%m/%Y à %H:%M}."),
        "in_progress": ("booking_started", "Intervention démarrée",
                        f"{artisan} a démarré l'intervention « {service} ».", f"Intervention « {service} » démarrée."),
        "completed": ("booking_completed", "Intervention terminée",
                      f"« {service} » est terminée. Laissez un avis à {artisan}.", f"Mission « {service} » terminée."),
        "cancelled": ("booking_cancelled", "Réservation annulée",
                      f"La réservation « {service} » a été annulée.", f"{client} a annulé la réservation « {service} »."),
    }
    if status not in plans:
        return  # « pending » : couvert par booking_created ; autres statuts sans notification
    ntype, title, for_client, for_artisan = plans[status]
    for user_id, text, audience in ((booking.client_id, for_client, "client"), (booking.handyman_id, for_artisan, "artisan")):
        if actor_id is not None and user_id == actor_id:
            continue  # l'auteur de l'action n'est jamais notifié de sa propre action
        notify(user_id, ntype, text, title=title, data=_booking_data(booking, audience),
               dedupe_key=f"booking:{booking.pk}:{status}", content_object=booking)


@_safe
def review_created(review) -> None:
    booking = review.booking
    notify(booking.handyman_id, "review_received",
           f"{_first(booking.client, 'Un client')} vous a laissé un avis ({review.rating}/5).",
           title="Nouvel avis", data={"kind": "reviews"}, dedupe_key=f"review:{review.pk}:received", content_object=review)


@_safe
def review_replied(review) -> None:
    notify(review.booking.client_id, "review_reply", "L'artisan a répondu à votre avis.", title="Réponse à votre avis",
           data={"kind": "reviews"}, dedupe_key=f"review:{review.pk}:reply", content_object=review)


@_safe
def message_created(message) -> None:
    """Message reçu : les AUTRES participants sont prévenus, par conversation (le push remplace le précédent)."""
    conversation = message.conversation
    preview = (message.content or "").strip().replace("\n", " ")
    preview = preview if len(preview) <= 90 else preview[:87] + "…"
    sender = _first(message.sender, "Nouveau message")
    for user_id in conversation.participants.exclude(pk=message.sender_id).values_list("pk", flat=True):
        notify(user_id, "message_received", preview or "Nouveau message", title=sender,
               data={"kind": "conversation", "id": conversation.pk}, dedupe_key=f"message:{message.pk}",
               collapse_key=f"conversation-{conversation.pk}")


@_safe
def kyc_decided(document) -> None:
    user_id = document.handyman.user_id
    label = document.get_document_type_display()
    if document.status == "approved":
        notify(user_id, "kyc_approved", f"Votre document « {label} » a été validé par l'équipe Tratra.",
               title="Document validé", data={"kind": "kyc"}, dedupe_key=f"document:{document.pk}:approved")
    elif document.status == "rejected":
        reason = f" Motif : {document.rejection_reason}" if document.rejection_reason else ""
        notify(user_id, "kyc_rejected", f"Votre document « {label} » a été refusé.{reason}".strip(),
               title="Document refusé", data={"kind": "kyc"},
               dedupe_key=f"document:{document.pk}:rejected:{int(document.reviewed_at.timestamp()) if document.reviewed_at else 0}")


@_safe
def payment_released(payment) -> None:
    booking = payment.booking
    net = payment.amount - (payment.platform_fee or 0)
    notify(booking.handyman_id, "payment_received", f"Paiement de {net:.0f} FCFA disponible pour « {_service_title(booking)} ».",
           title="Paiement reçu", data=_booking_data(booking, "artisan"), dedupe_key=f"payment:{payment.pk}:released")


@_safe
def payment_refunded(payment) -> None:
    booking = payment.booking
    notify(booking.client_id, "refund_issued", f"{payment.refunded_amount:.0f} FCFA vous ont été remboursés pour « {_service_title(booking)} ».",
           title="Remboursement émis", data=_booking_data(booking, "client"), dedupe_key=f"payment:{payment.pk}:refunded")


@_safe
def dispute_changed(dispute, created: bool) -> None:
    booking = dispute.booking
    if created:
        other = booking.handyman_id if dispute.reporter_id == booking.client_id else booking.client_id
        audience = "artisan" if other == booking.handyman_id else "client"
        notify(other, "dispute_opened", f"Un litige a été ouvert sur « {_service_title(booking)} ». Notre équipe l'examine.",
               title="Litige ouvert", data=_booking_data(booking, audience), dedupe_key=f"dispute:{dispute.pk}:opened")
    if dispute.status in ("resolved", "rejected"):
        for user_id, audience in ((booking.client_id, "client"), (booking.handyman_id, "artisan")):
            notify(user_id, "dispute_resolved", f"Le litige sur « {_service_title(booking)} » est {'résolu' if dispute.status == 'resolved' else 'clos'}.",
                   title="Litige traité", data=_booking_data(booking, audience), dedupe_key=f"dispute:{dispute.pk}:{dispute.status}")
