from django.urls import include, path
from rest_framework.routers import DefaultRouter

from announcements.api import AnnouncementAdminViewSet
from backoffice import api_core, api_ops, api_people

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
    # Services
    path("services/", api_ops.ServiceList.as_view(), name="bo-services"),
    path("services/categories/", api_ops.CategoryList.as_view(), name="bo-categories"),
    path("services/categories/<int:pk>/", api_ops.CategoryDetail.as_view(), name="bo-category"),
    path("services/<int:pk>/", api_ops.ServiceDetail.as_view(), name="bo-service"),
    path("services/<int:pk>/hide/", api_ops.ServiceHide.as_view(), name="bo-service-hide"),
    path("services/<int:pk>/restore/", api_ops.ServiceRestore.as_view(), name="bo-service-restore"),
    # Réservations et litiges
    path("bookings/", api_ops.BookingList.as_view(), name="bo-bookings"),
    path("bookings/<int:pk>/", api_ops.BookingDetail.as_view(), name="bo-booking"),
    path("bookings/<int:pk>/cancel/", api_ops.BookingCancel.as_view(), name="bo-booking-cancel"),
    path("disputes/", api_ops.DisputeList.as_view(), name="bo-disputes"),
    path("disputes/<int:pk>/", api_ops.DisputeDetail.as_view(), name="bo-dispute"),
    path("disputes/<int:pk>/<str:op>/", api_ops.DisputeAction.as_view(), name="bo-dispute-action"),
    # Suivi en direct
    path("live/", api_ops.LiveList.as_view(), name="bo-live"),
    path("live/<int:booking_id>/", api_ops.LiveDetail.as_view(), name="bo-live-detail"),
    path("live/<int:booking_id>/position/", api_ops.LivePositionAccess.as_view(), name="bo-live-position"),
    # Avis et signalements
    path("reviews/", api_ops.ReviewList.as_view(), name="bo-reviews"),
    path("reviews/reports/", api_ops.ReportList.as_view(), name="bo-reports"),
    path("reviews/reports/<int:pk>/resolve/", api_ops.ReportResolve.as_view(), name="bo-report-resolve"),
    path("reviews/<int:pk>/", api_ops.ReviewDetail.as_view(), name="bo-review"),
    path("reviews/<int:pk>/hide/", api_ops.ReviewHide.as_view(), name="bo-review-hide"),
    path("reviews/<int:pk>/restore/", api_ops.ReviewRestore.as_view(), name="bo-review-restore"),
    path("", include(router.urls)),
]
