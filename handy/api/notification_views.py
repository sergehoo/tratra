"""API du centre de notifications : historique, lu/non lu, compteur, catégories, préférences et consentement marketing.

Chaque utilisateur ne voit QUE ses notifications (même le personnel : l'administration dispose de ses propres vues).
Les notifications ne se créent jamais via l'API : seul le serveur les émet (handy.notifications.notify)."""
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from handy import notifications
from handy.models import MarketingConsent, Notification

from .views import DefaultPageNumberPagination


class NotificationSerializer(serializers.ModelSerializer):
    category_label = serializers.SerializerMethodField()
    deeplink = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "notification_type", "category", "category_label", "title", "message", "data", "deeplink",
                  "is_read", "read_at", "created_at"]
        read_only_fields = [f for f in fields if f != "is_read"]

    def get_category_label(self, obj):
        return notifications.CATEGORY_LABELS.get(obj.category, "")

    def get_deeplink(self, obj):
        return notifications.deeplink(obj.data)

    def update(self, instance, validated_data):
        from django.utils import timezone

        if "is_read" in validated_data:
            instance.is_read = validated_data["is_read"]
            instance.read_at = timezone.now() if instance.is_read else None
            instance.save(update_fields=["is_read", "read_at"])
        return instance


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = DefaultPageNumberPagination
    http_method_names = ["get", "patch", "delete", "post", "head", "options"]

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user).order_by("-created_at", "-id")
        params = self.request.query_params
        if params.get("category"):
            qs = qs.filter(category=params["category"])
        if params.get("type"):
            qs = qs.filter(notification_type=params["type"])
        if params.get("is_read") in ("true", "false", "1", "0"):
            qs = qs.filter(is_read=params["is_read"] in ("true", "1"))
        return qs

    def create(self, request, *args, **kwargs):  # pas de création côté client : aucune fausse notification possible
        return Response({"detail": "Méthode non autorisée."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @extend_schema(summary="Compteur de notifications non lues, par catégorie")
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        by_category = notifications.unread_by_category(request.user)
        return Response({"unread": sum(by_category.values()), "by_category": by_category})

    @extend_schema(summary="Marquer comme lues (ids, catégorie, ou toutes)")
    @action(detail=False, methods=["post"], url_path="mark-read")
    def mark_read(self, request):
        ids = request.data.get("ids")
        category = request.data.get("category")
        if ids is not None and not isinstance(ids, list):
            return Response({"ids": "Une liste d'identifiants est attendue."}, status=status.HTTP_400_BAD_REQUEST)
        updated = notifications.mark_read(request.user, ids=ids, category=category)
        return Response({"updated": updated, "unread": notifications.unread_count(request.user)})


def _consent_payload(user):
    consent = MarketingConsent.objects.filter(user=user).first()
    return {"granted": bool(consent and consent.granted), "granted_at": consent.granted_at if consent else None,
            "revoked_at": consent.revoked_at if consent else None}


@extend_schema(tags=["Notifications"], summary="Préférences de notification par catégorie et consentement marketing")
@api_view(["GET", "PUT"])
@permission_classes([permissions.IsAuthenticated])
def me_notification_preferences(request):
    """GET : {preferences: [{category, label, push_enabled, locked}], marketing_consent}.
    PUT {"preferences": {"booking": true, "review": false}} : les catégories verrouillées (compte) ne sont jamais coupées."""
    if request.method == "PUT":
        changes = request.data.get("preferences")
        if not isinstance(changes, dict) or not all(isinstance(v, bool) for v in changes.values()):
            return Response({"preferences": "Un objet {catégorie: true|false} est attendu."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            notifications.set_preferences(request.user, changes)
        except ValueError as exc:
            return Response({"preferences": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"preferences": notifications.preferences_for(request.user), "marketing_consent": _consent_payload(request.user)})


@extend_schema(tags=["Notifications"], summary="Donner ou retirer le consentement aux communications promotionnelles")
@api_view(["PUT"])
@permission_classes([permissions.IsAuthenticated])
def me_marketing_consent(request):
    granted = request.data.get("granted")
    if not isinstance(granted, bool):
        return Response({"granted": "true ou false attendu."}, status=status.HTTP_400_BAD_REQUEST)
    source = str(request.data.get("source") or "app")[:40]
    notifications.set_marketing_consent(request.user, granted, source=source, text_version=str(request.data.get("text_version") or "v1")[:20])
    return Response(_consent_payload(request.user))
