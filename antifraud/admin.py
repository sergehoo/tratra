"""Administration : journaux en LECTURE SEULE (aucun texte de SMS, numéros masqués), lots de désactivation consultables. Les
décisions passent par la commande `antifraud_accounts` (rapport relu, confirmation explicite, annulation possible)."""
from django.contrib import admin

from antifraud.models import AccountSuspension, SignupLog, SmsLog, SuspensionBatch


class ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SmsLog)
class SmsLogAdmin(ReadOnly):
    list_display = ("created_at", "purpose", "status", "reason", "number_masked", "country_code", "provider", "ip", "user")
    list_filter = ("status", "purpose", "reason", "country_code", "provider")
    search_fields = ("number_masked", "ip", "user__username")
    date_hierarchy = "created_at"
    raw_id_fields = ("user",)


@admin.register(SignupLog)
class SignupLogAdmin(ReadOnly):
    list_display = ("created_at", "accepted", "reason", "channel", "captcha", "ip", "user")
    list_filter = ("accepted", "reason", "channel", "captcha")
    search_fields = ("ip", "user__username", "user__phone")
    date_hierarchy = "created_at"
    raw_id_fields = ("user",)


class SuspensionInline(admin.TabularInline):
    model = AccountSuspension
    fields = ("user", "was_active", "restored", "reasons")
    readonly_fields = fields
    raw_id_fields = ("user",)
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SuspensionBatch)
class SuspensionBatchAdmin(ReadOnly):
    list_display = ("id", "label", "created_at", "created_by", "reverted_at")
    inlines = [SuspensionInline]
