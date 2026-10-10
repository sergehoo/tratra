import csv
from datetime import date, timedelta

from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from business import rbac, services
from business.models import (ApprovalRule, Budget, Building, ConsolidatedInvoice, Equipment, InterventionRequest, Invitation,
                             MaintenanceContract, Membership, Organization, PreventivePlan, Role, Site)
from business import serializers as ser
from handy.api.views import DefaultPageNumberPagination
from trust import identity
from trust.models import AuditEvent, audit


def _error(exc: services.BusinessError) -> Response:
    return Response(exc.payload(), status=exc.status)


class OrgMixin:
    """Résout l'organisation de l'URL via l'ADHÉSION du compte. Pas d'adhésion active = organisation inexistante (404) ;
    capacité manquante = 403. L'isolation entre organisations repose uniquement ici et dans les querysets."""
    permission_classes = [permissions.IsAuthenticated]
    read_cap = "view.structure"
    write_cap = None
    caps = {}  # action -> capacité (prioritaire)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.membership = rbac.membership_for(request.user, kwargs.get("org_id"))
        if self.membership is None:
            raise Http404
        self.org = self.membership.organization
        action_name = getattr(self, "action", None) or request.method.lower()
        cap = self.caps.get(action_name) or (self.read_cap if request.method in permissions.SAFE_METHODS else self.write_cap)
        if cap and not rbac.can(self.membership, cap):
            raise PermissionDenied("Votre rôle ne permet pas cette action.")

    def handle_exception(self, exc):
        if isinstance(exc, services.BusinessError):
            return _error(exc)
        return super().handle_exception(exc)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if hasattr(self, "org"):
            ctx.update(org=self.org, membership=self.membership)
        return ctx


class OrgModelViewSet(OrgMixin, viewsets.ModelViewSet):
    model = None
    pagination_class = None
    audit_name = ""

    def get_queryset(self):
        return self.model.objects.filter(organization=self.org)

    def perform_create(self, serializer):
        obj = serializer.save(organization=self.org)
        audit(f"{self.audit_name}.created", actor=self.request.user, target=obj, organization_id=self.org.id)

    def perform_update(self, serializer):
        obj = serializer.save()
        audit(f"{self.audit_name}.updated", actor=self.request.user, target=obj, organization_id=self.org.id)

    def perform_destroy(self, instance):
        audit(f"{self.audit_name}.deleted", actor=self.request.user, target=instance, organization_id=self.org.id)
        instance.delete()


# ---- Organisations --------------------------------------------------------------------------------------------------

class OrganizationListView(APIView):
    """GET : les organisations où l'on est membre actif (rôle et capacités inclus). POST : créer la sienne (propriétaire)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rows = []
        for m in (Membership.objects.filter(user=request.user, is_active=True, organization__is_active=True)
                  .select_related("organization").order_by("organization__name")):
            rows.append({**ser.OrganizationSerializer(m.organization).data, "role": m.role, "role_label": Role.LABELS[m.role],
                         "capabilities": sorted(rbac.capabilities(m)),
                         "scoped_sites": sorted(rbac.scoped_site_ids(m) or [])})
        return Response(rows)

    def post(self, request):
        s = ser.OrganizationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        org = services.create_organization(request.user, **s.validated_data)
        return Response(ser.OrganizationSerializer(org).data, status=status.HTTP_201_CREATED)


class OrganizationDetailView(OrgMixin, APIView):
    write_cap = "org.manage"

    def get(self, request, org_id):
        m = self.membership
        return Response({**ser.OrganizationSerializer(self.org).data, "role": m.role, "role_label": Role.LABELS[m.role],
                         "capabilities": sorted(rbac.capabilities(m)), "scoped_sites": sorted(rbac.scoped_site_ids(m) or [])})

    def patch(self, request, org_id):
        s = ser.OrganizationSerializer(self.org, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit("organization.updated", actor=request.user, target=self.org, organization_id=self.org.id)
        return Response(s.data)


class JoinView(APIView):
    """POST /business/join/ {code} — rejoindre une organisation avec le code reçu (compte connecté)."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "login"  # limite anti-devinette des codes

    def post(self, request):
        try:
            m = services.join_with_code(request.user, request.data.get("code", ""))
        except services.BusinessError as e:
            return _error(e)
        return Response({"organization": m.organization_id, "name": m.organization.name, "role": m.role}, status=201)


# ---- Membres, invitations -------------------------------------------------------------------------------------------

