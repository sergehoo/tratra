"""API des annonces : flux de l'utilisateur (Web/Flutter) et administration (Back-Office, droit announcements.manage)."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from announcements import services
from announcements.models import Announcement, AnnouncementDelivery
from announcements.serializers import AnnouncementAdminSerializer, FeedAnnouncementSerializer
from backoffice.permissions import HasBackOfficePermission
from handy.api.views import DefaultPageNumberPagination
from trust.models import audit


# ---------------------------------------------------------------------------------------------- flux utilisateur

@extend_schema(tags=["Annonces"], summary="Mes annonces actives")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me_announcements(request):
    deliveries = services.feed_for(request.user)[:30]
    return Response({"results": FeedAnnouncementSerializer(deliveries, many=True, context={"request": request}).data})


@extend_schema(tags=["Annonces"], summary="Marquer une annonce comme vue / ouverte / écartée")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def me_announcement_event(request, pk, event):
    field = {"seen": "seen_at", "open": "opened_at", "dismiss": "dismissed_at"}.get(event)
    if field is None:
        return Response({"detail": "Événement inconnu."}, status=status.HTTP_404_NOT_FOUND)
    try:
        delivery = services.mark(request.user, pk, field)
    except AnnouncementDelivery.DoesNotExist:
        return Response({"detail": "Introuvable."}, status=status.HTTP_404_NOT_FOUND)   # jamais l'annonce d'un autre
    return Response({"id": pk, "seen_at": delivery.seen_at, "opened_at": delivery.opened_at, "dismissed_at": delivery.dismissed_at})


# --------------------------------------------------------------------------------------------- administration

class AnnouncementAdminViewSet(viewsets.ModelViewSet):
    """CRUD des annonces. Une annonce publiée n'est plus modifiable (sauf son expiration) : on l'annule ou on la laisse expirer."""
    queryset = Announcement.objects.all()
    serializer_class = AnnouncementAdminSerializer
    permission_classes = [HasBackOfficePermission]
    bo_permission = "announcements.manage"
    pagination_class = DefaultPageNumberPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        for field in ("status", "kind"):
            if params.get(field):
                qs = qs.filter(**{field: params[field]})
        if params.get("q"):
            qs = qs.filter(title__icontains=params["q"])
        return qs

    def perform_create(self, serializer):
        a = serializer.save(created_by=self.request.user, status="draft")
        audit("announcement.created", actor=self.request.user, target=a, kind=a.kind)

    def _check_version(self, request, instance):
        raw = request.data.get("version", request.headers.get("If-Match"))
        if raw in (None, ""):
            raise serializers.ValidationError({"version": "La version de l'annonce est requise (écritures concurrentes)."})
        if int(raw) != instance.version:
            raise ConflictError(instance.version)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self._check_version(request, instance)
        except (TypeError, ValueError):
            raise serializers.ValidationError({"version": "Version invalide."})
        except ConflictError as exc:
            return Response({"detail": "L'annonce a été modifiée entre-temps.", "current_version": exc.version}, status=status.HTTP_409_CONFLICT)
        if instance.status not in ("draft", "scheduled"):
            allowed = {"expires_at", "version"}
            if set(request.data.keys()) - allowed:
                raise serializers.ValidationError({"detail": "Une annonce publiée ne peut plus être modifiée : annulez-la ou laissez-la expirer."})
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        a = serializer.save(version=instance.version + 1)
        audit("announcement.updated", actor=request.user, target=a, fields=sorted(k for k in request.data.keys() if k != "version"))
        return Response(self.get_serializer(a).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, partial=True, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status != "draft":
            return Response({"detail": "Seul un brouillon peut être supprimé ; une annonce programmée ou publiée s'annule."},
                            status=status.HTTP_409_CONFLICT)
        audit("announcement.deleted", actor=request.user, target=instance)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _run(self, request, fn, *args):
        a = self.get_object()
        try:
            return Response(self.get_serializer(fn(a, *args, actor=request.user)).data)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        return self._run(request, services.publish)

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        value = serializers.DateTimeField().to_internal_value(request.data.get("publish_at"))
        return self._run(request, services.schedule, value)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._run(request, services.cancel)

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        return Response(services.stats(self.get_object()))


class ConflictError(Exception):
    def __init__(self, version):
        self.version = version
