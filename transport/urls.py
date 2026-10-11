from django.urls import path

from transport import api

urlpatterns = [
    path("transport/quote/", api.transport_quote, name="transport-quote"),
    path("bookings/<int:pk>/transport/", api.booking_transport_requote, name="booking-transport"),
]
