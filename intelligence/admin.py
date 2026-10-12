from django.contrib import admin

from handy.admin_utils import ReadOnlyHistoryAdmin
from intelligence.models import AIRun, DocumentAnalysis, RiskCase, RiskDecision

# Lecture seule : l'IA et les règles PROPOSENT, un administrateur DÉCIDE depuis le Back-Office (KYC > Risques et fraudes), avec motif et audit.


@admin.register(DocumentAnalysis)
class DocumentAnalysisAdmin(ReadOnlyHistoryAdmin, admin.ModelAdmin):
    list_display = ('id', 'document', 'risk_level', 'ocr_engine', 'external_used', 'created_at')
    list_filter = ('risk_level', 'ocr_engine', 'external_used')
    raw_id_fields = ('document', 'requested_by')
    exclude = ('id_fingerprint',)        # empreinte protégée du numéro de document : jamais affichée


@admin.register(AIRun)
class AIRunAdmin(ReadOnlyHistoryAdmin, admin.ModelAdmin):
    """Journal des appels aux fournisseurs d'IA : fournisseur, tâche, durée, code d'erreur — jamais le contenu."""
    list_display = ('created_at', 'provider', 'task', 'ok', 'sensitive', 'error_code', 'latency_ms')
    list_filter = ('provider', 'ok', 'sensitive', 'task')


class RiskDecisionInline(admin.TabularInline):
    model = RiskDecision
    extra = 0
    can_delete = False
    readonly_fields = ('actor', 'decision', 'reason', 'at')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(RiskCase)
class RiskCaseAdmin(ReadOnlyHistoryAdmin, admin.ModelAdmin):
    list_display = ('id', 'subject', 'kind', 'status', 'priority', 'source', 'detected_at')
    list_filter = ('status', 'kind', 'priority', 'source')
    search_fields = ('subject__username', 'subject__first_name', 'subject__last_name')
    raw_id_fields = ('subject',)
    inlines = [RiskDecisionInline]
