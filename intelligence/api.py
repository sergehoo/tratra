"""Recommandations (Web / Flutter) : moteur déterministe, résultats explicables, prestataires éligibles uniquement."""
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from handy.models import ServiceCategory, UserAddress
from intelligence import recommendations
from transport.api import destination_from, _when


@extend_schema(tags=["Recommandations"], summary="Services recommandés (besoin, catégorie, lieu, créneau) — critères explicables")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def recommend(request):
    d = request.data
    category = None
    if d.get("category"):
        raw = str(d["category"])
        category = (ServiceCategory.objects.filter(pk=int(raw)).first() if raw.isdigit() else ServiceCategory.objects.filter(slug=raw).first())
        if category is None:
            return Response({"detail": "Catégorie inconnue."}, status=status.HTTP_400_BAD_REQUEST)
    point, _commune, _city, error = destination_from(d, request.user)
    if error:
        return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
    used_default = False
    if point is None and not d.get("lat") and not d.get("address_id"):
        a = UserAddress.objects.filter(user=request.user, is_primary=True, latitude__isnull=False, longitude__isnull=False).first()
        if a:
            point, used_default = (float(a.latitude), float(a.longitude)), True      # l'adresse principale du compte, jamais celle d'un autre
    when = _when(d.get("when")) if d.get("when") else None
    try:
        limit = max(1, min(int(d.get("limit", 6)), 12))
    except (TypeError, ValueError):
        limit = 6
    out = recommendations.recommend(request.user, category=category, query=str(d.get("q") or "")[:200], location=point, when=when, limit=limit)
    return Response({**out, "located": point is not None, "used_primary_address": used_default})


recommend.cls.throttle_scope = "geo"
