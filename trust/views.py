from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from handy.models import HandymanProfile
from trust import passport
from trust.engine import evaluate_profile


class MyTrustView(APIView):
    """GET /handy/me/trust/ — « Ma réputation » : passeport détaillé de l'artisan connecté (critères restants,
    historique motivé, justificatifs en attente). Le compte unique sans profil artisan reçoit 404."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = HandymanProfile.objects.select_related("user").filter(user=request.user).first()
        if profile is None:
            return Response({"detail": "Aucun profil artisan sur ce compte."}, status=status.HTTP_404_NOT_FOUND)
        # Données fraîches : la page propriétaire reflète l'état réel au moment de la consultation.
        evaluate_profile(profile, trigger="owner_view")
        return Response(passport.build(profile, request=request, owner=True))
