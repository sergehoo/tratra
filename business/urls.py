from django.urls import include, path
from rest_framework.routers import DefaultRouter

from business import views

router = DefaultRouter()
router.register("sites", views.SiteViewSet, basename="biz-sites")
router.register("buildings", views.BuildingViewSet, basename="biz-buildings")
router.register("equipment", views.EquipmentViewSet, basename="biz-equipment")
router.register("members", views.MemberViewSet, basename="biz-members")
router.register("approval-rules", views.ApprovalRuleViewSet, basename="biz-rules")
router.register("contracts", views.ContractViewSet, basename="biz-contracts")
router.register("preventive-plans", views.PreventivePlanViewSet, basename="biz-preventive")
router.register("budgets", views.BudgetViewSet, basename="biz-budgets")
router.register("requests", views.RequestViewSet, basename="biz-requests")
router.register("invoices", views.InvoiceViewSet, basename="biz-invoices")

urlpatterns = [
    path("business/orgs/", views.OrganizationListView.as_view(), name="biz-orgs"),
    path("business/join/", views.JoinView.as_view(), name="biz-join"),
    path("business/equipment/lookup/<str:code>/", views.EquipmentLookupView.as_view(), name="biz-equipment-lookup"),
    path("business/orgs/<int:org_id>/", views.OrganizationDetailView.as_view(), name="biz-org"),
    path("business/orgs/<int:org_id>/invitations/", views.InvitationViewSet.as_view({"get": "list", "post": "create"}), name="biz-invitations"),
    path("business/orgs/<int:org_id>/invitations/<int:pk>/", views.InvitationViewSet.as_view({"delete": "destroy"}), name="biz-invitation"),
    path("business/orgs/<int:org_id>/dashboard/", views.DashboardView.as_view(), name="biz-dashboard"),
    path("business/orgs/<int:org_id>/reports/requests.csv", views.ReportRequestsView.as_view(), name="biz-report-requests"),
    path("business/orgs/<int:org_id>/audit/", views.AuditView.as_view(), name="biz-audit"),
    # fichiers sans barre finale (images, exports)
    path("business/orgs/<int:org_id>/equipment/<int:pk>/qr.png", views.EquipmentViewSet.as_view({"get": "qr"}), name="biz-equipment-qr"),
    path("business/orgs/<int:org_id>/invoices/<int:pk>/export.csv", views.InvoiceViewSet.as_view({"get": "export"}), name="biz-invoice-csv"),
    path("business/orgs/<int:org_id>/", include(router.urls)),
]
