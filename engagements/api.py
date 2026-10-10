"""API des engagements, commune au web (React) et à Flutter. Toutes les routes exigent une session authentifiée ; un contrat n'existe
que pour ses parties (404 sinon) ; les écritures sensibles acceptent `Idempotency-Key` et `expected_version` (ou `If-Match`)."""
import functools
import mimetypes
import re
from datetime import timedelta

from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from continuity.idempotency import run_idempotent
from engagements import serializers as S
from engagements.models import (
    ContractAmendment, ContractInstallment, EngagementApplication, EngagementContract, EngagementEvaluation, EngagementInterview, EngagementPosting, EngagementRule,
    InstallmentLine, InstallmentPayment, ScheduleEvent,
)
from engagements.services import contracts as contract_svc
from engagements.services import disputes as dispute_svc
from engagements.services import evaluations as eval_svc
from engagements.services import installments as inst_svc
from engagements.services import overview as overview_svc
from engagements.services import planning as planning_svc
from engagements.services import postings as posting_svc
from engagements.services.common import EngagementError, contracts_for, managed_org_ids, party_of
from engagements.services.experience import experience_for
from handy.eligibility import is_user_publishable

TAG = "Engagements"


# ── Socle ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def error_response(exc: EngagementError) -> Response:
    return Response({"code": exc.code, "detail": exc.message, **exc.extra}, status=exc.status)


def endpoint(methods, summary, *, idempotent=None, files=False):
    """Vue de fonction authentifiée : refus métier → JSON `{code, detail, ...}` ; `Idempotency-Key` honorée sur les POST."""
    def decorate(fn):
        @functools.wraps(fn)
        def inner(request, *args, **kwargs):
            def call():
                try:
                    return fn(request, *args, **kwargs)
                except EngagementError as exc:
                    return error_response(exc)
            if idempotent and request.method == "POST":
                return run_idempotent(request, f"engagements.{idempotent}", call)
            return call()
        view = permission_classes([permissions.IsAuthenticated])(inner)
        if files:
            view = parser_classes([MultiPartParser, FormParser, JSONParser])(view)
        return extend_schema(tags=[TAG], summary=summary)(api_view(methods)(view))
    return decorate


def expected_version(request):
    raw = request.data.get("expected_version") if hasattr(request.data, "get") else None
    raw = raw if raw not in (None, "") else re.sub(r'^(W/)?"?|"?$', "", request.headers.get("If-Match", ""))
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        raise EngagementError("invalid", "`expected_version` invalide.", 400)


def page(request, qs, render, *, default=20, maximum=50):
    try:
        limit = max(1, min(int(request.query_params.get("limit", default)), maximum))
        offset = max(0, int(request.query_params.get("offset", 0)))
    except ValueError:
        raise EngagementError("invalid", "Pagination invalide.", 400)
    total = qs.count()
    rows = list(qs[offset:offset + limit])
    return Response({"count": total, "limit": limit, "offset": offset, "next_offset": offset + limit if offset + limit < total else None, "results": [render(r) for r in rows]})


def contract_or_404(request, pk) -> EngagementContract:
    c = (contracts_for(request.user).filter(pk=pk).select_related("category", "worker", "principal", "organization", "notice_given_by").first())
    if c is None:
        raise EngagementError("not_found", "Contrat introuvable.", 404)
    return c


def posting_or_404(request, pk, *, owner_only=False) -> EngagementPosting:
    p = EngagementPosting.objects.select_related("category", "publisher", "organization").filter(pk=pk).first()
    if p is None:
        raise EngagementError("not_found", "Besoin introuvable.", 404)
    if posting_svc.posting_side(p, request.user):
        return p
    if owner_only or not (p.status == "open" or p.applications.filter(applicant=request.user).exists()):
        raise EngagementError("not_found", "Besoin introuvable.", 404)
    return p


