"""API du paiement en espèces d'une réservation : état et historique, déclaration, confirmation/contestation par l'autre partie, justificatif.

Réservées aux DEUX parties de la réservation (404 pour toute autre personne, personnel compris : le Back-Office a sa propre vue en lecture
seule et ne confirme jamais un paiement). Voir `handy/services/cash.py` pour les règles."""
import functools
import mimetypes

from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from continuity.idempotency import run_idempotent
from handy.models import Booking, CashDeclaration, Payment
from handy.services import cash as cash_svc

TAG = "Paiements"


def _error(exc: cash_svc.CashError) -> Response:
    return Response({"code": exc.code, "detail": exc.message, **exc.extra}, status=exc.status)


def _guard(fn):
    @functools.wraps(fn)
    def inner(request, *args, **kwargs):
        try:
            return fn(request, *args, **kwargs)
        except cash_svc.CashError as exc:
            return _error(exc)
    return inner


def _booking_for(request, pk) -> Booking:
    booking = Booking.objects.select_related("service", "client", "handyman").filter(pk=pk).first()
    if booking is None or cash_svc.role_of(booking, request.user) is None:
        raise cash_svc.CashError("not_found", "Introuvable.", 404)
    return booking


def _payment_block(booking: Booking):
    payment = Payment.objects.filter(booking=booking).first()
    if payment is None:
        return None
    from handy.api.serializers import PaymentSerializer
    verification = PaymentSerializer().get_verification(payment)
    if payment.method == "cash":
        # Espèces : confirmation humaine entre les parties (« manual ») dès qu'une déclaration est confirmée ; jamais « provider_verified ».
        verification = "manual" if cash_svc.totals(booking)["confirmed"] > 0 else "unverified"
    return {"id": payment.pk, "method": payment.method, "status": payment.status, "amount": str(payment.amount), "currency": payment.currency,
            "verification": verification, "provider_verified_at": payment.provider_verified_at}


@extend_schema(responses=OpenApiTypes.OBJECT, tags=[TAG], summary="État du règlement d'une réservation (espèces : déclarations et historique)")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@_guard
def booking_payment(request, pk):
    booking = _booking_for(request, pk)
    payment = _payment_block(booking)
    is_cash = payment is None or payment["method"] == "cash"
    return Response({"booking_id": booking.pk, "booking_status": booking.status, "payment": payment, "cash": cash_svc.summary(booking, request.user) if is_cash else None})


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=[TAG], summary="Déclarer un paiement en espèces (remis ou reçu) — à confirmer par l'autre partie")
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@permission_classes([permissions.IsAuthenticated])
def cash_declare(request, pk):
    @_guard
    def call(request):
        booking = _booking_for(request, pk)
        payment = _payment_block(booking)
        if payment is not None and payment["method"] != "cash":
            raise cash_svc.CashError("not_cash", "Cette réservation se règle par un prestataire de paiement, pas en espèces.", 409)
        decl = cash_svc.declare(booking, request.user, request.data, request.FILES.get("receipt"))
        return Response({"declaration": cash_svc.serialize(decl, request.user, booking), "cash": cash_svc.summary(booking, request.user)}, status=201)
    return run_idempotent(request, "handy.cash.declare", lambda: call(request))


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=[TAG], summary="Confirmer ou contester une déclaration d'espèces (l'autre partie uniquement)")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@_guard
def cash_respond(request, pk):
    decl = CashDeclaration.objects.select_related("booking").filter(pk=pk).first()
    if decl is None or cash_svc.role_of(decl.booking, request.user) is None:
        raise cash_svc.CashError("not_found", "Introuvable.", 404)
    confirm = request.data.get("confirm")
    if not isinstance(confirm, bool):
        raise cash_svc.CashError("invalid", "Indiquez si vous confirmez (confirm : true) ou contestez (confirm : false).", 400, fields={"confirm": "Booléen attendu."})
    decl = cash_svc.respond(decl, request.user, confirm, str(request.data.get("reason", "")))
    return Response({"declaration": cash_svc.serialize(decl, request.user, decl.booking), "cash": cash_svc.summary(decl.booking, request.user)})


@extend_schema(responses=OpenApiTypes.BINARY, tags=[TAG], summary="Justificatif d'une déclaration d'espèces (les deux parties uniquement)")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@_guard
def cash_receipt(request, pk):
    decl = CashDeclaration.objects.select_related("booking").filter(pk=pk).first()
    if decl is None or cash_svc.role_of(decl.booking, request.user) is None or not decl.receipt:
        raise cash_svc.CashError("not_found", "Introuvable.", 404)
    response = FileResponse(decl.receipt.open("rb"), content_type=mimetypes.guess_type(decl.receipt.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response
