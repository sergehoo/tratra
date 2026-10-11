from django.urls import path

from reputation import api

urlpatterns = [
    path("me/evaluations/", api.me_evaluations, name="me-evaluations"),
    path("bookings/<int:pk>/evaluation/", api.booking_evaluation, name="booking-evaluation"),
    path("client-reviews/<int:pk>/contest/", api.client_review_contest, name="client-review-contest"),
    path("users/<int:pk>/requester-score/", api.requester_score, name="requester-score"),
]
