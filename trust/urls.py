from django.urls import path

from trust.views import MyTrustView

urlpatterns = [
    path("me/trust/", MyTrustView.as_view(), name="me-trust"),
]
