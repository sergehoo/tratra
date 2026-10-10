from django.urls import path

from continuity import api

urlpatterns = [
    path("me/activities/", api.me_activities, name="me-activities"),
    path("bookings/<int:pk>/history/", api.booking_history, name="booking-history"),
]
