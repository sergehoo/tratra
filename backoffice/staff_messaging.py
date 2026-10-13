"""Messagerie administrateur : écrire à un membre ou à plusieurs, chacun dans SON fil « Équipe Tratra ».

 - envoi INDIVIDUEL à chaque destinataire (un message, une conversation par membre) : aucun groupe, aucune liste de destinataires exposée ;
 - une promotion exige le consentement marketing ; un compte inactif ou personnel est ignoré (et le résultat le dit) ;
 - la préférence de notification de chaque membre est respectée par le push (`handy.notifications`) ; le message reste lisible dans l'application ;
 - idempotent : l'identifiant d'envoi d'un destinataire est dérivé du lot, un rejeu de la tâche ne duplique jamais un message."""
import logging
import uuid
from datetime import timedelta
from typing import Dict, List

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from backoffice.models import StaffMessageBatch, StaffMessageDelivery
from handy import messaging
from handy.models import MarketingConsent

logger = logging.getLogger(__name__)
User = get_user_model()
DIRECT_LIMIT = 20          # au-delà (ou avec des critères) : droit « messages.bulk »
BULK_LIMIT = 2000
BODY_MAX = 2000
NAMESPACE = uuid.UUID("6f7c9a52-2d0f-4d6b-9d3a-7a1e5f5b9a10")
FILTER_KEYS = ("type", "city", "kyc", "offers", "q", "verified", "active_days")


class StaffMessagingError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def is_bulk(selection: Dict) -> bool:
    ids = selection.get("user_ids")
    return not (isinstance(ids, list) and 0 < len(ids) <= DIRECT_LIMIT and not selection.get("filters"))


def recipients(selection: Dict):
    """Destinataires visés : soit une sélection explicite (`user_ids`), soit des critères métier AUTORISÉS (`filters`). Jamais le personnel."""
    qs = User.objects.filter(is_staff=False)
    ids = selection.get("user_ids")
    filters = selection.get("filters") or {}
    if ids and filters:
        raise StaffMessagingError("invalid_selection", "Choisissez des destinataires OU des critères, pas les deux.")
    if ids:
        try:
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            raise StaffMessagingError("invalid_selection", "Identifiants de destinataires invalides.")
        return qs.filter(pk__in=ids)
    if not filters:
        raise StaffMessagingError("invalid_selection", "Choisissez au moins un destinataire ou un critère.")
    unknown = set(filters) - set(FILTER_KEYS)
    if unknown:
        raise StaffMessagingError("invalid_filter", f"Critère non autorisé : {sorted(unknown)[0]}.")
    from backoffice.api_people import KYC_STATES, _filter_kyc_state
    from handy.models import HandymanDocument

    qs = qs.filter(is_active=True)
    kind = filters.get("type")
    if kind == "artisan":
        qs = qs.filter(handyman_profile__isnull=False)
    elif kind == "company":
        qs = qs.filter(Q(company_profile__isnull=False) | Q(business_memberships__is_active=True))
    elif kind == "client":
        qs = qs.filter(handyman_profile__isnull=True, company_profile__isnull=True)
    elif kind:
        raise StaffMessagingError("invalid_filter", "Type de membre inconnu.")
    if filters.get("city"):
        qs = qs.filter(city__iexact=str(filters["city"])[:80])
    if filters.get("kyc"):
        if filters["kyc"] not in KYC_STATES:
            raise StaffMessagingError("invalid_filter", "État KYC inconnu.")
        docs = HandymanDocument.objects.filter(handyman__user=OuterRef("pk"))
        qs = qs.annotate(kyc_pending=Exists(docs.filter(status="pending")), kyc_rejected=Exists(docs.filter(status="rejected")),
                         kyc_id_ok=Exists(docs.filter(document_type="id_card", status="approved")))
        qs = _filter_kyc_state(qs, filters["kyc"])
    if filters.get("offers") in (True, False, "true", "false"):
        has = str(filters["offers"]).lower() == "true"
        qs = qs.filter(services__isnull=not has)
    if filters.get("verified") in (True, False, "true", "false"):
        qs = qs.filter(is_verified=str(filters["verified"]).lower() == "true")
    if filters.get("active_days"):
        try:
            days = max(1, min(int(filters["active_days"]), 365))
        except (TypeError, ValueError):
            raise StaffMessagingError("invalid_filter", "Durée d'activité invalide.")
        qs = qs.filter(last_login__gte=timezone.now() - timedelta(days=days))
    q = str(filters.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q))
    return qs.distinct()


def _check_message(body: str, purpose: str) -> str:
    body = (body or "").strip()
    if not body:
        raise StaffMessagingError("empty", "Le message est vide.")
    if len(body) > BODY_MAX:
        raise StaffMessagingError("too_long", f"Message trop long : {BODY_MAX} caractères au maximum.")
    if purpose not in (StaffMessageBatch.SERVICE, StaffMessageBatch.PROMOTION):
        raise StaffMessagingError("invalid_purpose", "Nature du message inconnue.")
    return body


