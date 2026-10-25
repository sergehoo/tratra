from django.urls import path

from statuses import api

urlpatterns = [
    path("statuses/", api.statuses, name="statuses"),
    path("statuses/feed/", api.feed, name="statuses-feed"),
    path("statuses/discover/", api.discover, name="statuses-discover"),
    path("statuses/presence/", api.presence, name="statuses-presence"),
    path("statuses/authors/<int:user_id>/", api.author_statuses, name="statuses-author"),
    path("statuses/settings/", api.settings_view, name="statuses-settings"),
    path("statuses/contacts/", api.contacts_view, name="statuses-contacts"),
    path("statuses/exclusions/", api.exclusions_view, name="statuses-exclusions"),
    path("statuses/exclusions/<int:user_id>/", api.exclusion_detail, name="statuses-exclusion-detail"),
    path("statuses/<int:pk>/", api.status_detail, name="status-detail"),
    path("statuses/<int:pk>/view/", api.status_view, name="status-view"),
    path("statuses/<int:pk>/viewers/", api.status_viewers, name="status-viewers"),
    path("statuses/<int:pk>/reply/", api.status_reply, name="status-reply"),
    path("statuses/<int:pk>/report/", api.status_report, name="status-report"),
]
