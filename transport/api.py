"""API membre du transport (Web / Flutter) : devis avec créneaux, et recalcul explicite d'une réservation en attente.
Le serveur recalcule toujours : un montant envoyé par le client n'est qu'un accord à confirmer, jamais une valeur de confiance."""
from django.db.models import F
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from handy.api.errors import CodedAPIException
from handy.models import Booking, Payment, Service, User, UserAddress
from transport import pricing


def TransportChanged(quote: dict) -> CodedAPIException:
    """409 : le transport recalculé par le serveur diffère de celui que le client a vu ; il doit confirmer le nouveau montant."""
    return CodedAPIException("transport_changed", "Les frais de déplacement ont changé. Vérifiez le nouveau montant avant de confirmer.", status=409, quote=quote)


def destination_from(data, user):
    """Point, commune et ville du lieu de mission : adresse enregistrée du compte (`address_id`) ou coordonnées envoyées."""
    commune, city, point = str(data.get("commune") or ""), str(data.get("city") or ""), None
    if data.get("address_id"):
        a = UserAddress.objects.filter(pk=data["address_id"], user=user).first()
        if a is None:
            return None, "", "", "Adresse introuvable."
        commune, city = a.commune, a.city
        if a.latitude is not None and a.longitude is not None:
            point = (float(a.latitude), float(a.longitude))
    elif data.get("lat") not in (None, "") and data.get("lng") not in (None, ""):
        try:
            lat, lng = float(data["lat"]), float(data["lng"])
        except (TypeError, ValueError):
            return None, "", "", "Coordonnées invalides."
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None, "", "", "Coordonnées invalides."
        point = (lat, lng)
    return point, commune, city, None


def _when(raw):
    if not raw:
        return timezone.now()
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(str(raw))
    return pricing.local(parsed) if parsed else timezone.now()


@extend_schema(tags=["Transport"], summary="Estimer les frais de déplacement et proposer des créneaux")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def transport_quote(request):
    d = request.data
    service = Service.objects.select_related("handyman").filter(pk=d.get("service")).first() if d.get("service") else None
    handyman = service.handyman if service else User.objects.filter(pk=d.get("handyman")).first()
    if handyman is None:
        return Response({"detail": "Indiquez une prestation ou un artisan."}, status=status.HTTP_400_BAD_REQUEST)
    point, commune, city, error = destination_from(d, request.user)
    if error:
        return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
    needs = service.requires_travel if service else True
    when = _when(d.get("when"))
    now = timezone.now()
    return Response({
        "quote": pricing.quote(handyman=handyman, destination=point, when=when, commune=commune, city=city, needs_travel=needs),
        "suggestions": pricing.suggestions(handyman=handyman, destination=point, now=now, commune=commune, city=city, needs_travel=needs) if d.get("suggestions", True) else [],
        "needs_travel": needs,
    })


@extend_schema(tags=["Transport"], summary="Recalculer explicitement les frais de déplacement d'une réservation en attente")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def booking_transport_requote(request, pk):
    from trust.models import audit

    booking = Booking.objects.select_related("service", "handyman").filter(pk=pk, client=request.user).first()
    if booking is None:
        return Response({"detail": "Réservation introuvable."}, status=status.HTTP_404_NOT_FOUND)
    if booking.status != "pending" or Payment.objects.filter(booking=booking).exists():
        return Response({"code": "transport_locked", "detail": "Le montant est figé : un paiement existe ou la réservation n'est plus en attente."}, status=status.HTTP_409_CONFLICT)
    loc = booking.job_location
    quote = pricing.quote(handyman=booking.handyman, destination=(loc.y, loc.x) if loc else None, when=booking.booking_date, city=booking.city,
                          needs_travel=booking.service.requires_travel if booking.service else True)
    accepted = request.data.get("accept_fee")
    if accepted is None or int(float(accepted)) != quote["amount"]:
        raise TransportChanged(quote)                        # modification EXPLICITE : le client doit confirmer le montant recalculé
    Booking.objects.filter(pk=booking.pk).update(transport_fee=quote["amount"], transport_quote=quote, version=F("version") + 1)
    audit("booking.transport_requoted", actor=request.user, target=booking, amount=quote["amount"], version=quote["version"])
    return Response({"transport_fee": quote["amount"], "quote": quote})


transport_quote.cls.throttle_scope = "geo"
booking_transport_requote.cls.throttle_scope = "geo"