def sub_or_404(request, model, pk, path_to_contract, *, allow_substitute=False):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise EngagementError("not_found", "Introuvable.", 404)
    contract = obj
    for part in path_to_contract.split("."):
        contract = getattr(contract, part) if part else contract
    if not contracts_for(request.user).filter(pk=contract.pk).exists() and not (allow_substitute and getattr(obj, "replacement_worker_id", None) == request.user.id):
        raise EngagementError("not_found", "Introuvable.", 404)
    return obj, contract


# ── Règles et tableau de bord ───────────────────────────────────────────────────────────────────────────────────────

@endpoint(["GET"], "Règles applicables (par catégorie)")
def rules(request):
    """Règles d'engagement : durée maximale, préavis minimal, plafonds. Sans `category` : règle par défaut et surcharges."""
    category = request.query_params.get("category")
    if category:
        return Response(S.rules(int(category)) if category.isdigit() else S.rules())
    custom = EngagementRule.objects.filter(is_default=False, active=True).select_related("category")
    return Response({"default": S.rules(), "categories": [{"category": {"id": r.category_id, "name": r.category.name}, **S.rules(r.category_id)} for r in custom]})


@endpoint(["GET"], "Mes engagements : compteurs et « à faire »")
def me_overview(request):
    return Response(overview_svc.overview(request.user))


@endpoint(["GET"], "Mon expérience professionnelle vérifiable")
def me_experience(request):
    return Response(experience_for(request.user))


@endpoint(["GET"], "Remplacements qui me sont proposés ou confirmés")
def me_replacements(request):
    qs = (ScheduleEvent.objects.filter(replacement_worker=request.user).exclude(replacement_status="declined").select_related("contract", "contract__category", "contract__principal", "replacement_worker")
          .order_by("-date", "-id"))
    return page(request, qs, lambda e: {**S.schedule_event(e, request.user, e.contract), "contract_title": e.contract.title, "category": e.contract.category.name,
                                        "principal": S.person(e.contract.principal), "city": e.contract.location_city})


# ── Besoins ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@endpoint(["GET", "POST"], "Besoins publiés (parcourir) / publier un besoin", idempotent="posting.create")
def postings(request):
    if request.method == "POST":
        p = posting_svc.create_posting(request.user, request.data)
        return Response(S.posting(p, request.user, detail=True), status=201)
    qs = EngagementPosting.objects.filter(status="open").select_related("category", "publisher", "organization").order_by("-published_at", "-id")
    q = request.query_params
    if q.get("category"):
        qs = qs.filter(category_id=q["category"]) if q["category"].isdigit() else qs.none()
    for field in ("mission_type", "work_relationship"):
        if q.get(field):
            qs = qs.filter(**{field: q[field]})
    if q.get("city"):
        qs = qs.filter(city__icontains=q["city"][:100])
    if q.get("q"):
        qs = qs.filter(Q(title__icontains=q["q"][:100]) | Q(description__icontains=q["q"][:100]))
    eligible = is_user_publishable(request.user)
    applied = set(EngagementApplication.objects.filter(applicant=request.user).values_list("posting_id", flat=True))

    def render(p):
        out = S.posting(p, request.user)
        out["can_apply"] = bool(eligible and not out["mine"] and p.id not in applied)
        out["applied"] = p.id in applied
        return out
    return page(request, qs, render)


@endpoint(["GET"], "Mes besoins publiés")
def postings_mine(request):
    qs = (EngagementPosting.objects.filter(Q(publisher=request.user, organization__isnull=True) | Q(organization_id__in=managed_org_ids(request.user)))
          .select_related("category", "publisher", "organization").order_by("-created_at", "-id"))
    return page(request, qs, lambda p: S.posting(p, request.user))


@endpoint(["GET", "PATCH"], "Détail / modification d'un besoin")
def posting_detail(request, pk):
    p = posting_or_404(request, pk)
    if request.method == "PATCH":
        p = posting_svc.update_posting(p, request.user, request.data, expected_version=expected_version(request))
        p.refresh_from_db()
    out = S.posting(p, request.user, detail=True)
    out["applied"] = p.applications.filter(applicant=request.user).exists()
    out["can_apply"] = bool(p.status == "open" and not out["mine"] and is_user_publishable(request.user) and not out["applied"])
    return Response(out)


