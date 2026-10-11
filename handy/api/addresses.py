"""Adresses du compte courant + recherche d'adresse (partagées Web / Flutter). Propriétaire seul : aucune adresse d'un autre compte."""
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from handy import addresses, geo
from handy.models import UserAddress


def _own(request, pk):
    return UserAddress.objects.filter(pk=pk, user=request.user).select_related("user").first()


def _bad(exc: addresses.AddressError):
    return Response(exc.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=["Adresses"], summary="Lister / créer mes adresses")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
def me_addresses(request):
    if request.method == "POST":
        try:
            a = addresses.create(request.user, request.data, make_primary=request.data.get("is_primary") is True)
        except addresses.AddressError as exc:
            return _bad(exc)
        return Response(addresses.serialize(a), status=status.HTTP_201_CREATED)
    rows = UserAddress.objects.filter(user=request.user)
    return Response({"results": [addresses.serialize(a) for a in rows], "complete": addresses.is_complete(request.user),
                     "max": UserAddress.MAX_PER_USER})


@extend_schema(tags=["Adresses"], summary="Lire / modifier / supprimer une de mes adresses")
@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([permissions.IsAuthenticated])
def me_address_detail(request, pk):
    a = _own(request, pk)
    if a is None:
        return Response({"detail": "Adresse introuvable."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        addresses.delete(a)
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":
        try:
            a = addresses.update(a, request.data)
        except addresses.AddressError as exc:
            return _bad(exc)
    return Response(addresses.serialize(a))


@extend_schema(tags=["Adresses"], summary="Définir mon adresse principale")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def me_address_set_primary(request, pk):
    a = _own(request, pk)
    if a is None:
        return Response({"detail": "Adresse introuvable."}, status=status.HTTP_404_NOT_FOUND)
    return Response(addresses.serialize(addresses.set_primary(a)))


def _unavailable(exc: geo.GeoUnavailable):
    # 503 + `manual_entry` : l'application bascule sur la saisie manuelle au lieu d'afficher une erreur bloquante.
    return Response({"detail": str(exc), "manual_entry": True}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@extend_schema(tags=["Adresses"], summary="Autocomplétion / géocodage d'une adresse (fournisseur configurable, mis en cache)")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def geo_search(request):
    q = str(request.query_params.get("q") or "")
    try:
        return Response({"results": geo.search(q), "provider": geo.provider()})
    except geo.GeoUnavailable as exc:
        return _unavailable(exc)


@extend_schema(tags=["Adresses"], summary="Géocodage inverse d'un point (consentement explicite requis)")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def geo_reverse(request):
    if request.query_params.get("consent") != "true":
        return Response({"consent": "Votre consentement explicite est requis pour utiliser ces coordonnées."}, status=status.HTTP_400_BAD_REQUEST)
    errors = {}
    try:
        lat, lng = float(request.query_params.get("lat")), float(request.query_params.get("lng"))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError
    except (TypeError, ValueError):
        return Response({"lat": "Coordonnées invalides."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response({"result": geo.reverse(lat, lng), "provider": geo.provider()})
    except geo.GeoUnavailable as exc:
        return _unavailable(exc)


geo_search.cls.throttle_scope = "geo"
geo_reverse.cls.throttle_scope = "geo"
