from django.contrib import admin

from announcements.models import Announcement, AnnouncementDelivery


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    """Lecture seule dans l'administration Django : toute création / publication passe par le Back-Office (droits, audit,
    contrôle de version et validations métier). Évite de contourner le workflow depuis l'ancienne interface."""
    list_display = ("title", "kind", "status", "publish_at", "expires_at", "created_at")
    list_filter = ("status", "kind")
    search_fields = ("title",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AnnouncementDelivery)
class AnnouncementDeliveryAdmin(admin.ModelAdmin):
    list_display = ("announcement", "user", "delivered_at", "seen_at", "opened_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
