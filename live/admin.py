from django.contrib import admin

from live.models import TrackingSession


@admin.register(TrackingSession)
class TrackingSessionAdmin(admin.ModelAdmin):
    """Lecture seule : jalons du suivi (aucune position n'est exposée en administration)."""
    list_display = ("booking", "en_route_at", "arrived_at", "arrival_distance_m", "artisan_sharing", "client_sharing")
    readonly_fields = [f.name for f in TrackingSession._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
