"""API de continuité : activités en cours (reprise après fermeture, coupure, plantage, changement d'appareil) et
historique des statuts d'une réservation."""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from continuity import activities
from handy.models import Booking


@extend_schema(tags=["Continuité"], summary="Mes activités en cours (reprise)",
               parameters=[OpenApiParameter("since", str, description="Horodatage ISO 8601 : renvoie aussi les changements depuis.")])
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me_activities(request):
    """Source de vérité pour la bannière « Activité en cours » et le bouton « Reprendre ma mission ».
    `server_time` sert de curseur pour la synchronisation suivante (`?since=`), sans dépendre de l'horloge du téléphone."""
    now = timezone.now()
    items = activities.active_for(request.user)
    body = {"server_time": now, "has_active": bool(items), "primary": activities.primary(items), "activities": items}
    raw = request.query_params.get("since")
    if raw:
        since = parse_datetime(raw)
        if since is None:
            return Response({"code": "invalid_since", "detail": "Horodatage `since` invalide."}, status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(since):
            since = timezone.make_aware(since)
        body["changes"] = activities.changes_since(request.user, since)
    return Response(body)


@extend_schema(tags=["Continuité"], summary="Historique des statuts d'une réservation")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def booking_history(request, pk):
    """Événements de statut : qui (rôle, jamais l'identité), quand, de quel statut à quel statut. Réservé aux parties."""
    booking = get_object_or_404(Booking.objects.filter(client=request.user) | Booking.objects.filter(handyman=request.user), pk=pk)
    events = []
    for t in booking.timeline.select_related("actor").order_by("at", "id"):
        by = "system" if t.actor_id is None else ("client" if t.actor_id == booking.client_id else "handyman")
        events.append({"status": t.status, "previous_status": t.previous_status or None, "at": t.at, "by": by})
    return Response({"booking_id": booking.id, "status": booking.status, "version": booking.version, "created_at": booking.created_at,
                     "events": events})
