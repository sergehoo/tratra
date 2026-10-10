from rest_framework import serializers

from business import rbac, services
from business.models import (ApprovalRule, ApprovalStep, Budget, Building, ConsolidatedInvoice, Equipment, InterventionRequest,
                             InvoiceLine, MaintenanceContract, Membership, Organization, PreventivePlan, Role, Site)
from handy.models import ServiceCategory


class OrgScopedMixin:
    """Toute clé étrangère doit appartenir à L'ORGANISATION courante (isolation stricte : jamais de référence croisée)."""

    def _same_org(self, obj, label="Objet"):
        org = self.context["org"]
        owner_id = getattr(obj, "organization_id", None) or getattr(getattr(obj, "site", None), "organization_id", None)
        if obj is not None and owner_id != org.id:
            raise serializers.ValidationError(f"{label} introuvable dans cette organisation.")
        return obj


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "legal_name", "registration_number", "industry", "address", "city", "phone", "currency",
                  "created_at"]
        read_only_fields = ["id", "created_at"]


class SiteSerializer(serializers.ModelSerializer):
    lat = serializers.FloatField(required=False, allow_null=True, write_only=True, min_value=-90, max_value=90)
    lng = serializers.FloatField(required=False, allow_null=True, write_only=True, min_value=-180, max_value=180)
    location = serializers.SerializerMethodField()
    equipment_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Site
        fields = ["id", "name", "address", "city", "postal_code", "notes", "is_active", "location", "lat", "lng",
                  "equipment_count"]
        read_only_fields = ["id"]

    def get_location(self, obj):
        return {"lat": obj.location.y, "lng": obj.location.x} if obj.location else None

    def _apply_point(self, validated):
        from django.contrib.gis.geos import Point
        lat, lng = validated.pop("lat", None), validated.pop("lng", None)
        if lat is not None and lng is not None:
            validated["location"] = Point(lng, lat, srid=4326)
        return validated

    def create(self, validated):
        return super().create(self._apply_point(validated))

    def update(self, instance, validated):
        return super().update(instance, self._apply_point(validated))


class BuildingSerializer(OrgScopedMixin, serializers.ModelSerializer):
    class Meta:
        model = Building
        fields = ["id", "site", "name", "floors"]

    def validate_site(self, site):
        return self._same_org(site, "Site")


class EquipmentSerializer(OrgScopedMixin, serializers.ModelSerializer):
    site_name = serializers.CharField(source="site.name", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True, default=None)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)

    class Meta:
        model = Equipment
        fields = ["id", "name", "site", "site_name", "building", "building_name", "category", "category_name", "reference",
                  "location_detail", "installed_on", "warranty_ends_on", "status", "qr_code", "notes"]
        read_only_fields = ["id", "qr_code"]

    def validate_site(self, site):
        return self._same_org(site, "Site")

    def validate_building(self, building):
        return self._same_org(building, "Bâtiment") if building else building

    def validate(self, attrs):
        site, building = attrs.get("site") or getattr(self.instance, "site", None), attrs.get("building")
        if building is not None and site is not None and building.site_id != site.id:
            raise serializers.ValidationError({"building": "Ce bâtiment n'appartient pas à ce site."})
        return attrs


class MemberSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(read_only=True)
    display_name = serializers.SerializerMethodField()
    role_label = serializers.SerializerMethodField()
    sites = serializers.PrimaryKeyRelatedField(many=True, queryset=Site.objects.all(), required=False)

    class Meta:
        model = Membership
        fields = ["id", "user_id", "display_name", "role", "role_label", "sites", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_display_name(self, obj):
        return services._public_name(obj.user)

    def get_role_label(self, obj):
        return Role.LABELS.get(obj.role, obj.role)

    def validate_sites(self, sites):
        org = self.context["org"]
        if any(s.organization_id != org.id for s in sites):
            raise serializers.ValidationError("Site introuvable dans cette organisation.")
        return sites

    def validate_role(self, role):
        if role == Role.OWNER:
            raise serializers.ValidationError("Le rôle propriétaire ne s'attribue pas.")
        return role


class ApprovalRuleSerializer(OrgScopedMixin, serializers.ModelSerializer):
    class Meta:
        model = ApprovalRule
        fields = ["id", "name", "order", "min_amount", "max_amount", "priorities", "site", "steps", "is_active"]

    def validate_site(self, site):
        return self._same_org(site, "Site") if site else site

    def validate_steps(self, steps):
        if not isinstance(steps, list) or any(s not in Role.ALL or s in (Role.VIEWER, Role.REQUESTER) for s in steps):
            raise serializers.ValidationError("Chaque étape doit être un rôle habilité à valider "
                                              "(propriétaire, administrateur, responsable de site, validateur, finance).")
        return steps

    def validate_priorities(self, priorities):
        valid = {p for p, _ in InterventionRequest.PRIORITIES}
        if not isinstance(priorities, list) or any(p not in valid for p in priorities):
            raise serializers.ValidationError("Priorités invalides.")
        return priorities

    def validate(self, attrs):
        lo, hi = attrs.get("min_amount", 0), attrs.get("max_amount")
        if hi is not None and hi < lo:
            raise serializers.ValidationError({"max_amount": "Le plafond est inférieur au minimum."})
        return attrs


class ContractSerializer(OrgScopedMixin, serializers.ModelSerializer):
    provider_name = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceContract
        fields = ["id", "name", "site", "provider", "provider_name", "categories", "starts_on", "ends_on",
                  "sla_response_hours", "sla_resolution_hours", "notes", "status"]
        read_only_fields = ["id"]

    def get_provider_name(self, obj):
        return services._public_name(obj.provider) if obj.provider_id else None

    def validate_site(self, site):
        return self._same_org(site, "Site") if site else site

    def validate_provider(self, user):
        from handy.eligibility import is_user_publishable
        if user is not None and not is_user_publishable(user):
            raise serializers.ValidationError("Ce prestataire n'est pas éligible (identité vérifiée requise).")
        return user

    def validate(self, attrs):
        s, e = attrs.get("starts_on"), attrs.get("ends_on")
        if s and e and e < s:
            raise serializers.ValidationError({"ends_on": "La fin précède le début."})
        return attrs


class PreventivePlanSerializer(OrgScopedMixin, serializers.ModelSerializer):
    equipment_name = serializers.CharField(source="equipment.name", read_only=True)

    class Meta:
        model = PreventivePlan
        fields = ["id", "equipment", "equipment_name", "title", "category", "frequency_days", "next_due_on", "lead_days",
                  "last_done_on", "contract", "is_active"]
        read_only_fields = ["id", "last_done_on"]

    def validate_equipment(self, eq):
        return self._same_org(eq, "Équipement")

    def validate_contract(self, contract):
        return self._same_org(contract, "Contrat") if contract else contract


class BudgetSerializer(OrgScopedMixin, serializers.ModelSerializer):
    status = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = ["id", "name", "site", "equipment", "period_start", "period_end", "amount", "alert_threshold_pct", "status"]
        read_only_fields = ["id"]

    def get_status(self, obj):
        return services.budget_status(obj)

    def validate_site(self, site):
        return self._same_org(site, "Site") if site else site

    def validate_equipment(self, eq):
        return self._same_org(eq, "Équipement") if eq else eq

    def validate(self, attrs):
        s, e = attrs.get("period_start"), attrs.get("period_end")
        if s and e and e < s:
            raise serializers.ValidationError({"period_end": "La fin précède le début."})
        return attrs


class StepSerializer(serializers.ModelSerializer):
    role_label = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalStep
        fields = ["order", "role", "role_label", "status", "decided_by_name", "decided_at", "comment"]

    def get_role_label(self, obj):
        return Role.LABELS.get(obj.role, obj.role)

    def get_decided_by_name(self, obj):
        return services._public_name(obj.decided_by) if obj.decided_by_id else None


class RequestSerializer(OrgScopedMixin, serializers.ModelSerializer):
    site_name = serializers.CharField(source="site.name", read_only=True)
    equipment_name = serializers.CharField(source="equipment.name", read_only=True, default=None)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    requested_by_name = serializers.SerializerMethodField()
    steps = StepSerializer(many=True, read_only=True)
    cost = serializers.SerializerMethodField()
    sla = serializers.SerializerMethodField()
    can_decide = serializers.SerializerMethodField()
    booking_id = serializers.IntegerField(read_only=True)
    budget_warnings = serializers.SerializerMethodField()

    class Meta:
        model = InterventionRequest
        fields = ["id", "number", "site", "site_name", "equipment", "equipment_name", "title", "description", "category",
                  "category_name", "priority", "status", "source", "desired_date", "estimated_cost", "cost", "contract",
                  "booking_id", "requested_by_name", "rejection_reason", "steps", "sla", "can_decide", "budget_warnings",
                  "created_at", "completed_at"]
        read_only_fields = ["id", "number", "status", "source", "contract", "rejection_reason", "created_at", "completed_at"]

    def validate_site(self, site):
        return self._same_org(site, "Site")

    def validate_equipment(self, eq):
        return self._same_org(eq, "Équipement") if eq else eq

    def validate(self, attrs):
        eq, site = attrs.get("equipment"), attrs.get("site")
        if eq is not None and site is not None and eq.site_id != site.id:
            raise serializers.ValidationError({"equipment": "Cet équipement n'est pas sur ce site."})
        return attrs

    def get_requested_by_name(self, obj):
        return services._public_name(obj.requested_by)

    def get_cost(self, obj):
        return services.request_cost(obj)

    def get_sla(self, obj):
        return {"due_response_at": obj.due_response_at, "due_resolution_at": obj.due_resolution_at,
                "response_met": obj.sla_response_met, "resolution_met": obj.sla_resolution_met}

    def get_can_decide(self, obj):
        m = self.context.get("membership")
        return bool(m and services.can_decide(m, obj))

    def get_budget_warnings(self, obj):
        m = self.context.get("membership")
        if not (m and rbac.can(m, "requests.view_all")) or obj.status not in ("pending_approval", "approved"):
            return []
        return services.budget_warnings(obj)


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ["site_name", "description", "amount", "request"]


class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model = ConsolidatedInvoice
        fields = ["id", "number", "period_start", "period_end", "total", "status", "created_at", "lines"]
