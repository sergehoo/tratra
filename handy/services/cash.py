"""Paiement en ESPÈCES d'une réservation : déclaré par une partie, confirmé par l'AUTRE, historique conservé, justificatif facultatif.

Ce que cela prouve — et ne prouve pas :
  * deux personnes sont d'accord sur ce qui a été remis en main propre ; ce n'est JAMAIS un encaissement vérifié par un prestataire
    de paiement (`verification` vaut toujours « manual » ; voir docs/paiements.md) ;
  * aucun fonds ne transite par Tratra : la confirmation ne crée aucun gain retirable, ne touche pas au séquestre (`Payment`) et ne
    peut pas être posée par le Back-Office (lecture seule) ;
  * une partie ne confirme jamais sa propre déclaration ; une contestation exige un motif ; tout reste dans l'historique."""
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from handy.media.receipts import ReceiptRefused, clean_receipt
from handy.models import Booking, CashDeclaration, Payment

ZERO = Decimal("0.00")
NOTE = ("Les espèces remises en main propre ne passent pas par Tratra : une confirmation prouve l'accord des deux parties, "
        "pas un encaissement vérifié par un prestataire de paiement.")
LIVE_STATUSES = ("in_progress", "completed")      # on ne règle une prestation qu'une fois commencée


class CashError(Exception):
    """Refus métier : `code` stable pour les clients, `message` en français, statut HTTP associé."""

    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra


