from django.contrib import admin
from django.http import HttpResponseRedirect

from trust.models import AuditEvent, BadgeAward, TrustConfig


@admin.register(TrustConfig)
class TrustConfigAdmin(admin.ModelAdmin):
    """Critères des badges EXPERT et SUR, tolérance de ponctualité et pondération du score (configuration unique)."""
    fieldsets = (
        ("EXPERT — expertise démontrée", {"fields": (
            "expert_min_certifications", "expert_min_completed", "expert_min_reviews", "expert_min_rating",
            "expert_min_experience_years")}),
        ("SÛR — fiabilité mesurée", {"fields": (
            "sure_min_completed", "sure_min_punctuality", "sure_min_punctuality_sample", "sure_max_dispute_rate",
            "sure_min_rating", "sure_min_reviews", "sure_window_days")}),
        ("Mesures et réévaluation", {"fields": ("punctuality_tolerance_minutes", "min_sample", "reevaluation_hours")}),
        ("Pondération du score de confiance", {"fields": (
            "weight_identity", "weight_satisfaction", "weight_reliability", "weight_reactivity",
            "weight_track_record", "weight_certifications")}),
    )

    def has_add_permission(self, request):
        return not TrustConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        TrustConfig.get_solo()
        obj = TrustConfig.objects.first()
        return HttpResponseRedirect(f"{request.path}{obj.pk}/change/")


@admin.register(BadgeAward)
class BadgeAwardAdmin(admin.ModelAdmin):
    """Historique des badges : lecture seule (attribution et retrait sont automatiques et audités)."""
    list_display = ("profile", "code", "started_at", "ended_at", "start_reason", "end_reason")
    list_filter = ("code", ("ended_at", admin.EmptyFieldListFilter))
    search_fields = ("profile__user__username", "profile__user__email")
    readonly_fields = [f.name for f in BadgeAward._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_type", "target_id", "organization_id")
    list_filter = ("action", "target_type")
    search_fields = ("action", "target_id")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
