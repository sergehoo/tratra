"""Planning d'un engagement : calendrier généré à partir du contrat, congés, absences, heures supplémentaires, remplacements,
présences DÉCLARÉES par le prestataire et CONFIRMÉES par le donneur d'ordre.

Aucune position GPS n'est jamais collectée ici : la présence est une déclaration validée par l'autre partie. Chaque événement
demandé par une partie est validé (ou refusé) par l'AUTRE ; un événement de planning ne modifie jamais le contrat lui-même."""
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from engagements.dates import daterange, hours_between, parse_hhmm
from engagements.models import ContractInstallment, EngagementContract, InstallmentLine, ScheduleEvent
from engagements.rules import BOOKING_HORIZON_DAYS, SHIFT_HORIZON_DAYS
from engagements.services.common import EngagementError, conflict, counterpart, notify_role, party_of, record, require_eligible_worker
from engagements.services.installments import generate_installments, q, refresh_installment
from engagements.services.validation import Validator
from handy.eligibility import is_user_publishable
from handy.models import Booking, User

logger = logging.getLogger(__name__)

LIVE = ("accepted", "signed", "active", "suspended", "notice")
REQUESTABLE = ("leave", "absence", "overtime", "rest", "shift")
COVERING = ("leave", "absence", "rest")


def _window(contract: EngagementContract):
    return contract.start_date, contract.effective_end


def _in_suspension(contract: EngagementContract, d: date) -> bool:
    return any(w.starts_on <= d and (w.ends_on is None or d < w.ends_on) for w in contract.suspensions.all())


def covered(contract: EngagementContract, d: date) -> bool:
    """La date est-elle couverte par un congé, une absence ou un repos validé ?"""
    return contract.schedule_events.filter(kind__in=COVERING, status="approved", date__lte=d).filter(Q(end_date__gte=d) | Q(end_date__isnull=True, date=d)).exists()


# ── Génération du calendrier ────────────────────────────────────────────────────────────────────────────────────────

def generate_shifts(contract: EngagementContract, today: Optional[date] = None, horizon_days: int = SHIFT_HORIZON_DAYS) -> int:
    """Crée les interventions prévues par le planning du contrat pour les `horizon_days` à venir. IDEMPOTENT (contrainte d'unicité
    par contrat, jour et heure de début) ; ignore les suspensions, congés, absences et repos validés."""
    today = today or timezone.localdate()
    if contract.status not in LIVE or not contract.schedule:
        return 0
    start, end = max(today, contract.start_date), today + timedelta(days=horizon_days)
    if contract.effective_end:
        end = min(end, contract.effective_end)
    if end < start:
        return 0
    slots = {}
    for slot in contract.schedule:
        slots.setdefault(slot["weekday"], []).append((parse_hhmm(slot["start"]), parse_hhmm(slot["end"])))
    existing = set(contract.schedule_events.filter(source="generated", date__gte=start, date__lte=end).values_list("date", "start_time"))
    created = 0
    for d in daterange(start, end):
        for s, e in slots.get(d.weekday(), []):
            if (d, s) in existing or _in_suspension(contract, d) or covered(contract, d):
                continue
            ScheduleEvent.objects.create(contract=contract, kind="shift", date=d, start_time=s, end_time=e, hours=hours_between(s, e), status="planned", source="generated")
            created += 1
    return created


def regenerate_future_shifts(contract: EngagementContract, from_date: date, today: Optional[date] = None) -> int:
    """Après un avenant ou une suspension : les interventions GÉNÉRÉES à venir, sans présence ni réservation, sont annulées puis
    régénérées selon les nouvelles conditions. Les événements saisis à la main ne sont jamais touchés."""
    today = today or timezone.localdate()
    stale_ids = list(contract.schedule_events.filter(kind="shift", source="generated", date__gte=max(from_date, today), status="planned", attendance_status="none",
                                                     booking__isnull=True).values_list("pk", flat=True))
    # Annulées (trace conservée) et marquées « saisies » pour libérer l'unicité (jour, heure) des interventions générées.
    n = ScheduleEvent.objects.filter(pk__in=stale_ids).update(status="cancelled", source="manual", note="Remplacé après modification du contrat.")
    return n + generate_shifts(contract, today)