def q(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def role_of(booking: Booking, user) -> Optional[str]:
    if user is None or not getattr(user, "pk", None):
        return None
    if user.pk == booking.client_id:
        return "client"
    if user.pk == booking.handyman_id:
        return "artisan"
    return None


def due_amount(booking: Booking) -> Optional[Decimal]:
    """Montant convenu : celui du paiement « espèces » créé à la réservation, sinon le prix de la réservation ; None si inconnu
    (les parties confirment alors le montant saisi — c'est tout l'objet de la confirmation)."""
    payment = Payment.objects.filter(booking=booking, method="cash").first()
    for value in (payment.amount if payment else None, booking.total_price, booking.proposed_price):
        if value:
            return q(value)
    return None


def totals(booking: Booking) -> dict:
    rows = booking.cash_declarations
    confirmed = rows.filter(status="confirmed").aggregate(t=Sum("amount"))["t"] or ZERO
    waiting = rows.filter(status="declared").aggregate(t=Sum("amount"))["t"] or ZERO
    due = due_amount(booking)
    remaining = None if due is None else max(q(due - confirmed - waiting), ZERO)
    last = rows.order_by("-declared_at", "-id").first()
    if confirmed > 0 and (due is None or confirmed >= due):
        state = "paid"
    elif waiting > 0:
        state = "awaiting_confirmation"
    elif confirmed > 0:
        state = "partial"
    elif last is not None and last.status == "rejected":
        state = "contested"
    else:
        state = "none"
    return {"due": due, "confirmed": q(confirmed), "declared": q(waiting), "remaining": remaining, "state": state}


def can_declare(booking: Booking, user) -> bool:
    t = totals(booking)
    return (role_of(booking, user) is not None and booking.status in LIVE_STATUSES and t["state"] != "paid"
            and (t["remaining"] is None or t["remaining"] > 0))


@transaction.atomic
def declare(booking: Booking, user, data: dict, receipt=None, today: Optional[date] = None) -> CashDeclaration:
    """Déclare un paiement en espèces (remis ou reçu) ; il ne COMPTE qu'une fois confirmé par l'autre partie."""
    today = today or timezone.localdate()
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    role = role_of(booking, user)
    if role is None:
        raise CashError("not_found", "Introuvable.", 404)
    if booking.status not in LIVE_STATUSES:
        raise CashError("booking_not_ready", "Le paiement se déclare une fois la prestation commencée.", 409)
    t = totals(booking)
    if t["state"] == "paid":
        raise CashError("already_paid", "Cette prestation est déjà réglée.", 409)
    try:
        raw = data.get("amount")
        amount = q(raw) if raw not in (None, "") else (t["remaining"] if t["remaining"] is not None else None)
    except (InvalidOperation, ValueError, TypeError):
        raise CashError("invalid", "Montant invalide.", 400, fields={"amount": "Montant invalide."})
    if amount is None or amount <= 0:
        raise CashError("invalid", "Indiquez le montant remis en espèces.", 400, fields={"amount": "Montant obligatoire."})
    if t["remaining"] is not None and amount > t["remaining"]:
        raise CashError("invalid", "Ce montant dépasse le solde restant à régler.", 400, fields={"amount": f"Solde restant : {t['remaining']}."}, remaining=str(t["remaining"]))
    paid_raw = data.get("paid_on")
    paid_on = parse_date(str(paid_raw)) if paid_raw not in (None, "") else today
    if paid_on is None:
        raise CashError("invalid", "Date invalide.", 400, fields={"paid_on": "Date invalide."})
    if paid_on > today:
        raise CashError("invalid", "La date du paiement ne peut pas être dans le futur.", 400, fields={"paid_on": "Date dans le futur."})
    note = str(data.get("note") or "").strip()
    if len(note) > 200:
        raise CashError("invalid", "Précision trop longue (200 caractères au maximum).", 400, fields={"note": "200 caractères au maximum."})
    if booking.cash_declarations.filter(declared_by=user, amount=amount, paid_on=paid_on, status="declared").exists():
        raise CashError("duplicate", "Ce paiement a déjà été déclaré : en attente de confirmation de l'autre partie.", 409)
    try:
        cleaned = clean_receipt(receipt)
    except ReceiptRefused as exc:
        raise CashError("invalid", exc.message, 400, fields={"receipt": exc.message})
    decl = CashDeclaration.objects.create(booking=booking, amount=amount, paid_on=paid_on, note=note, declared_by=user, declared_by_role=role, receipt=cleaned)
    from handy.notification_events import cash_declared
    cash_declared(decl)
    return decl


@transaction.atomic
def respond(decl: CashDeclaration, user, confirm: bool, reason: str = "") -> CashDeclaration:
    decl = CashDeclaration.objects.select_for_update().select_related("booking", "declared_by").get(pk=decl.pk)
    booking = decl.booking
    role = role_of(booking, user)
    if role is None:
        raise CashError("not_found", "Introuvable.", 404)
    if role == decl.declared_by_role:
        raise CashError("forbidden", "Un paiement doit être confirmé par l'AUTRE partie : jamais par son auteur.", 403)
    if decl.status != "declared":
        raise CashError("not_open", "Cette déclaration a déjà reçu une réponse.", 409)
    reason = (reason or "").strip()[:500]
    if not confirm and len(reason) < 5:
        raise CashError("invalid", "Indiquez le motif de la contestation (5 caractères au minimum).", 400, fields={"reason": "Motif obligatoire."})
    decl.status, decl.responded_by, decl.responded_at = ("confirmed" if confirm else "rejected"), user, timezone.now()
    decl.rejection_reason = "" if confirm else reason
    decl.save(update_fields=["status", "responded_by", "responded_at", "rejection_reason"])
    from handy.notification_events import cash_responded
    cash_responded(decl)
    return decl


def serialize(decl: CashDeclaration, user, booking: Booking) -> dict:
    role = role_of(booking, user)
    return {
        "id": decl.pk, "amount": str(q(decl.amount)), "paid_on": decl.paid_on, "note": decl.note, "status": decl.status,
        "declared_by_role": decl.declared_by_role, "mine": decl.declared_by_id == getattr(user, "pk", None),
        "can_respond": decl.status == "declared" and role is not None and role != decl.declared_by_role,
        "rejection_reason": decl.rejection_reason, "declared_at": decl.declared_at, "responded_at": decl.responded_at,
        "receipt": {"url": f"/handy/payments/cash/{decl.pk}/receipt/"} if decl.receipt and role is not None else None,
    }


def summary(booking: Booking, user) -> dict:
    """État du règlement en espèces, vu par `user` (partie : détail et actions ; personnel : lecture seule, sans justificatifs)."""
    t = totals(booking)
    role = role_of(booking, user)
    return {
        "method": "cash", "currency": "XOF", "state": t["state"], "verification": "manual",
        "due": None if t["due"] is None else str(t["due"]), "confirmed": str(t["confirmed"]), "declared": str(t["declared"]),
        "remaining": None if t["remaining"] is None else str(t["remaining"]),
        "my_role": role, "can_declare": can_declare(booking, user), "note": NOTE,
        "history": [serialize(d, user, booking) for d in booking.cash_declarations.select_related("declared_by").order_by("declared_at", "id")],
    }
