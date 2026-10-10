from django.db.models import Q
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from handy.models import Booking
from live import notify, realtime, services


def _booking(user, pk):
    return Booking.objects.select_related("client", "handyman").filter(Q(client=user) | Q(handyman=user), pk=pk).first()


class LiveBase(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def booking(self, request, pk):
        booking = _booking(request.user, pk)
        if booking is None:  # tiers ou réservation inexistante : même réponse
            raise services.LiveError("not_found", "Réservation introuvable.", 404)
        return booking

    def handle_exception(self, exc):
        if isinstance(exc, services.LiveError):
            return Response(exc.payload(), status=exc.status)
        return super().handle_exception(exc)

    def state(self, booking, user, code=status.HTTP_200_OK):
        response = Response(realtime.jsonable(services.snapshot(booking, user)), status=code)
        response["Cache-Control"] = "private, no-store"
        return response


class LiveStateView(LiveBase):
    """GET /handy/bookings/<id>/live/ — état du suivi vu par l'utilisateur courant (lecture, repli du temps réel)."""

    def get(self, request, pk):
        return self.state(self.booking(request, pk), request.user)


class LiveConsentView(LiveBase):
    """POST /handy/bookings/<id>/live/consent/ {share: bool} — activer / retirer le partage de SA position."""

    def post(self, request, pk):
        booking = self.booking(request, pk)
        share = request.data.get("share")
        if not isinstance(share, bool):
            raise services.LiveError("invalid", "share (booléen) requis.")
        services.set_consent(booking, request.user, share)
        realtime.broadcast(booking)
        return self.state(booking, request.user)


class LiveEnRouteView(LiveBase):
    """POST /handy/bookings/<id>/live/en-route/ {consent: true} — « Je suis en route » (artisan)."""

    def post(self, request, pk):
        booking = self.booking(request, pk)
        first = not getattr(services.get_session(booking), "en_route_at", None)
        services.start_route(booking, request.user, consent=request.data.get("consent") is True)
        if first:
            notify.notify_client(booking, "en_route")
        realtime.broadcast(booking)
        return self.state(booking, request.user)


class LiveArrivedView(LiveBase):
    """POST /handy/bookings/<id>/live/arrived/ — « Je suis arrivé » (artisan) : fin du partage de position."""

    def post(self, request, pk):
        booking = self.booking(request, pk)
        first = not getattr(services.get_session(booking), "arrived_at", None)
        services.arrive(booking, request.user)
        if first:
            notify.notify_client(booking, "arrived")
        realtime.broadcast(booking)
        return self.state(booking, request.user)


class LivePositionView(LiveBase):
    """POST /handy/bookings/<id>/live/position/ — position du participant (consentement et jalon vérifiés)."""

    def post(self, request, pk):
        booking = self.booking(request, pk)
        services.record_position(booking, request.user, request.data)
        realtime.broadcast(booking)
        return self.state(booking, request.user, status.HTTP_201_CREATED)


class LiveTicketView(LiveBase):
    """POST /handy/bookings/<id>/live/ticket/ — billet à 60 s pour ouvrir la WebSocket /ws/live/<id>/."""

    def post(self, request, pk):
        booking = self.booking(request, pk)
        services.role_of(booking, request.user)
        response = Response({"ticket": realtime.make_ticket(request.user.id, booking.id),
                             "path": f"/ws/live/{booking.id}/", "expires_in": realtime.TICKET_MAX_AGE})
        response["Cache-Control"] = "private, no-store"
        return response
