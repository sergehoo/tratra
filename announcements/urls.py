from django.urls import path

from announcements import api

urlpatterns = [
    path("me/announcements/", api.me_announcements, name="me-announcements"),
    path("me/announcements/<int:pk>/<str:event>/", api.me_announcement_event, name="me-announcement-event"),
]
