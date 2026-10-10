"""Tratra Business : organisations multi-sites, équipements, demandes d'intervention validées, contrats, budgets.

Isolation stricte : TOUTE donnée appartient à une organisation ; l'accès passe exclusivement par une adhésion
(`Membership`) et ses capacités (business.rbac). Les interventions réutilisent les réservations existantes
(`handy.Booking`) : artisans éligibles seulement, paiements, KYC et abonnements ne sont jamais contournés."""
import secrets
from decimal import Decimal

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

User = settings.AUTH_USER_MODEL

QR_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_equipment_code() -> str:
    return "EQ-" + "".join(secrets.choice(QR_ALPHABET) for _ in range(4)) + "-" + "".join(secrets.choice(QR_ALPHABET) for _ in range(4))


class Organization(models.Model):
    name = models.CharField(max_length=150)
    legal_name = models.CharField(max_length=200, blank=True, default="")
    registration_number = models.CharField(max_length=50, blank=True, default="")  # RCCM / SIRET
    industry = models.CharField(max_length=100, blank=True, default="")
    address = models.TextField(blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    currency = models.CharField(max_length=3, default="XOF")
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="owned_organizations")
    # Entreprise existante (compte « entreprise ») : l'organisation en est le prolongement, jamais un doublon.
    company_profile = models.OneToOneField("handy.CompanyProfile", on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name="organization")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Role:
    OWNER, ADMIN, SITE_MANAGER, APPROVER, REQUESTER, FINANCE, VIEWER = (
        "owner", "admin", "site_manager", "approver", "requester", "finance", "viewer")
    CHOICES = [(OWNER, "Propriétaire"), (ADMIN, "Administrateur"), (SITE_MANAGER, "Responsable de site"),
               (APPROVER, "Validateur"), (REQUESTER, "Demandeur"), (FINANCE, "Finance"), (VIEWER, "Lecteur")]
    LABELS = dict(CHOICES)
    ALL = [c for c, _ in CHOICES]


class Site(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="sites")
    name = models.CharField(max_length=150)
    address = models.TextField(blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    postal_code = models.CharField(max_length=20, blank=True, default="")
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="biz_site_unique_name")]

    def __str__(self):
        return f"{self.name} ({self.organization})"


class Membership(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="business_memberships")
    role = models.CharField(max_length=20, choices=Role.CHOICES, default=Role.REQUESTER)
    # Périmètre : vide = tous les sites ; sinon uniquement ces sites (ignoré pour propriétaire et administrateur).
    sites = models.ManyToManyField(Site, blank=True, related_name="members")
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="biz_membership_unique")]

    def __str__(self):
        return f"{self.user} — {self.organization} ({self.role})"


class Invitation(models.Model):
    """Invitation par CODE (aucune recherche de compte par téléphone/e-mail : pas d'énumération). Le code, affiché une
    seule fois à l'invitant, est saisi par l'invité une fois connecté ; seule son empreinte est stockée."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    role = models.CharField(max_length=20, choices=Role.CHOICES, default=Role.REQUESTER)
    sites = models.ManyToManyField(Site, blank=True, related_name="+")
    label = models.CharField(max_length=120, blank=True, default="")
    code_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class Building(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="buildings")
    name = models.CharField(max_length=120)
    floors = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["site", "name"], name="biz_building_unique_name")]

    def __str__(self):
        return f"{self.name} — {self.site.name}"


class Equipment(models.Model):
    STATUSES = [("operational", "En service"), ("degraded", "Dégradé"), ("out_of_service", "Hors service"),
                ("retired", "Retiré")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="equipment")
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="equipment")
    building = models.ForeignKey(Building, on_delete=models.SET_NULL, null=True, blank=True, related_name="equipment")
    name = models.CharField(max_length=150)
    category = models.ForeignKey("handy.ServiceCategory", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    reference = models.CharField(max_length=80, blank=True, default="")      # numéro de série / inventaire
    location_detail = models.CharField(max_length=200, blank=True, default="")  # « Étage 2, local technique »
    installed_on = models.DateField(null=True, blank=True)
    warranty_ends_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="operational", db_index=True)
    qr_code = models.CharField(max_length=14, unique=True, editable=False, default=new_equipment_code)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.qr_code})"


class ApprovalRule(models.Model):
    """Validation hiérarchique CONFIGURABLE : selon le montant estimé, la priorité et le site, une suite de rôles à
    franchir dans l'ordre (ex. [« site_manager », « finance »]). Première règle applicable (ordre croissant)."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="approval_rules")
    name = models.CharField(max_length=120)
    order = models.PositiveSmallIntegerField(default=0)
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    max_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    priorities = models.JSONField(default=list, blank=True)  # vide = toutes
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    steps = models.JSONField(default=list)                   # rôles dans l'ordre ; vide = approbation automatique
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]


