"""Règlement d'un paiement par prestataire : VÉRIFIER auprès du prestataire, puis appliquer.

Principe (docs/paiements.md) : ni un webhook, ni le retour du client sur l'application, ni une action humaine ne suffit à
reconnaître un encaissement. Seul le résultat de `Provider.verify` — appel serveur-à-serveur dont le montant, la devise et la
référence concordent avec le paiement Tratra — place les fonds sous séquestre (`Payment.mark_held` refuse sinon).

Le webhook et le client ne sont que des DÉCLENCHEURS : la décision vient toujours de la vérification. Sans prestataire
configuré, ou si celui-ci ne répond pas, AUCUN état ne change (le prestataire réessaiera, la réconciliation repassera)."""
import logging
from typing import Dict, List

from django.db import transaction
from django.utils import timezone

from handy.models import Payment, PaymentLog
from handy.services.gateway import PROVIDER_METHODS, Provider, Verification, provider_for_method

logger = logging.getLogger(__name__)


def expected_reference(payment: Payment) -> str:
    """Référence que le prestataire doit rappeler : celle posée à la création (jamais une valeur fournie par l'appelant)."""
    session = payment.provider_session or {}
    return str(session.get("external_id") or session.get("tratra_ref") or payment.transaction_id or "")


def mismatches(payment: Payment, provider: Provider, v: Verification) -> List[str]:
    problems = []
    if v.amount is None or v.amount != payment.amount:
        problems.append("montant")
    if (v.currency or "").upper() != provider.currency.upper():
        problems.append("devise")
    expected = expected_reference(payment)
    if not expected or v.reference != expected:
        problems.append("référence")
    return problems


def settle(payment_id: int, *, source: str) -> Dict:
    """Vérifie le paiement auprès du prestataire puis applique le résultat. Lève `PaymentProviderUnavailable` (prestataire non
    configuré) ou `PaymentProviderError` (réponse impossible) SANS rien modifier. Rejouable : sans effet double."""
    payment = Payment.objects.get(pk=payment_id)
    if payment.method not in PROVIDER_METHODS:
        return {"state": "not_provider", "status": payment.status}
    provider = provider_for_method(payment.method)
    if not provider.is_available:
        from handy.services.gateway import PaymentProviderUnavailable
        raise PaymentProviderUnavailable(payment.method)
    verification = provider.verify(payment)                  # appel réseau : hors transaction, hors verrou
    return apply(payment_id, provider, verification, source=source)


def apply(payment_id: int, provider: Provider, v: Verification, *, source: str) -> Dict:
    with transaction.atomic():
        p = Payment.objects.select_for_update().get(pk=payment_id)
        now = timezone.now()
        p.provider_checked_at, p.provider_status = now, (v.raw_status or "")[:40]
        fields = ["provider_checked_at", "provider_status", "updated_at"]
        note = f"prov={p.method} via={source}"
        outcome = "pending"

        if v.state == "completed":
            if p.status != "pending":
                outcome = "already_settled"
            else:
                problems = mismatches(p, provider, v)
                if problems:
                    p.provider_status = "mismatch"
                    PaymentLog.objects.create(payment=p, previous_status=p.status, new_status=p.status,
                                              notes=f"Encaissement signalé mais incohérent ({', '.join(problems)}) : non reconnu. {note}")
                    logger.error("Paiement #%s : vérification incohérente (%s) — aucun encaissement reconnu.", p.pk, ", ".join(problems))
                    outcome = "mismatch"
                else:
                    p.provider_verified_at = now
                    fields.append("provider_verified_at")
                    p.save(update_fields=fields)
                    p.mark_held(note=note)
                    return {"state": "completed", "status": p.status, "verified": True}
        elif v.state == "failed":
            if p.status == "pending":
                p.save(update_fields=fields)
                p._set_status("failed", note=note)
                return {"state": "failed", "status": p.status, "verified": False}
            outcome = "already_settled"
        elif v.state == "refunded":
            if p.status in ("pending", "held", "completed"):
                p.save(update_fields=fields)
                p.refund(note=note)
                return {"state": "refunded", "status": p.status, "verified": bool(p.provider_verified_at)}
            outcome = "already_settled"
        p.save(update_fields=fields)
        return {"state": outcome, "status": p.status, "verified": bool(p.provider_verified_at)}
