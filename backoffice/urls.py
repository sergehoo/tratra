from django.urls import include, path
from rest_framework.routers import DefaultRouter

from announcements.api import AnnouncementAdminViewSet
from backoffice import api_core, api_money, api_ops, api_people, api_system

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
    # Tratra Business (supervision)
    path("business/organizations/", api_money.OrganizationList.as_view(), name="bo-organizations"),
    path("business/organizations/<int:pk>/", api_money.OrganizationDetail.as_view(), name="bo-organization"),
    path("business/organizations/<int:pk>/suspend/", api_money.OrganizationSuspend.as_view(), name="bo-organization-suspend"),
    path("business/organizations/<int:pk>/reactivate/", api_money.OrganizationReactivate.as_view(), name="bo-organization-reactivate"),
    path("business/requests/", api_money.BusinessRequestList.as_view(), name="bo-business-requests"),
    path("business/invoices/", api_money.BusinessInvoiceList.as_view(), name="bo-business-invoices"),
    # Finances
    path("finance/summary/", api_money.FinanceSummary.as_view(), name="bo-finance-summary"),
    path("finance/payments/", api_money.PaymentList.as_view(), name="bo-payments"),
    path("finance/payments/<int:pk>/", api_money.PaymentDetail.as_view(), name="bo-payment"),
    path("finance/payments/<int:pk>/refund/", api_money.PaymentRefund.as_view(), name="bo-payment-refund"),
    path("finance/payouts/", api_money.PayoutList.as_view(), name="bo-payouts"),
    path("finance/payouts/<int:pk>/<str:op>/", api_money.PayoutDecision.as_view(), name="bo-payout-decision"),
    path("finance/invoices/", api_money.InvoiceList.as_view(), name="bo-invoices"),
    # Support
    path("support/queue/", api_money.SupportQueue.as_view(), name="bo-support-queue"),
    path("support/users/<int:pk>/", api_money.SupportOverview.as_view(), name="bo-support-user"),
    path("support/users/<int:pk>/notes/", api_money.SupportNotes.as_view(), name="bo-support-notes"),
    # Notifications
    path("notifications/summary/", api_system.NotificationSummary.as_view(), name="bo-notifications-summary"),
    path("notifications/", api_system.NotificationList.as_view(), name="bo-notifications"),
    # Continuité
    path("continuity/overview/", api_system.ContinuityOverview.as_view(), name="bo-continuity"),
    path("continuity/stuck/", api_system.ContinuityStuck.as_view(), name="bo-continuity-stuck"),
    # Statistiques et exports
    path("analytics/overview/", api_system.AnalyticsOverview.as_view(), name="bo-analytics"),
    path("analytics/export/<str:dataset>/", api_system.AnalyticsExport.as_view(), name="bo-export"),
    # Réglages
    path("settings/", api_system.SettingsOverview.as_view(), name="bo-settings"),
    path("settings/pricing-rules/", api_system.PricingRuleCreate.as_view(), name="bo-pricing-rules"),
    path("settings/pricing-rules/<int:pk>/", api_system.PricingRuleUpdate.as_view(), name="bo-pricing-rule"),
    path("settings/cancellation-policies/", api_system.CancellationPolicyUpsert.as_view(), name="bo-cancellation-policies"),
    path("settings/cancellation-policies/<int:pk>/", api_system.CancellationPolicyUpsert.as_view(), name="bo-cancellation-policy"),
    path("settings/trust/", api_system.TrustSettingsUpdate.as_view(), name="bo-settings-trust"),
    path("settings/coupons/", api_system.CouponList.as_view(), name="bo-coupons"),
    path("settings/coupons/<int:pk>/", api_system.CouponUpdate.as_view(), name="bo-coupon"),
    # Sécurité
    path("security/roles/", api_system.RoleList.as_view(), name="bo-roles"),
    path("security/staff/", api_system.StaffList.as_view(), name="bo-staff"),
    path("security/staff/<int:pk>/roles/", api_system.StaffRoles.as_view(), name="bo-staff-roles"),
    path("security/staff/<int:pk>/remove/", api_system.StaffRemove.as_view(), name="bo-staff-remove"),
    path("security/sessions/", api_system.SessionList.as_view(), name="bo-sessions"),
    path("security/sessions/<int:pk>/revoke/", api_system.SessionRevoke.as_view(), name="bo-session-revoke"),
    path("security/users/<int:pk>/revoke-sessions/", api_system.UserSessionsRevoke.as_view(), name="bo-user-sessions-revoke"),
    path("security/audit/", api_system.AuditList.as_view(), name="bo-audit"),
    path("security/audit/actions/", api_system.AuditActions.as_view(), name="bo-audit-actions"),
    path("", include(router.urls)),
]
