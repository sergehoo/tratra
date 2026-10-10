from django.contrib import admin

from business import models


@admin.register(models.Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "city", "is_active", "created_at")
    search_fields = ("name", "registration_number")
    list_filter = ("is_active",)


@admin.register(models.Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("user__username", "organization__name")


for _model in (models.Site, models.Building, models.Equipment, models.MaintenanceContract, models.PreventivePlan,
               models.Budget, models.ApprovalRule):
    admin.site.register(_model)


@admin.register(models.InterventionRequest)
class InterventionRequestAdmin(admin.ModelAdmin):
    list_display = ("number", "organization", "site", "title", "status", "priority", "created_at")
    list_filter = ("status", "priority", "source")
    search_fields = ("number", "title")


@admin.register(models.ConsolidatedInvoice)
class ConsolidatedInvoiceAdmin(admin.ModelAdmin):
    """Lecture seule : une facture consolidée émise ne se modifie pas."""
    list_display = ("number", "organization", "period_start", "period_end", "total", "status")
    readonly_fields = [f.name for f in models.ConsolidatedInvoice._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