class MemberViewSet(OrgMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = ser.MemberSerializer
    write_cap = "members.manage"
    read_cap = "members.manage"
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Membership.objects.filter(organization=self.org).select_related("user").prefetch_related("sites").order_by("created_at")

    def _guard(self, obj):
        if obj.role == Role.OWNER:
            raise services.BusinessError("owner_protected", "Le propriétaire ne peut être ni modifié ni retiré.", 409)

    def perform_update(self, serializer):
        self._guard(serializer.instance)
        obj = serializer.save()
        audit("member.updated", actor=self.request.user, target=obj, organization_id=self.org.id, role=obj.role, active=obj.is_active)

    def perform_destroy(self, instance):
        self._guard(instance)
        instance.is_active = False  # désactivation : l'historique et les audits restent
        instance.save()
        audit("member.removed", actor=self.request.user, target=instance, organization_id=self.org.id)


class InvitationViewSet(OrgMixin, viewsets.ViewSet):
    write_cap = read_cap = "members.manage"

    def list(self, request, org_id):
        rows = Invitation.objects.filter(organization=self.org).order_by("-created_at")[:100]
        return Response([{"id": i.id, "role": i.role, "label": i.label, "expires_at": i.expires_at,
                          "status": ("accepted" if i.accepted_at else "revoked" if i.revoked_at else
                                     "expired" if i.expires_at <= timezone.now() else "pending")} for i in rows])

    def create(self, request, org_id):
        role = request.data.get("role", Role.REQUESTER)
        if role not in Role.ALL:
            raise services.BusinessError("invalid_role", "Rôle inconnu.")
        site_ids = request.data.get("sites") or []
        sites = list(Site.objects.filter(organization=self.org, id__in=site_ids))
        if len(sites) != len(set(site_ids)):
            raise services.BusinessError("invalid_site", "Site introuvable dans cette organisation.")
        data = services.create_invitation(self.org, request.user, role=role, sites=sites, label=str(request.data.get("label", ""))[:120])
        response = Response(data, status=201)  # le code n'est affiché qu'ici, une seule fois
        response["Cache-Control"] = "private, no-store"
        return response

    def destroy(self, request, org_id, pk=None):
        inv = Invitation.objects.filter(organization=self.org, pk=pk, accepted_at__isnull=True).first()
        if inv is None:
            raise Http404
        inv.revoked_at = timezone.now()
        inv.save(update_fields=["revoked_at"])
        audit("member.invitation_revoked", actor=request.user, target=self.org, organization_id=self.org.id)
        return Response(status=204)


# ---- Structure : sites, bâtiments, équipements ----------------------------------------------------------------------

class SiteViewSet(OrgModelViewSet):
    model, serializer_class, write_cap, audit_name = Site, ser.SiteSerializer, "sites.manage", "site"

    def get_queryset(self):
        qs = Site.objects.filter(organization=self.org).annotate(equipment_count=Count("equipment", distinct=True))
        scope = rbac.scoped_site_ids(self.membership)
        return qs.filter(id__in=scope) if scope is not None else qs


class BuildingViewSet(OrgModelViewSet):
    model, serializer_class, write_cap, audit_name = Building, ser.BuildingSerializer, "sites.manage", "building"

    def get_queryset(self):
        qs = Building.objects.filter(site__organization=self.org).select_related("site")
        scope = rbac.scoped_site_ids(self.membership)
        qs = qs.filter(site_id__in=scope) if scope is not None else qs
        return qs.filter(site_id=self.request.query_params["site"]) if self.request.query_params.get("site", "").isdigit() else qs

    def perform_create(self, serializer):
        obj = serializer.save()
        audit("building.created", actor=self.request.user, target=obj, organization_id=self.org.id)


class EquipmentViewSet(OrgModelViewSet):
    model, serializer_class, write_cap, audit_name = Equipment, ser.EquipmentSerializer, "equipment.manage", "equipment"

    def get_queryset(self):
        qs = Equipment.objects.filter(organization=self.org).select_related("site", "building", "category")
        scope = rbac.scoped_site_ids(self.membership)
        qs = qs.filter(site_id__in=scope) if scope is not None else qs
        p = self.request.query_params
        if p.get("site", "").isdigit():
            qs = qs.filter(site_id=p["site"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        return qs

    def perform_create(self, serializer):
        site = serializer.validated_data["site"]
        if not rbac.site_allowed(self.membership, site.id):
            raise PermissionDenied("Ce site ne fait pas partie de votre périmètre.")
        super().perform_create(serializer)

    @action(detail=True, methods=["get"], url_path="qr.png")
    def qr(self, request, org_id=None, pk=None):
        """QR imprimable de l'équipement : encode l'URL <site web>/equipment/<code> (aucune donnée sensible)."""
        eq = self.get_object()
        response = HttpResponse(identity.qr_png(f"{identity.settings.PUBLIC_WEB_URL}/equipment/{eq.qr_code}"), content_type="image/png")
        response["Cache-Control"] = "private, max-age=3600"
        return response


class EquipmentLookupView(APIView):
    """GET /business/equipment/lookup/<code>/ — scan d'un QR d'équipement. Visible UNIQUEMENT par les membres de son
    organisation (périmètre de site respecté) ; tout autre compte reçoit 404, comme pour un code inconnu."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "verify"

    def get(self, request, code):
        eq = Equipment.objects.select_related("site", "building", "category", "organization").filter(qr_code=(code or "").upper()).first()
        m = rbac.membership_for(request.user, eq.organization_id) if eq else None
        if eq is None or m is None or not rbac.can(m, "view.structure") or not rbac.site_allowed(m, eq.site_id):
            raise Http404
        return Response({**ser.EquipmentSerializer(eq, context={"org": eq.organization}).data, "organization": eq.organization_id,
                         "organization_name": eq.organization.name,
                         "can_request": rbac.can(m, "requests.create"),
                         "open_requests": eq.requests.filter(status__in=InterventionRequest.OPEN).count()})


# ---- Validation, contrats, préventif, budgets -----------------------------------------------------------------------------

class ApprovalRuleViewSet(OrgModelViewSet):
    model, serializer_class, audit_name = ApprovalRule, ser.ApprovalRuleSerializer, "approval_rule"
    read_cap = write_cap = "approval_rules.manage"


class ContractViewSet(OrgModelViewSet):
    model, serializer_class, write_cap, audit_name = MaintenanceContract, ser.ContractSerializer, "contracts.manage", "contract"
    read_cap = "view.structure"


class PreventivePlanViewSet(OrgModelViewSet):
    model, serializer_class, write_cap, audit_name = PreventivePlan, ser.PreventivePlanSerializer, "preventive.manage", "preventive_plan"

    def get_queryset(self):
        qs = PreventivePlan.objects.filter(organization=self.org).select_related("equipment")
        scope = rbac.scoped_site_ids(self.membership)
        return qs.filter(equipment__site_id__in=scope) if scope is not None else qs

    @action(detail=False, methods=["post"])
    def run(self, request, org_id=None):
        """Génère maintenant les demandes de maintenance préventive échues de cette organisation (idempotent)."""
        n = services.run_preventive()
        return Response({"created": n})


class BudgetViewSet(OrgModelViewSet):
    model, serializer_class, write_cap, audit_name = Budget, ser.BudgetSerializer, "budgets.manage", "budget"
    read_cap = "reports.view"


# ---- Demandes d'intervention ----------------------------------------------------------------------------------------------

class RequestViewSet(OrgMixin, viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin):
    serializer_class = ser.RequestSerializer
    pagination_class = DefaultPageNumberPagination
    read_cap = None  # chacun voit ses demandes ; l'étendue est fixée par get_queryset
    caps = {"create": "requests.create", "suggestions": "requests.dispatch", "send_to_artisan": "requests.dispatch",
            "decide": "requests.approve"}

    def get_queryset(self):
        qs = services.scoped_requests(self.org, self.membership).select_related(
            "site", "equipment", "category", "requested_by", "contract", "booking").prefetch_related("steps", "steps__decided_by")
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("priority"):
            qs = qs.filter(priority=p["priority"])
        if p.get("site", "").isdigit():
            qs = qs.filter(site_id=p["site"])
        if p.get("mine") in ("1", "true"):
            qs = qs.filter(requested_by=self.request.user)
        if p.get("to_approve") in ("1", "true"):
            ids = [r.id for r in qs.filter(status="pending_approval") if services.can_decide(self.membership, r)]
            qs = qs.filter(id__in=ids)
        if p.get("q"):
            qs = qs.filter(Q(title__icontains=p["q"]) | Q(number__icontains=p["q"]))
        return qs

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        req = services.create_request(
            self.org, request.user, self.membership, site=d["site"], title=d["title"], description=d.get("description", ""),
            category=d.get("category"), equipment=d.get("equipment"), priority=d.get("priority", "normal"),
            desired_date=d.get("desired_date"), estimated_cost=d.get("estimated_cost"),
            source="qr" if request.data.get("from_qr") in (True, "true", "1") else "manual")
        return Response(self.get_serializer(req).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def decide(self, request, org_id=None, pk=None):
        """POST {approve: true|false, comment} — valide ou refuse l'étape en attente (rôle et site contrôlés)."""
        req = self.get_object()
        approve = request.data.get("approve")
        if not isinstance(approve, bool):
            raise services.BusinessError("invalid", "approve (booléen) requis.")
        req = services.decide(req, request.user, self.membership, approve=approve, comment=str(request.data.get("comment", ""))[:500])
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, org_id=None, pk=None):
        req = self.get_object()
        if req.status not in ("pending_approval", "approved", "dispatched", "scheduled"):
            raise services.BusinessError("not_cancellable", "Cette demande ne peut plus être annulée.", 409)
        own = req.requested_by_id == request.user.id and req.status in ("pending_approval", "approved")
        if not (own or rbac.can(self.membership, "requests.dispatch") or rbac.can(self.membership, "org.manage")):
            raise PermissionDenied("Vous ne pouvez pas annuler cette demande.")
        return Response(self.get_serializer(services.cancel_request(req, request.user)).data)

    @action(detail=True, methods=["get"])
    def suggestions(self, request, org_id=None, pk=None):
        req = self.get_object()
        return Response({"results": services.suggest_artisans(req, limit=8)})

    @action(detail=True, methods=["post"], url_path="dispatch", url_name="dispatch")
    def send_to_artisan(self, request, org_id=None, pk=None):
        """POST {artisan: <user_id>} ou {auto: true} — crée la réservation de l'artisan éligible choisi."""
        req = self.get_object()
        artisan = request.data.get("artisan")
        when = request.data.get("when")
        parsed = None
        if when:
            from django.utils.dateparse import parse_datetime
            parsed = parse_datetime(str(when))
            if parsed is None:
                raise services.BusinessError("invalid", "Date invalide.")
        req = services.dispatch(req, request.user, artisan_id=int(artisan) if str(artisan or "").isdigit() else None,
                                auto=request.data.get("auto") is True, when=parsed)
        return Response(self.get_serializer(req).data)


# ---- Facturation, tableau de bord, exports, audit --------------------------------------------------------------------

class InvoiceViewSet(OrgMixin, viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    serializer_class = ser.InvoiceSerializer
    pagination_class = None
    read_cap = write_cap = "invoices.manage"

    def get_queryset(self):
        return ConsolidatedInvoice.objects.filter(organization=self.org).prefetch_related("lines")

    @action(detail=False, methods=["post"])
    def generate(self, request, org_id=None):
        """POST {start, end} — relève les interventions terminées et chiffrées de la période (chacune une seule fois)."""
        start, end = parse_date(str(request.data.get("start", ""))), parse_date(str(request.data.get("end", "")))
        if not start or not end:
            raise services.BusinessError("invalid_period", "start et end (AAAA-MM-JJ) requis.")
        inv = services.generate_invoice(self.org, request.user, start, end)
        data = ser.InvoiceSerializer(inv).data
        data["skipped_unpriced"] = getattr(inv, "skipped", 0)
        return Response(data, status=201)

    @action(detail=True, methods=["get"], url_path="export.csv")
    def export(self, request, org_id=None, pk=None):
        inv = self.get_object()
        return _csv(f"{inv.number}.csv", ["Site", "Intervention", f"Montant ({self.org.currency})"],
                    [[l.site_name, l.description, l.amount] for l in inv.lines.all()] + [["", "TOTAL", inv.total]])


def _safe(cell):
    s = "" if cell is None else str(cell)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s  # neutralise l'injection de formules dans les tableurs


def _csv(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")
    w = csv.writer(response, delimiter=";")
    w.writerow(header)
    for r in rows:
        w.writerow([_safe(c) for c in r])
    return response


def _period(request):
    today = timezone.localdate()
    start = parse_date(request.query_params.get("from", "") or "") or today.replace(day=1)
    end = parse_date(request.query_params.get("to", "") or "") or today
    return start, end


class DashboardView(OrgMixin, APIView):
    read_cap = "reports.view"

    def get(self, request, org_id):
        start, end = _period(request)
        return Response(services.dashboard(self.org, self.membership, start, end))


class ReportRequestsView(OrgMixin, APIView):
    read_cap = "reports.view"

    def get(self, request, org_id):
        start, end = _period(request)
        qs = services.scoped_requests(self.org, self.membership).filter(created_at__date__gte=start, created_at__date__lte=end) \
            .select_related("site", "equipment", "category", "requested_by", "booking").order_by("created_at")
        rows = [[r.number, r.created_at.date(), r.site.name, r.equipment.name if r.equipment else "", r.title,
                 r.category.name if r.category else "", r.get_priority_display(), r.get_status_display(),
                 r.completed_at.date() if r.completed_at else "", services.request_cost(r) or "",
                 {True: "oui", False: "non", None: ""}[r.sla_resolution_met]] for r in qs]
        return _csv(f"interventions-{start}-{end}.csv",
                    ["N°", "Créée le", "Site", "Équipement", "Intitulé", "Catégorie", "Priorité", "Statut", "Terminée le",
                     f"Coût ({self.org.currency})", "SLA résolution tenu"], rows)


class AuditView(OrgMixin, APIView):
    read_cap = "audit.view"

    def get(self, request, org_id):
        rows = AuditEvent.objects.filter(organization_id=self.org.id).select_related("actor")[:200]
        return Response([{"at": e.created_at, "action": e.action, "actor": services._public_name(e.actor) if e.actor_id else "Système",
                          "target_type": e.target_type, "target_id": e.target_id,
                          "detail": {k: v for k, v in (e.data or {}).items() if k not in ("code",)}} for e in rows])
