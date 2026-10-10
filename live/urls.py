from django.urls import path

from live import views

urlpatterns = [
    path("bookings/<int:pk>/live/", views.LiveStateView.as_view(), name="live-state"),
    path("bookings/<int:pk>/live/consent/", views.LiveConsentView.as_view(), name="live-consent"),
    path("bookings/<int:pk>/live/en-route/", views.LiveEnRouteView.as_view(), name="live-en-route"),
    path("bookings/<int:pk>/live/arrived/", views.LiveArrivedView.as_view(), name="live-arrived"),
    path("bookings/<int:pk>/live/position/", views.LivePositionView.as_view(), name="live-position"),
    path("bookings/<int:pk>/live/ticket/", views.LiveTicketView.as_view(), name="live-ticket"),
]