# ── Demandes d'événements ───────────────────────────────────────────────────────────────────────────────────────────

def _bounds_check(contract: EngagementContract, v: Validator, field: str, d: Optional[date]) -> None:
    start, end = _window(contract)
    if d and (d < start or (end and d > end)):
        v.err(field, "La date doit être comprise dans la durée du contrat.")


def _booking_cancel(event: ScheduleEvent, actor) -> None:
    booking = event.booking
    if booking is not None and booking.can_transition_to("cancelled"):
        booking.transition_to("cancelled", actor=actor)


@transaction.atomic
def request_event(contract: EngagementContract, user, data: dict, today: Optional[date] = None) -> ScheduleEvent:
    today = today or timezone.localdate()
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status not in ("active", "notice", "suspended"):
        raise conflict("contract_not_live", "Le planning n'accepte des demandes que pour un contrat en cours.")
    v = Validator()
    kind = v.choice(data, "kind", label="Nature", allowed=set(REQUESTABLE))
    d = v.date(data, "date", label="Date", required=True)
    end_d = v.date(data, "end_date", label="Date de fin")
    note = v.text(data, "note", label="Motif", max_len=500)
    hours = v.amount(data, "hours", label="Heures") if kind == "overtime" else None
    start_t = end_t = None
    if kind == "shift":
        try:
            start_t, end_t = parse_hhmm(str(data.get("start_time"))), parse_hhmm(str(data.get("end_time")))
            if end_t <= start_t:
                v.err("end_time", "La fin doit suivre le début.")
        except (ValueError, TypeError, AttributeError):
            v.err("start_time", "Heures de début et de fin : « HH:MM » attendu.")
        hours = hours_between(start_t, end_t) if start_t and end_t and end_t > start_t else None
    if kind == "overtime":
        if hours is None:
            v.err("hours", "Nombre d'heures obligatoire.")
        elif hours > Decimal("12"):
            v.err("hours", "12 heures au maximum par demande.")
    if kind in ("leave", "absence", "rest") and end_d and d and end_d < d:
        v.err("end_date", "La fin ne peut pas précéder le début.")
    if kind not in ("leave", "absence", "rest"):
        end_d = None
    v.raise_if()
    _bounds_check(contract, v, "date", d)
    if end_d:
        _bounds_check(contract, v, "end_date", end_d)
    if d < today - timedelta(days=14):
        v.err("date", "Une demande ne peut pas remonter à plus de 14 jours.")
    v.raise_if()
    if kind in COVERING and contract.schedule_events.filter(kind__in=COVERING, status__in=("requested", "approved"), date__lte=end_d or d).filter(Q(end_date__gte=d) | Q(end_date__isnull=True, date__gte=d)).exists():
        raise conflict("overlap", "Une demande de congé, d'absence ou de repos couvre déjà cette période.")
    event = ScheduleEvent.objects.create(contract=contract, kind=kind, date=d, end_date=end_d, start_time=start_t, end_time=end_t, hours=hours, status="requested",
                                         source="manual", requested_by=user, note=note)
    record(contract, user, "schedule_requested", kind=kind, date=d, event=event.pk)
    notify_role(contract, counterpart(role), "schedule_event", f"Demande de planning ({event.get_kind_display().lower()}) le {d:%d/%m/%Y} à valider.", title="Planning à valider",
                key=f"ev-{event.pk}-requested")
    return event


@transaction.atomic
def respond_event(event: ScheduleEvent, user, approve: bool, note: str = "") -> ScheduleEvent:
    event = ScheduleEvent.objects.select_for_update(of=("self",)).select_related("contract", "requested_by", "booking").get(pk=event.pk)
    contract = event.contract
    role = party_of(contract, user)
    requester_role = party_of(contract, event.requested_by) if event.requested_by_id else None
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if event.status != "requested":
        raise conflict("not_open", "Cet événement a déjà reçu une réponse.")
    if role == requester_role:
        raise EngagementError("forbidden", "C'est à l'AUTRE partie de valider cette demande.", 403)
    if event.kind == "replacement" and approve and event.replacement_status != "accepted":
        raise conflict("replacement_pending", "Le remplaçant doit d'abord accepter.")
    event.status, event.responded_by, event.responded_at = ("approved" if approve else "rejected"), user, timezone.now()
    if note:
        event.note = (event.note + " | " + note.strip())[:500] if event.note else note.strip()[:500]
    event.save()
    if approve:
        _apply_approved(event, user)
    record(contract, user, "schedule_approved" if approve else "schedule_rejected", kind=event.kind, date=event.date, event=event.pk)
    if event.requested_by_id:
        notify_role(contract, requester_role or "worker", "schedule_event", f"Votre demande de planning du {event.date:%d/%m/%Y} est {'validée' if approve else 'refusée'}.",
                    title="Planning " + ("validé" if approve else "refusé"), key=f"ev-{event.pk}-{'ok' if approve else 'ko'}")
    return event


