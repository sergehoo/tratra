from django.contrib import admin

from campaigns.models import Campaign, CampaignSend


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    """Lecture et contrôle ; l'édition courante (messages, ciblage, activation avec validation) se fait dans le Back-Office « Engagement »."""
    list_display = ("name", "key", "trigger", "audience", "is_active", "marketing", "send_push", "feature", "priority")
    list_filter = ("is_active", "trigger", "audience", "marketing")
    search_fields = ("name", "key", "title", "body")
    readonly_fields = ("key", "announcement", "activated_at", "version", "created_at", "updated_at")


@admin.register(CampaignSend)
class CampaignSendAdmin(admin.ModelAdmin):
    list_display = ("campaign", "user", "ref", "status", "reason", "push", "due_at", "sent_at", "converted_at")
    list_filter = ("status", "push", "campaign")
    raw_id_fields = ("user", "notification")
    readonly_fields = [f.name for f in CampaignSend._meta.fields]