@endpoint(["POST"], "Publier un besoin")
def posting_publish(request, pk):
    return Response(S.posting(posting_svc.publish(posting_or_404(request, pk, owner_only=True), request.user), request.user, detail=True))


@endpoint(["POST"], "Clore un besoin (clos ou annulé)")
def posting_close(request, pk):
    p = posting_or_404(request, pk, owner_only=True)
    return Response(S.posting(posting_svc.close_posting(p, request.user, cancel=bool(request.data.get("cancel"))), request.user, detail=True))


@endpoint(["POST"], "Postuler à un besoin", idempotent="application.create")
def posting_apply(request, pk):
    p = posting_or_404(request, pk)
    a = posting_svc.apply(p, request.user, request.data)
    return Response(S.application(a, request.user, with_applicant=False), status=201)


@endpoint(["GET"], "Candidatures reçues pour un besoin")
def posting_applications(request, pk):
    p = posting_or_404(request, pk, owner_only=True)
    qs = p.applications.select_related("posting", "applicant").prefetch_related("interviews").exclude(status="withdrawn").order_by("-created_at")
    if request.query_params.get("status"):
        qs = qs.filter(status=request.query_params["status"])
    return page(request, qs, lambda a: S.application(a, request.user, with_applicant=True))


@endpoint(["GET"], "Mes candidatures")
def applications_mine(request):
    qs = EngagementApplication.objects.filter(applicant=request.user).select_related("posting", "applicant").prefetch_related("interviews").order_by("-created_at")
    return page(request, qs, lambda a: S.application(a, request.user, with_applicant=False))


def application_or_404(request, pk, *, publisher=False):
    a = EngagementApplication.objects.select_related("posting", "applicant").filter(pk=pk).first()
    if a is None or not ((a.applicant_id == request.user.id and not publisher) or posting_svc.posting_side(a.posting, request.user)):
        raise EngagementError("not_found", "Candidature introuvable.", 404)
    return a


@endpoint(["POST"], "Décider d'une candidature (présélection, refus, choix)")
def application_decision(request, pk):
    a = application_or_404(request, pk, publisher=True)
    a = posting_svc.decide(a, request.user, str(request.data.get("decision", "")), str(request.data.get("note", "")))
    return Response(S.application(a, request.user, with_applicant=True))


@endpoint(["POST"], "Retirer ma candidature")
def application_withdraw(request, pk):
    a = posting_svc.withdraw(application_or_404(request, pk), request.user)
    return Response(S.application(a, request.user, with_applicant=False))


@endpoint(["POST"], "Proposer un entretien", idempotent="interview.create")
def application_interview(request, pk):
    a = application_or_404(request, pk)
    i = posting_svc.propose_interview(a, request.user, request.data)
    return Response(S.interview(i, request.user), status=201)


@endpoint(["POST"], "Répondre à un entretien (confirmer, refuser, annuler, terminé)")
def interview_respond(request, pk):
    i = EngagementInterview.objects.select_related("application", "application__posting", "application__applicant").filter(pk=pk).first()
    if i is None or not (i.application.applicant_id == request.user.id or posting_svc.posting_side(i.application.posting, request.user)):
        raise EngagementError("not_found", "Entretien introuvable.", 404)
    return Response(S.interview(posting_svc.respond_interview(i, request.user, str(request.data.get("op", ""))), request.user))


# ── Contrats ────────────────────────────────────────────────────────────────────────────────────────────────────────