def _split(qs, purpose: str):
    """(à envoyer, ignorés faute de consentement, ignorés car inactifs) — calculé SANS charger les profils complets."""
    users = list(qs.only("pk", "first_name", "last_name", "is_active")[:BULK_LIMIT + 1])
    if len(users) > BULK_LIMIT:
        raise StaffMessagingError("too_many", f"Trop de destinataires : {BULK_LIMIT} au maximum par envoi. Affinez les critères.")
    inactive = [u for u in users if not u.is_active]
    live = [u for u in users if u.is_active]
    if purpose == StaffMessageBatch.PROMOTION:
        consenting = set(MarketingConsent.objects.filter(granted=True, user_id__in=[u.pk for u in live]).values_list("user_id", flat=True))
        no_consent = [u for u in live if u.pk not in consenting]
        live = [u for u in live if u.pk in consenting]
    else:
        no_consent = []
    return live, no_consent, inactive


def preview(selection: Dict, body: str, purpose: str) -> Dict:
    body = _check_message(body, purpose)
    live, no_consent, inactive = _split(recipients(selection), purpose)
    return {"body": body, "purpose": purpose, "recipient_count": len(live),
            "skipped": {"no_consent": len(no_consent), "inactive": len(inactive)},
            "sample": [messaging.display_name(u) for u in live[:5]], "bulk": is_bulk(selection),
            "note": "Chaque destinataire reçoit ce message dans sa propre conversation « Équipe Tratra » ; les destinataires ne se voient pas entre eux."}


@transaction.atomic
def create_batch(staff, selection: Dict, body: str, purpose: str) -> StaffMessageBatch:
    body = _check_message(body, purpose)
    live, no_consent, inactive = _split(recipients(selection), purpose)
    if not live and not no_consent and not inactive:
        raise StaffMessagingError("no_recipient", "Aucun destinataire ne correspond à cette sélection.", 404)
    stored = {"user_ids": selection["user_ids"]} if selection.get("user_ids") else {"filters": selection.get("filters")}
    batch = StaffMessageBatch.objects.create(sender=staff, body=body, purpose=purpose, selection=stored, recipient_count=len(live))
    rows = ([StaffMessageDelivery(batch=batch, user=u) for u in live]
            + [StaffMessageDelivery(batch=batch, user=u, status=StaffMessageDelivery.NO_CONSENT) for u in no_consent]
            + [StaffMessageDelivery(batch=batch, user=u, status=StaffMessageDelivery.UNREACHABLE) for u in inactive])
    StaffMessageDelivery.objects.bulk_create(rows)
    return batch


def enqueue(batch_id: int) -> None:
    from backoffice.tasks import deliver_batch

    try:
        deliver_batch.apply_async(args=(batch_id,), retry=False)
    except Exception:  # broker indisponible : envoi sur place (idempotent)
        logger.warning("Broker indisponible : envoi du lot #%s exécuté sur place.", batch_id, exc_info=True)
        deliver_batch(batch_id)


def deliver(batch_id: int, *, chunk: int = 200) -> Dict:
    """Envoie les messages en attente du lot. Rejouable : seuls les destinataires `pending` ou `failed` sont (re)traités, et l'identifiant
    d'envoi dérivé du lot empêche tout doublon même si le message avait déjà été créé avant une interruption."""
    batch = StaffMessageBatch.objects.filter(pk=batch_id).select_related("sender").first()
    if batch is None:
        return {"sent": 0, "failed": 0}
    if batch.status == StaffMessageBatch.QUEUED:
        StaffMessageBatch.objects.filter(pk=batch.pk, status=StaffMessageBatch.QUEUED).update(status=StaffMessageBatch.SENDING)
    sent = failed = 0
    todo = StaffMessageDelivery.objects.filter(batch=batch, status__in=(StaffMessageDelivery.PENDING, StaffMessageDelivery.FAILED),
                                               attempts__lt=3).select_related("user").order_by("pk")
    for delivery in todo.iterator(chunk_size=chunk):
        try:
            conv = messaging.support_conversation(delivery.user)
            message, _ = messaging.send(batch.sender, conv, batch.body, via_staff=True, client_id=uuid.uuid5(NAMESPACE, f"{batch.pk}:{delivery.user_id}"))
            StaffMessageDelivery.objects.filter(pk=delivery.pk).update(status=StaffMessageDelivery.SENT, message=message, error="", attempts=delivery.attempts + 1)
            sent += 1
        except Exception as exc:  # un destinataire en échec n'arrête jamais le lot
            logger.warning("Message d'équipe : échec pour le membre #%s (lot #%s)", delivery.user_id, batch.pk, exc_info=True)
            StaffMessageDelivery.objects.filter(pk=delivery.pk).update(status=StaffMessageDelivery.FAILED, error=type(exc).__name__[:160], attempts=delivery.attempts + 1)
            failed += 1
    if not StaffMessageDelivery.objects.filter(batch=batch, status__in=(StaffMessageDelivery.PENDING, StaffMessageDelivery.FAILED), attempts__lt=3).exists():
        StaffMessageBatch.objects.filter(pk=batch.pk).update(status=StaffMessageBatch.DONE, finished_at=timezone.now())
    return {"sent": sent, "failed": failed}


def results(batch: StaffMessageBatch) -> Dict:
    from django.db.models import Count

    rows = dict(StaffMessageDelivery.objects.filter(batch=batch).values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    return {s: rows.get(s, 0) for s, _ in StaffMessageDelivery.STATUSES}
