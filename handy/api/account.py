"""Suppression de son propre compte : GET = ce qui empêche la suppression (liste vide = possible) ; POST {password, confirm} = anonymisation.
Le mot de passe est redemandé (un jeton volé ne suffit pas) et la confirmation écrite évite un geste accidentel."""
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from handy import account_deletion

CONFIRM_WORD = "SUPPRIMER"


class DeletionThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        view.throttle_scope = "login"
        return super().allow_request(request, view)


@never_cache
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["Compte"],
               summary="Suppression de mon compte : éléments bloquants (GET) / suppression définitive (POST {password, confirm})")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([DeletionThrottle])
def me_account_deletion(request):
    user = request.user
    if request.method == "GET":
        reasons = account_deletion.blockers(user)
        return Response({"allowed": not reasons, "blockers": reasons, "confirm_word": CONFIRM_WORD})
    if str(request.data.get("confirm") or "").strip().upper() != CONFIRM_WORD:
        return Response({"detail": f"Tapez « {CONFIRM_WORD} » pour confirmer.", "code": "confirm_required"}, status=status.HTTP_400_BAD_REQUEST)
    if not user.check_password(str(request.data.get("password") or "")):
        return Response({"detail": "Mot de passe incorrect.", "code": "wrong_password"}, status=status.HTTP_403_FORBIDDEN)
    try:
        account_deletion.delete_account(user)
    except account_deletion.DeletionRefused as exc:
        return Response({"detail": "Suppression impossible pour le moment.", "code": "blocked", "blockers": exc.blockers}, status=status.HTTP_409_CONFLICT)
    return Response({"deleted": True})