@endpoint(["GET", "POST"], "Mes contrats / créer un brouillon de contrat", idempotent="contract.create")
def contracts(request):
    if request.method == "POST":
        c = contract_svc.create_draft(request.user, request.data)
        return Response(S.contract(contract_or_404(request, c.pk), request.user, detail=True), status=201)
    qs = contracts_for(request.user).select_related("category", "worker", "principal", "organization").order_by("-updated_at", "-id")
    q = request.query_params
    if q.get("status"):
        wanted = [s for s in q["status"].split(",") if s]
        qs = qs.filter(status__in=wanted)
    if q.get("role") == "worker":
        qs = qs.filter(worker=request.user)
    elif q.get("role") == "principal":
        qs = qs.exclude(worker=request.user)
    return page(request, qs, lambda c: S.contract(c, request.user))


@endpoint(["GET", "PATCH"], "Détail d'un contrat / modifier le brouillon")
def contract_detail(request, pk):
    c = contract_or_404(request, pk)
    if request.method == "PATCH":
        contract_svc.update_draft(c, request.user, request.data, expected_version=expected_version(request))
        c = contract_or_404(request, pk)
    return Response(S.contract(c, request.user, detail=True))


def _contract_action(request, pk, fn):
    c = contract_or_404(request, pk)
    fn(c)
    return Response(S.contract(contract_or_404(request, pk), request.user, detail=True))


@endpoint(["POST"], "Proposer le contrat à l'autre partie")
def contract_propose(request, pk):
    return _contract_action(request, pk, lambda c: contract_svc.propose(c, request.user, expected_version=expected_version(request)))


@endpoint(["POST"], "Renvoyer le contrat avec une demande de modification")
def contract_send_back(request, pk):
    return _contract_action(request, pk, lambda c: contract_svc.send_back(c, request.user, str(request.data.get("note", ""))))


@endpoint(["POST"], "Refuser / annuler le contrat avant son début")
def contract_decline(request, pk):
    return _contract_action(request, pk, lambda c: contract_svc.decline(c, request.user, str(request.data.get("reason", ""))))


@endpoint(["POST"], "Accepter les conditions (empreinte exacte exigée)", idempotent="contract.accept")
def contract_accept(request, pk):
    return _contract_action(request, pk, lambda c: contract_svc.accept(c, request.user, str(request.data.get("terms_hash", ""))))


@endpoint(["POST"], "Reprendre un contrat suspendu d'un commun accord")
def contract_resume(request, pk):
    return _contract_action(request, pk, lambda c: contract_svc.resume(c, request.user))


@endpoint(["POST"], "Donner un préavis", idempotent="contract.notice")
def contract_notice(request, pk):
    return _contract_action(request, pk, lambda c: contract_svc.give_notice(c, request.user, request.data, expected_version=expected_version(request)))


@endpoint(["POST"], "Refuser le renouvellement automatique")
def contract_non_renewal(request, pk):
    return _contract_action(request, pk, lambda c: contract_svc.declare_non_renewal(c, request.user))


@endpoint(["POST"], "Clôturer un contrat terminé (plus aucun solde dû)")
def contract_close(request, pk):
    return _contract_action(request, pk, lambda c: contract_svc.close(c, request.user))


@endpoint(["GET"], "Historique des événements d'un contrat")
def contract_history(request, pk):
    c = contract_or_404(request, pk)
    return page(request, c.events.select_related("actor").order_by("-created_at", "-id"), S.event, default=50, maximum=200)


@endpoint(["GET"], "Document du contrat : conditions, acceptations, avenants")
def contract_document(request, pk):
    c = contract_or_404(request, pk)
    return Response({"contract": S.contract(c, request.user, detail=True), "terms": contract_svc.snapshot(c), "terms_hash": c.terms_hash, "terms_version": c.terms_version,
                     "acceptances": [{"role": a.role, "user": S.person(a.user), "terms_version": a.terms_version, "terms_hash": a.terms_hash, "accepted_at": a.accepted_at}
                                     for a in c.acceptances.select_related("user").order_by("terms_version", "accepted_at")],
                     "amendments": [S.amendment(a, request.user, c) for a in c.amendments.select_related("proposed_by").order_by("created_at")],
                     "notice": "Acceptation électronique simple enregistrée par Tratra (qui, quand, empreinte des conditions) : elle ne constitue pas une signature qualifiée."})