def _apply_approved(event: ScheduleEvent, actor) -> None:
    contract = event.contract
    if event.kind in COVERING:
        last = event.end_date or event.date
        for shift in contract.schedule_events.filter(kind="shift", date__gte=event.date, date__lte=last).exclude(status__in=("cancelled", "replaced")).select_related("booking"):
            shift.status, shift.note = "cancelled", f"Couvert par : {event.get_kind_display().lower()}."
            shift.save(update_fields=["status", "note", "updated_at"])
            _booking_cancel(shift, actor)
    elif event.kind == "overtime":
        _overtime_line(event, actor)
    elif event.kind == "replacement" and event.replaces_id:
        original = event.replaces
        original.status = "replaced"
        original.save(update_fields=["status", "updated_at"])
        _booking_cancel(original, actor)


def _overtime_line(event: ScheduleEvent, actor) -> None:
    """Heures supplémentaires validées par les DEUX parties : une ligne d'ajustement acceptée est ajoutée à l'échéance de la période,
    uniquement si le contrat fixe un taux horaire (jamais de taux légal supposé)."""
    contract = event.contract
    if not contract.overtime_hourly_rate or not event.hours:
        return
    generate_installments(contract)
    inst = contract.installments.filter(period_start__lte=event.date, period_end__gte=event.date).exclude(status__in=("waived", "cancelled", "paid")).first()
    if inst is None:
        return
    amount = q(event.hours * contract.overtime_hourly_rate)
    InstallmentLine.objects.get_or_create(source_event=event, defaults=dict(installment=inst, kind="overtime", amount=amount, description=f"Heures supplémentaires du {event.date:%d/%m/%Y} ({event.hours} h)",
                                                                            proposed_by=event.requested_by or actor, status="accepted", responded_by=actor, responded_at=timezone.now()))
    refresh_installment(inst)


@transaction.atomic
def cancel_event(event: ScheduleEvent, user) -> ScheduleEvent:
    event = ScheduleEvent.objects.select_for_update(of=("self",)).select_related("contract").get(pk=event.pk)
    if event.requested_by_id != user.id:
        raise EngagementError("forbidden", "Seul l'auteur de la demande peut l'annuler.", 403)
    if event.status != "requested":
        raise conflict("not_open", "Cette demande ne peut plus être annulée.")
    event.status = "cancelled"
    event.save(update_fields=["status", "updated_at"])
    record(event.contract, user, "schedule_cancelled", kind=event.kind, date=event.date, event=event.pk)
    return event


# ── Présences ───────────────────────────────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def declare_attendance(event: ScheduleEvent, user, data: dict, today: Optional[date] = None) -> ScheduleEvent:
    """Le prestataire (ou son remplaçant) DÉCLARE sa présence ; sans position GPS ; le donneur d'ordre la confirme."""
    today = today or timezone.localdate()
    event = ScheduleEvent.objects.select_for_update(of=("self",)).select_related("contract").get(pk=event.pk)
    contract = event.contract
    actor_ok = (event.kind == "shift" and contract.worker_id == user.id) or (event.kind == "replacement" and event.replacement_worker_id == user.id)
    if not actor_ok:
        raise EngagementError("forbidden" if party_of(contract, user) else "not_found", "Seul le prestataire concerné déclare sa présence.", 403 if party_of(contract, user) else 404)
    if event.status not in ("planned", "approved") or event.attendance_status == "confirmed":
        raise conflict("not_open", "La présence de cet événement ne peut plus être déclarée.")
    if event.date > today:
        raise conflict("future_event", "On ne peut pas déclarer une présence à venir.")
    v = Validator()
    start = end = None
    if data.get("actual_start") or data.get("actual_end"):
        try:
            start, end = parse_hhmm(str(data.get("actual_start"))), parse_hhmm(str(data.get("actual_end")))
            if end <= start:
                v.err("actual_end", "La fin doit suivre le début.")
        except (ValueError, TypeError, AttributeError):
            v.err("actual_start", "Heures réelles : « HH:MM » attendu pour le début ET la fin.")
    v.raise_if()
    event.actual_start, event.actual_end = start, end
    event.hours = hours_between(start, end) if start and end else (event.hours or (hours_between(event.start_time, event.end_time) if event.start_time and event.end_time else None))
    event.attendance_status, event.declared_at = "declared", timezone.now()
    event.save()
    record(contract, user, "attendance_declared", date=event.date, event=event.pk, hours=event.hours)
    notify_role(contract, "principal", "schedule_event", f"Présence du {event.date:%d/%m/%Y} déclarée : à confirmer.", title="Présence à confirmer", key=f"ev-{event.pk}-attendance")
    return event


