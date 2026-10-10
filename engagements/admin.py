"""Administration Django (lecture surtout) : la gestion courante se fait dans le Back-Office (RBAC + journal d'audit)."""
from django.contrib import admin

from engagements import models


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.EngagementRule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("category", "is_default", "active", "allow_recurring", "allow_long_term", "allow_employment", "max_duration_months", "updated_at")
    list_filter = ("is_default", "active", "allow_employment")


@admin.register(models.EngagementContract)
class ContractAdmin(ReadOnlyAdmin):
    list_display = ("id", "title", "status", "mission_type", "work_relationship", "principal", "worker", "start_date", "end_date", "amount", "period")
    list_filter = ("status", "mission_type", "work_relationship")
    search_fields = ("title", "principal__username", "worker__username")
    raw_id_fields = ("principal", "worker", "organization", "posting", "application", "service", "non_renewal_by", "notice_given_by")


@admin.register(models.EngagementPosting)
class PostingAdmin(ReadOnlyAdmin):
    list_display = ("id", "title", "status", "mission_type", "work_relationship", "city", "publisher", "published_at")
    list_filter = ("status", "mission_type", "work_relationship")
    search_fields = ("title", "city", "publisher__username")


@admin.register(models.ContractInstallment)
class InstallmentAdmin(ReadOnlyAdmin):
    list_display = ("id", "contract", "sequence", "period_start", "period_end", "due_date", "base_amount", "status")
    list_filter = ("status",)


@admin.register(models.EngagementDispute)
class DisputeAdmin(ReadOnlyAdmin):
    list_display = ("id", "contract", "kind", "status", "opened_by", "created_at")
    list_filter = ("status", "kind")


@admin.register(models.ContractEvent)
class EventAdmin(ReadOnlyAdmin):
    list_display = ("id", "contract", "type", "actor", "created_at")
    list_filter = ("type",)