@endpoint(["GET", "POST"], "Avenants d'un contrat / proposer un avenant", idempotent="amendment.create")
def contract_amendments(request, pk):
    c = contract_or_404(request, pk)
    if request.method == "POST":
        a = contract_svc.propose_amendment(c, request.user, request.data, expected_version=expected_version(request))
        return Response(S.amendment(a, request.user, c), status=201)
    return Response({"results": [S.amendment(a, request.user, c) for a in c.amendments.select_related("proposed_by").order_by("-created_at")]})


def _amendment_or_404(request, pk):
    a = ContractAmendment.objects.select_related("contract", "proposed_by").filter(pk=pk).first()
    if a is None or not contracts_for(request.user).filter(pk=a.contract_id).exists():
        raise EngagementError("not_found", "Avenant introuvable.", 404)
    return a


@endpoint(["POST"], "Accepter ou refuser un avenant")
def amendment_respond(request, pk):
    a = _amendment_or_404(request, pk)
    accept = request.data.get("accept")
    if not isinstance(accept, bool):
        raise EngagementError("invalid", "`accept` doit être vrai ou faux.", 400, fields={"accept": "Booléen attendu."})
    a = contract_svc.respond_amendment(a, request.user, accept)
    return Response(S.amendment(ContractAmendment.objects.get(pk=a.pk), request.user, a.contract))


@endpoint(["POST"], "Retirer un avenant proposé")
def amendment_withdraw(request, pk):
    a = contract_svc.withdraw_amendment(_amendment_or_404(request, pk), request.user)
    return Response(S.amendment(a, request.user, a.contract))


# ── Échéances, ajustements, paiements ───────────────────────────────────────────────────────────────────────────────

def _inst_list(request, c, qs):
    qs = qs.prefetch_related("lines", "payments").select_related("contract")
    return Response({"count": len(qs), "results": [S.installment(i, request.user) for i in qs]})


@endpoint(["GET"], "Échéances d'un contrat")
def contract_installments(request, pk):
    c = contract_or_404(request, pk)
    qs = c.installments.order_by("sequence")
    if request.query_params.get("status"):
        qs = qs.filter(status__in=request.query_params["status"].split(","))
    return _inst_list(request, c, qs)


def installment_or_404(request, pk):
    inst, _ = sub_or_404(request, ContractInstallment, pk, "contract")
    return ContractInstallment.objects.select_related("contract", "contract__worker", "contract__principal").get(pk=inst.pk)


@endpoint(["GET"], "Détail d'une échéance (ajustements, paiements)")
def installment_detail(request, pk):
    return Response(S.installment(installment_or_404(request, pk), request.user, detail=True))


@endpoint(["POST"], "Proposer un ajustement (prime, frais, retenue, correction)", idempotent="line.create", files=True)
def installment_lines(request, pk):
    inst = installment_or_404(request, pk)
    line = inst_svc.propose_line(inst, request.user, request.data, request.FILES.get("evidence"))
    return Response(S.line(line, request.user, inst.contract), status=201)


@endpoint(["POST"], "Accepter ou refuser un ajustement")
def line_respond(request, pk):
    line, contract = sub_or_404(request, InstallmentLine, pk, "installment.contract")
    accept = request.data.get("accept")
    if not isinstance(accept, bool):
        raise EngagementError("invalid", "`accept` doit être vrai ou faux.", 400, fields={"accept": "Booléen attendu."})
    line = inst_svc.respond_line(line, request.user, accept)
    return Response(S.line(InstallmentLine.objects.get(pk=line.pk), request.user, contract))


@endpoint(["POST"], "Déclarer un paiement (confirmé ensuite par l'autre partie)", idempotent="payment.create", files=True)
def installment_payments(request, pk):
    inst = installment_or_404(request, pk)
    p = inst_svc.declare_payment(inst, request.user, request.data, request.FILES.get("evidence"))
    return Response(S.payment(p, request.user, inst.contract), status=201)