@transaction.atomic
def respond_attendance(event: ScheduleEvent, user, confirm: bool, note: str = "") -> ScheduleEvent:
    event = ScheduleEvent.objects.select_for_update(of=("self",)).select_related("contract").get(pk=event.pk)
    contract = event.contract
    if party_of(contract, user) != "principal":
        raise EngagementError("forbidden" if party_of(contract, user) else "not_found", "Seul le donneur d'ordre confirme une présence.", 403 if party_of(contract, user) else 404)
    if event.attendance_status != "declared":
        raise conflict("not_open", "Aucune présence en attente de confirmation.")
    note = (note or "").strip()[:500]
    if not confirm and len(note) < 5:
        raise EngagementError("invalid", "Indiquez le motif de la contestation (5 caractères au minimum).", 400, fields={"note": "Motif obligatoire."})
    event.attendance_status, event.confirmed_at = ("confirmed" if confirm else "disputed"), timezone.now()
    if note:
        event.note = (event.note + " | " + note)[:500] if event.note else note
    event.save()
    record(contract, user, "attendance_confirmed" if confirm else "attendance_disputed", date=event.date, event=event.pk)
    notify_role(contract, "worker", "schedule_event", f"Votre présence du {event.date:%d/%m/%Y} est {'confirmée' if confirm else 'contestée'}.", title="Présence " + ("confirmée" if confirm else "contestée"),
                key=f"ev-{event.pk}-attendance-{'ok' if confirm else 'ko'}")
    return event


# ── Remplacements ───────────────────────────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def propose_replacement(contract: EngagementContract, user, shift_id: int, replacement_worker_id: int, note: str = "") -> ScheduleEvent:
    contract = EngagementContract.objects.select_for_update().get(pk=contract.pk)
    role = party_of(contract, user)
    if role is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    if contract.status not in ("active", "notice"):
        raise conflict("contract_not_live", "Un remplacement n'est possible que pour un contrat en cours.")
    shift = contract.schedule_events.select_for_update().filter(pk=shift_id, kind="shift", status__in=("planned", "approved")).first()
    if shift is None:
        raise EngagementError("not_found", "Intervention introuvable ou déjà remplacée.", 404)
    if shift.date < timezone.localdate():
        raise conflict("past_event", "On ne remplace pas une intervention passée.")
    substitute = User.objects.filter(pk=replacement_worker_id, is_active=True).first()
    if substitute is None or substitute.pk in (contract.worker_id, contract.principal_id):
        raise EngagementError("invalid", "Remplaçant invalide.", 400, fields={"replacement_worker": "Choisissez un autre professionnel vérifié."})
    if not is_user_publishable(substitute):
        raise conflict("worker_not_verified", "Le remplaçant doit être un professionnel vérifié par Tratra.")
    if contract.schedule_events.filter(kind="replacement", replaces=shift, status="requested").exists():
        raise conflict("overlap", "Un remplacement est déjà en cours de validation pour cette intervention.")
    event = ScheduleEvent.objects.create(contract=contract, kind="replacement", date=shift.date, start_time=shift.start_time, end_time=shift.end_time, hours=shift.hours,
                                         status="requested", source="manual", requested_by=user, note=(note or "").strip()[:500], replaces=shift,
                                         replacement_worker=substitute, replacement_status="proposed")
    record(contract, user, "replacement_proposed", date=shift.date, event=event.pk)
    from handy.notifications import notify
    notify(substitute, "schedule_event", f"On vous propose de remplacer une intervention le {shift.date:%d/%m/%Y}.", title="Remplacement proposé",
           data={"kind": "replacements"}, dedupe_key=f"eng:{contract.pk}:ev-{event.pk}:sub")
    notify_role(contract, counterpart(role), "schedule_event", f"Remplacement proposé pour le {shift.date:%d/%m/%Y} : à valider.", title="Remplacement à valider", key=f"ev-{event.pk}-replacement")
    return event


