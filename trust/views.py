from django.db.models import Q
from django.http import HttpResponse
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from handy.models import Booking, HandymanProfile
from trust import identity, passport
from trust.engine import evaluate_profile


def _own_profile(user):
    return HandymanProfile.objects.select_related("user").prefetch_related("skills").filter(user=user).first()


class MyTrustView(APIView):
    """GET /handy/me/trust/ — « Ma réputation » : passeport détaillé de l'artisan connecté (critères restants,
    historique motivé, justificatifs en attente). Le compte unique sans profil artisan reçoit 404."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = _own_profile(request.user)
        if profile is None:
            return Response({"detail": "Aucun profil artisan sur ce compte."}, status=status.HTTP_404_NOT_FOUND)
        # Données fraîches : la page propriétaire reflète l'état réel au moment de la consultation.
        evaluate_profile(profile, trigger="owner_view")
        return Response(passport.build(profile, request=request, owner=True))


class MyTratraIdView(APIView):
    """GET /handy/me/tratra-id/ — badge numérique + QR permanent de l'artisan connecté (créé à la 1re demande)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = _own_profile(request.user)
        if profile is None:
            return Response({"detail": "Aucun profil artisan sur ce compte."}, status=status.HTTP_404_NOT_FOUND)
        response = Response(identity.my_id(profile, request))
        response["Cache-Control"] = "private, no-store"
        return response


class MyBadgePdfView(APIView):
    """GET /handy/me/tratra-id/badge.pdf — badge imprimable ; réservé à un badge ACTIF."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = _own_profile(request.user)
        if profile is None:
            return Response({"detail": "Aucun profil artisan sur ce compte."}, status=status.HTTP_404_NOT_FOUND)
        try:
            pdf = identity.badge_pdf(profile)
        except identity.IdentityError as e:
            return Response(e.payload(), status=e.status)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="tratra-id-{identity.ensure_id(profile).code}.pdf"'
        response["Cache-Control"] = "private, no-store"
        return response


class PublicVerifyView(APIView):
    """GET /handy/verify/id/<code>/ — vérification PUBLIQUE d'un QR permanent (limitée en fréquence).

    Réponse de même forme pour tout code ; validité recalculée à chaque appel (suspension = révocation immédiate) ;
    un badge révoqué ne divulgue plus aucun détail personnel."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_scope = "verify"

    def get(self, request, code):
        http_status, payload = identity.public_verification(code, request)
        response = Response(payload, status=http_status)
        response["Cache-Control"] = "no-store"
        return response


def _participant_booking(user, pk):
    return Booking.objects.filter(Q(client=user) | Q(handyman=user), pk=pk).first()


class BookingIdentityPassView(APIView):
    """POST /handy/bookings/<id>/identity-pass/ — l'ARTISAN de la réservation obtient un QR de mission
    temporaire (15 min, usage unique)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        booking = _participant_booking(request.user, pk)
        if booking is None:
            return Response({"detail": "Réservation introuvable."}, status=status.HTTP_404_NOT_FOUND)
        try:
            data = identity.issue_pass(booking, request.user)
        except identity.IdentityError as e:
            return Response(e.payload(), status=e.status)
        response = Response(data, status=status.HTTP_201_CREATED)
        response["Cache-Control"] = "private, no-store"
        return response


class BookingIdentityView(APIView):
    """GET /handy/bookings/<id>/identity/ — la vérification d'identité de la réservation a-t-elle eu lieu ?"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        booking = _participant_booking(request.user, pk)
        if booking is None:
            return Response({"detail": "Réservation introuvable."}, status=status.HTTP_404_NOT_FOUND)
        return Response(identity.booking_identity(booking))


class VerifyPassView(APIView):
    """POST /handy/verify/pass/ {token} — le CLIENT de la réservation scanne le QR de mission : identité confirmée
    et QR consommé. Un tiers reçoit la même réponse qu'un QR inconnu."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "verify"

    def post(self, request):
        try:
            data = identity.consume_pass(request.data.get("token", ""), request.user, request)
        except identity.IdentityError as e:
            return Response(e.payload(), status=e.status)
        response = Response(data)
        response["Cache-Control"] = "private, no-store"
        return response
