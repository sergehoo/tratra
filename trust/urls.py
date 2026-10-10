from django.urls import path

from trust import views

urlpatterns = [
    path("me/trust/", views.MyTrustView.as_view(), name="me-trust"),
    path("me/tratra-id/", views.MyTratraIdView.as_view(), name="me-tratra-id"),
    path("me/tratra-id/badge.pdf", views.MyBadgePdfView.as_view(), name="me-tratra-id-pdf"),
    path("verify/id/<str:code>/", views.PublicVerifyView.as_view(), name="verify-id"),
    path("verify/pass/", views.VerifyPassView.as_view(), name="verify-pass"),
    path("bookings/<int:pk>/identity-pass/", views.BookingIdentityPassView.as_view(), name="booking-identity-pass"),
    path("bookings/<int:pk>/identity/", views.BookingIdentityView.as_view(), name="booking-identity"),
]