@transaction.atomic
def respond_replacement(event: ScheduleEvent, user, accept: bool) -> ScheduleEvent:
    event = ScheduleEvent.objects.select_for_update(of=("self",)).select_related("contract").get(pk=event.pk)
    if event.kind != "replacement" or event.replacement_worker_id != user.id:
        raise EngagementError("not_found", "Introuvable.", 404)
    if event.replacement_status != "proposed" or event.status != "requested":
        raise conflict("not_open", "Cette proposition a déjà reçu une réponse.")
    if accept:
        require_eligible_worker(user)
    event.replacement_status = "accepted" if accept else "declined"
    if not accept:
        event.status = "rejected"
    event.save()
    record(event.contract, user, "replacement_accepted" if accept else "replacement_declined", date=event.date, event=event.pk)
    return event


# ── Réservations des occurrences (prestations récurrentes) ─────────────────────────────────────────────────────────

def _aware(d: date, t):
    return timezone.make_aware(datetime.combine(d, t))


def materialize_bookings(contract: EngagementContract, today: Optional[date] = None, days: int = BOOKING_HORIZON_DAYS) -> int:
    """Prestation récurrente indépendante : chaque occurrence des `days` prochains jours devient une RÉSERVATION confirmée du
    workflow existant (suivi, QR d'identité, avis, litiges). IDEMPOTENT : une occurrence ne porte qu'une réservation (OneToOne)."""
    today = today or timezone.localdate()
    if contract.bookings_mode != "per_occurrence" or contract.work_relationship != "independent" or contract.status not in ("active", "notice"):
        return 0
    events = (contract.schedule_events.filter(kind__in=("shift", "replacement"), status__in=("planned", "approved"), booking__isnull=True, start_time__isnull=False,
                                              date__gte=today, date__lte=today + timedelta(days=days)).select_related("replacement_worker"))
    made = 0
    for event in events:
        worker = event.replacement_worker if event.kind == "replacement" else contract.worker
        if worker is None or not is_user_publishable(worker) or covered(contract, event.date):
            continue
        try:
            with transaction.atomic():
                locked = ScheduleEvent.objects.select_for_update().get(pk=event.pk)
                if locked.booking_id is not None:
                    continue
                booking = Booking.objects.create(
                    client=contract.principal, handyman=worker, service=contract.service, booking_date=_aware(event.date, event.start_time),
                    end_date=_aware(event.date, event.end_time) if event.end_time else None, address=contract.location_address or "Adresse convenue au contrat",
                    city=contract.location_city or "—", postal_code="", description=f"Prestation récurrente — contrat #{contract.pk}", booking_type="scheduled")
                booking.transition_to("confirmed", actor=worker)
                locked.booking = booking
                locked.save(update_fields=["booking", "updated_at"])
                made += 1
        except Exception:  # noqa: BLE001 - une occurrence en échec ne bloque pas les suivantes
            logger.exception("Réservation de l'occurrence %s impossible", event.pk)
    return made


# ── Lecture ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def calendar(contract: EngagementContract, user, start: date, end: date):
    """Événements visibles de `user` : les parties voient tout ; un remplaçant ne voit que ses propres remplacements."""
    qs = contract.schedule_events.filter(date__lte=end).filter(Q(end_date__gte=start) | Q(end_date__isnull=True, date__gte=start))
    if party_of(contract, user) is None:
        qs = qs.filter(kind="replacement", replacement_worker=user)
    return qs.select_related("requested_by", "replacement_worker").order_by("date", "start_time", "id")
