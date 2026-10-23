from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from announcements import services
from announcements.models import Announcement
from handy import destinations
from handy.api.serializers import PublicImageField, absolute_media_url


class FeedAnnouncementSerializer(serializers.Serializer):
    """Annonce telle que l'utilisateur la voit (Web et Flutter) : aucune donnée de ciblage ni statistique."""

    def to_representation(self, delivery):
        a = delivery.announcement
        request = self.context.get("request")
        return {
            "id": a.pk, "title": a.title, "body": a.body, "kind": a.kind,
            "image": absolute_media_url(request, a.image),
            "action": None if a.action_kind == "none" else {
                "kind": a.action_kind, "label": a.action_label or "Voir", "value": a.action_value,
                # Équivalent sur le site (registre central) ; null = pas de page web pour cet écran.
                **({"web": destinations.web_href(a.action_value)} if a.action_kind == "deeplink" else {})},
            "delivered_at": delivery.delivered_at, "expires_at": a.expires_at,
            "seen_at": delivery.seen_at, "opened_at": delivery.opened_at,
        }


class AnnouncementAdminSerializer(serializers.ModelSerializer):
    image = PublicImageField(required=False, allow_null=True)
    image_url = serializers.SerializerMethodField()
    audience = serializers.SerializerMethodField()
    cities = serializers.ListField(child=serializers.CharField(max_length=100), required=False, max_length=50)

    class Meta:
        model = Announcement
        fields = ["id", "title", "body", "image", "image_url", "kind", "action_kind", "action_label", "action_value",
                  "to_clients", "to_artisans", "to_companies", "cities", "audience", "send_push", "publish_at", "expires_at",
                  "status", "published_at", "created_by", "created_at", "updated_at", "version"]
        read_only_fields = ["status", "published_at", "created_by", "created_at", "updated_at", "version"]

    def get_image_url(self, obj):
        return absolute_media_url(self.context.get("request"), obj.image)

    def get_audience(self, obj):
        return services.audience_summary(obj)

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Le titre est obligatoire.")
        return value

    def validate(self, attrs):
        kind = attrs.get("action_kind", getattr(self.instance, "action_kind", "none"))
        value = attrs.get("action_value", getattr(self.instance, "action_value", ""))
        if kind == "none":
            attrs["action_value"], attrs["action_label"] = "", ""
        roles = services.roles_of({f: attrs.get(f, getattr(self.instance, f, False)) for f in ("to_clients", "to_artisans", "to_companies")})
        try:
            services.validate_action(kind, value, roles)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"action_value": exc.messages})
        publish_at = attrs.get("publish_at", getattr(self.instance, "publish_at", None))
        expires_at = attrs.get("expires_at", getattr(self.instance, "expires_at", None))
        if publish_at and expires_at and expires_at <= publish_at:
            raise serializers.ValidationError({"expires_at": "L'expiration doit suivre la publication."})
        attrs["cities"] = [c.strip() for c in attrs.get("cities", getattr(self.instance, "cities", [])) if c.strip()]
        return attrs
