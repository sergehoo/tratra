from django.urls import include, path
from rest_framework.routers import DefaultRouter

from announcements.api import AnnouncementAdminViewSet
from backoffice import api_core, api_people

router = DefaultRouter()
router.register("announcements", AnnouncementAdminViewSet, basename="bo-announcements")

urlpatterns = [
    path("me/", api_core.me, name="bo-me"),
    path("dashboard/", api_core.DashboardView.as_view(), name="bo-dashboard"),
    # Utilisateurs
    path("users/", api_people.UserList.as_view(), name="bo-users"),
    path("users/<int:pk>/", api_people.UserDetail.as_view(), name="bo-user"),
    path("users/<int:pk>/suspend/", api_people.UserSuspend.as_view(), name="bo-user-suspend"),
    path("users/<int:pk>/reactivate/", api_people.UserReactivate.as_view(), name="bo-user-reactivate"),
    # KYC
    path("kyc/", api_people.KycList.as_view(), name="bo-kyc"),
    path("kyc/<int:pk>/", api_people.KycDetail.as_view(), name="bo-kyc-detail"),
    path("kyc/<int:pk>/approve/", api_people.KycProfileApprove.as_view(), name="bo-kyc-approve"),
    path("kyc/<int:pk>/suspend/", api_people.KycProfileSuspend.as_view(), name="bo-kyc-suspend"),
    path("kyc/documents/<int:pk>/file/", api_people.KycDocumentFile.as_view(), name="bo-kyc-file"),
    path("kyc/documents/<int:pk>/review/", api_people.KycDocumentReview.as_view(), name="bo-kyc-review"),
    # Tratra Trust
    path("trust/", api_people.TrustList.as_view(), name="bo-trust"),
    path("trust/config/", api_people.TrustConfigView.as_view(), name="bo-trust-config"),
    path("trust/<int:pk>/", api_people.TrustDetail.as_view(), name="bo-trust-detail"),
    path("trust/<int:pk>/reevaluate/", api_people.TrustReevaluate.as_view(), name="bo-trust-reevaluate"),
    # Tratra ID
    path("tratra-id/", api_people.TratraIdList.as_view(), name="bo-tratra-id"),
    path("tratra-id/stats/", api_people.TratraIdStats.as_view(), name="bo-tratra-id-stats"),
    path("tratra-id/<int:pk>/suspend/", api_people.TratraIdSuspend.as_view(), name="bo-tratra-id-suspend"),
    path("tratra-id/passes/<int:booking_id>/revoke/", api_people.MissionPassRevoke.as_view(), name="bo-mission-pass-revoke"),
    path("", include(router.urls)),
]