class MaintenanceContract(models.Model):
    STATUSES = [("active", "Actif"), ("expired", "Expiré"), ("cancelled", "Résilié")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="contracts")
    name = models.CharField(max_length=150)
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name="contracts")
    provider = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")  # artisan
    categories = models.ManyToManyField("handy.ServiceCategory", blank=True, related_name="+")
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    sla_response_hours = models.PositiveIntegerField(default=24)      # délai de prise en charge
    sla_resolution_hours = models.PositiveIntegerField(default=72)    # délai de résolution
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUSES, default="active", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_on", "-id"]

    def covers(self, on_date=None) -> bool:
        d = on_date or timezone.localdate()
        return self.status == "active" and self.starts_on <= d and (self.ends_on is None or d <= self.ends_on)


class PreventivePlan(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="preventive_plans")
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="preventive_plans")
    title = models.CharField(max_length=150)
    category = models.ForeignKey("handy.ServiceCategory", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    frequency_days = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    next_due_on = models.DateField()
    lead_days = models.PositiveSmallIntegerField(default=7)  # rappel et création de la demande X jours avant
    last_done_on = models.DateField(null=True, blank=True)
    contract = models.ForeignKey(MaintenanceContract, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="preventive_plans")
    is_active = models.BooleanField(default=True)
    last_generated_for = models.DateField(null=True, blank=True)  # échéance déjà transformée en demande
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["next_due_on", "id"]


class InterventionRequest(models.Model):
    PRIORITIES = [("low", "Basse"), ("normal", "Normale"), ("high", "Haute"), ("urgent", "Urgente")]
    STATUSES = [("pending_approval", "En attente de validation"), ("approved", "Validée"),
                ("dispatched", "Artisan sollicité"), ("scheduled", "Planifiée"), ("in_progress", "En cours"),
                ("completed", "Terminée"), ("rejected", "Refusée"), ("cancelled", "Annulée")]
    OPEN = ("pending_approval", "approved", "dispatched", "scheduled", "in_progress")
    SOURCES = [("manual", "Saisie"), ("qr", "QR équipement"), ("preventive", "Maintenance préventive")]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="requests")
    number = models.CharField(max_length=24, db_index=True)  # INT-2026-0001, unique PAR organisation
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="requests")
    equipment = models.ForeignKey(Equipment, on_delete=models.SET_NULL, null=True, blank=True, related_name="requests")
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="business_requests")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey("handy.ServiceCategory", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="normal", db_index=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="pending_approval", db_index=True)
    source = models.CharField(max_length=12, choices=SOURCES, default="manual")
    desired_date = models.DateTimeField(null=True, blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                         validators=[MinValueValidator(0)])
    final_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    contract = models.ForeignKey(MaintenanceContract, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="requests")
    preventive_plan = models.ForeignKey(PreventivePlan, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="requests")
    booking = models.OneToOneField("handy.Booking", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="business_request")
    rejection_reason = models.TextField(blank=True, default="")
    due_response_at = models.DateTimeField(null=True, blank=True)    # SLA : prise en charge
    due_resolution_at = models.DateTimeField(null=True, blank=True)  # SLA : résolution
    responded_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["organization", "number"], name="biz_request_unique_number")]
        indexes = [models.Index(fields=["organization", "status"]), models.Index(fields=["organization", "site"])]

    def __str__(self):
        return f"{self.number} — {self.title}"

    @property
    def sla_response_met(self):
        if not self.due_response_at or not self.responded_at:
            return None
        return self.responded_at <= self.due_response_at

    @property
    def sla_resolution_met(self):
        if not self.due_resolution_at or not self.completed_at:
            return None
        return self.completed_at <= self.due_resolution_at


class ApprovalStep(models.Model):
    STATUSES = [("pending", "En attente"), ("approved", "Validée"), ("rejected", "Refusée")]
    request = models.ForeignKey(InterventionRequest, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField()
    role = models.CharField(max_length=20, choices=Role.CHOICES)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["request", "order"], name="biz_step_unique_order")]


class Budget(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="budgets")
    name = models.CharField(max_length=150)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True, related_name="budgets")
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, null=True, blank=True, related_name="budgets")
    period_start = models.DateField()
    period_end = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    alert_threshold_pct = models.PositiveSmallIntegerField(default=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "id"]


class ConsolidatedInvoice(models.Model):
    """Relevé facturable regroupant les interventions terminées d'une période. Il n'encaisse rien et n'active rien :
    les paiements restent portés par les réservations (escrow) ; chaque intervention n'est facturée qu'une fois."""
    STATUSES = [("issued", "Émise"), ("void", "Annulée")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invoices")
    number = models.CharField(max_length=30)
    period_start = models.DateField()
    period_end = models.DateField()
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    status = models.CharField(max_length=10, choices=STATUSES, default="issued")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["organization", "number"], name="biz_invoice_unique_number")]


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(ConsolidatedInvoice, on_delete=models.CASCADE, related_name="lines")
    request = models.OneToOneField(InterventionRequest, on_delete=models.PROTECT, related_name="invoice_line")
    site_name = models.CharField(max_length=150)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
