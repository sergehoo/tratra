from django.contrib import admin

from handy.admin_utils import ReadOnlyHistoryAdmin
from reputation.models import ClientReview, EvaluationContest, EvaluationWatch, WatchDecision

# Lecture seule : modération, contestations et décisions de surveillance se font dans le Back-Office (motif obligatoire, historique, audit).


@admin.register(ClientReview)
class ClientReviewAdmin(ReadOnlyHistoryAdmin, admin.ModelAdmin):
    list_display = ('id', 'booking', 'author', 'subject', 'rating', 'is_hidden', 'revealed_at', 'created_at')
    list_filter = ('is_hidden', 'rating', ('revealed_at', admin.EmptyFieldListFilter))
    search_fields = ('author__username', 'subject__username', 'comment')
    raw_id_fields = ('booking', 'author', 'subject')
    date_hierarchy = 'created_at'


@admin.register(EvaluationContest)
class EvaluationContestAdmin(ReadOnlyHistoryAdmin, admin.ModelAdmin):
    list_display = ('id', 'author', 'status', 'created_at', 'resolved_at')
    list_filter = ('status',)
    raw_id_fields = ('client_review', 'review', 'author', 'resolved_by')


class WatchDecisionInline(admin.TabularInline):
    model = WatchDecision
    extra = 0
    can_delete = False
    readonly_fields = ('actor', 'decision', 'reason', 'at')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(EvaluationWatch)
class EvaluationWatchAdmin(ReadOnlyHistoryAdmin, admin.ModelAdmin):
    list_display = ('id', 'subject', 'kind', 'status', 'priority', 'detected_at')
    list_filter = ('status', 'kind', 'priority')
    search_fields = ('subject__username', 'subject__first_name', 'subject__last_name')
    raw_id_fields = ('subject',)
    inlines = [WatchDecisionInline]
