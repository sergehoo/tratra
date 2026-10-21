from django.urls import path

from flash import api

urlpatterns = [
    path("flash/requests/", api.requests_view, name="flash-requests"),
    path("flash/requests/<int:pk>/", api.request_detail, name="flash-request"),
    path("flash/requests/<int:pk>/cancel/", api.request_cancel, name="flash-request-cancel"),
    path("flash/requests/<int:pk>/relaunch/", api.request_relaunch, name="flash-request-relaunch"),
    path("flash/requests/<int:pk>/quotes/<int:offer_id>/accept/", api.request_choose_quote, name="flash-request-choose-quote"),
    path("flash/offers/", api.offers_view, name="flash-offers"),
    path("flash/offers/<int:pk>/", api.offer_detail, name="flash-offer"),
    path("flash/offers/<int:pk>/accept/", api.offer_accept, name="flash-offer-accept"),
    path("flash/offers/<int:pk>/decline/", api.offer_decline, name="flash-offer-decline"),
    path("flash/offers/<int:pk>/quote/", api.offer_quote, name="flash-offer-quote"),
    path("flash/availability/", api.availability_view, name="flash-availability"),
]