@endpoint(["POST"], "Confirmer ou contester un paiement déclaré par l'autre partie")
def payment_respond(request, pk):
    pay, contract = sub_or_404(request, InstallmentPayment, pk, "installment.contract")
    confirm = request.data.get("confirm")
    if not isinstance(confirm, bool):
        raise EngagementError("invalid", "`confirm` doit être vrai ou faux.", 400, fields={"confirm": "Booléen attendu."})
    pay = inst_svc.respond_payment(pay, request.user, confirm, str(request.data.get("reason", "")))
    return Response(S.payment(InstallmentPayment.objects.get(pk=pay.pk), request.user, contract))


@endpoint(["POST"], "Abandonner le solde d'une échéance (prestataire uniquement)")
def installment_waive(request, pk):
    inst = inst_svc.waive(installment_or_404(request, pk), request.user, str(request.data.get("reason", "")))
    return Response(S.installment(ContractInstallment.objects.select_related("contract").get(pk=inst.pk), request.user, detail=True))


@endpoint(["GET"], "Pièce justificative privée (parties uniquement)")
def evidence(request, kind, pk):
    if kind == "payment":
        obj, _ = sub_or_404(request, InstallmentPayment, pk, "installment.contract")
    elif kind == "line":
        obj, _ = sub_or_404(request, InstallmentLine, pk, "installment.contract")
    else:
        raise EngagementError("not_found", "Introuvable.", 404)
    if not obj.evidence:
        raise EngagementError("not_found", "Aucune pièce jointe.", 404)
    response = FileResponse(obj.evidence.open("rb"), content_type=mimetypes.guess_type(obj.evidence.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


# ── Planning ────────────────────────────────────────────────────────────────────────────────────────────────────────

@endpoint(["GET"], "Calendrier d'un contrat (parties ; aucun suivi de position)")
def contract_calendar(request, pk):
    c = contract_or_404(request, pk)
    today = timezone.localdate()
    start = parse_date(request.query_params.get("start", "")) or today - timedelta(days=7)
    end = parse_date(request.query_params.get("end", "")) or today + timedelta(days=45)
    if end < start or (end - start).days > 186:
        raise EngagementError("invalid", "Période invalide (186 jours au maximum).", 400, fields={"end": "Période trop longue ou inversée."})
    return Response({"start": start, "end": end, "events": [S.schedule_event(e, request.user, c) for e in planning_svc.calendar(c, request.user, start, end)]})


@endpoint(["POST"], "Demander un événement de planning (congé, absence, repos, heures supplémentaires)", idempotent="event.create")
def contract_events(request, pk):
    c = contract_or_404(request, pk)
    return Response(S.schedule_event(planning_svc.request_event(c, request.user, request.data), request.user, c), status=201)


def event_or_404(request, pk, *, allow_substitute=False):
    e, c = sub_or_404(request, ScheduleEvent, pk, "contract", allow_substitute=allow_substitute)
    return ScheduleEvent.objects.select_related("contract", "requested_by", "replacement_worker").get(pk=e.pk), c


@endpoint(["POST"], "Valider ou refuser une demande de planning")
def event_respond(request, pk):
    e, c = event_or_404(request, pk)
    approve = request.data.get("approve")
    if not isinstance(approve, bool):
        raise EngagementError("invalid", "`approve` doit être vrai ou faux.", 400, fields={"approve": "Booléen attendu."})
    return Response(S.schedule_event(planning_svc.respond_event(e, request.user, approve, str(request.data.get("note", ""))), request.user, c))


@endpoint(["POST"], "Annuler ma demande de planning")
def event_cancel(request, pk):
    e, c = event_or_404(request, pk)
    return Response(S.schedule_event(planning_svc.cancel_event(e, request.user), request.user, c))


@endpoint(["POST"], "Déclarer ma présence (sans position GPS)", idempotent="attendance.declare")
def event_attendance(request, pk):
    e, c = event_or_404(request, pk, allow_substitute=True)
    return Response(S.schedule_event(planning_svc.declare_attendance(e, request.user, request.data), request.user, c))


@endpoint(["POST"], "Confirmer ou contester une présence déclarée")
def event_attendance_respond(request, pk):
    e, c = event_or_404(request, pk)
    confirm = request.data.get("confirm")
    if not isinstance(confirm, bool):
        raise EngagementError("invalid", "`confirm` doit être vrai ou faux.", 400, fields={"confirm": "Booléen attendu."})
    return Response(S.schedule_event(planning_svc.respond_attendance(e, request.user, confirm, str(request.data.get("note", ""))), request.user, c))


@endpoint(["POST"], "Proposer un remplaçant temporaire", idempotent="replacement.create")
def contract_replacements(request, pk):
    c = contract_or_404(request, pk)
    try:
        shift, worker = int(request.data.get("shift")), int(request.data.get("replacement_worker"))
    except (TypeError, ValueError):
        raise EngagementError("invalid", "Intervention et remplaçant obligatoires.", 400, fields={"shift": "Obligatoire.", "replacement_worker": "Obligatoire."})
    e = planning_svc.propose_replacement(c, request.user, shift, worker, str(request.data.get("note", "")))
    return Response(S.schedule_event(e, request.user, c), status=201)


@endpoint(["POST"], "Accepter ou refuser un remplacement proposé")
def replacement_respond(request, pk):
    e, c = event_or_404(request, pk, allow_substitute=True)
    accept = request.data.get("accept")
    if not isinstance(accept, bool):
        raise EngagementError("invalid", "`accept` doit être vrai ou faux.", 400, fields={"accept": "Booléen attendu."})
    return Response(S.schedule_event(planning_svc.respond_replacement(e, request.user, accept), request.user, c))


# ── Évaluations et litiges ──────────────────────────────────────────────────────────────────────────────────────────

@endpoint(["GET", "POST"], "Évaluations d'un contrat / évaluer l'autre partie", idempotent="evaluation.create")
def contract_evaluations(request, pk):
    c = contract_or_404(request, pk)
    if request.method == "POST":
        return Response(S.evaluation(eval_svc.create(c, request.user, request.data), request.user), status=201)
    qs = c.evaluations.filter(Q(is_hidden=False) | Q(author=request.user)).select_related("author", "subject").order_by("-created_at")
    return Response({"results": [S.evaluation(e, request.user) for e in qs]})


def _evaluation_or_404(request, pk):
    ev = EngagementEvaluation.objects.select_related("contract", "author", "subject").filter(pk=pk).first()
    if ev is None or not contracts_for(request.user).filter(pk=ev.contract_id).exists():
        raise EngagementError("not_found", "Évaluation introuvable.", 404)
    return ev


@endpoint(["PATCH"], "Modifier mon évaluation (délai limité)")
def evaluation_update(request, pk):
    return Response(S.evaluation(eval_svc.update(_evaluation_or_404(request, pk), request.user, request.data), request.user))


@endpoint(["POST"], "Répondre à une évaluation reçue (une seule fois)")
def evaluation_reply(request, pk):
    return Response(S.evaluation(eval_svc.reply(_evaluation_or_404(request, pk), request.user, str(request.data.get("reply", ""))), request.user))


@endpoint(["POST"], "Signaler une évaluation")
def evaluation_report(request, pk):
    eval_svc.report(_evaluation_or_404(request, pk), request.user, str(request.data.get("reason", "")))
    return Response({"reported": True}, status=201)


@endpoint(["GET", "POST"], "Litiges d'un contrat / ouvrir un litige", idempotent="dispute.create")
def contract_disputes(request, pk):
    c = contract_or_404(request, pk)
    if request.method == "POST":
        return Response(S.dispute(dispute_svc.open_dispute(c, request.user, request.data), request.user), status=201)
    return Response({"results": [S.dispute(d, request.user) for d in c.disputes.order_by("-created_at")]})
