"""Prestations récurrentes et engagements de longue durée.

Principes (voir engagements/services) :
 - une prestation PONCTUELLE reste une réservation (`handy.Booking`) ; une prestation RÉCURRENTE en génère une par occurrence
   si le contrat le demande (workflow, suivi, avis et litiges inchangés) ; un engagement LONGUE DURÉE est un contrat suivi
   par planning et échéances ;
 - Tratra ne verse ni n'encaisse la rémunération d'un contrat : les paiements sont DÉCLARÉS par une partie et ne comptent
   qu'une fois CONFIRMÉS par l'autre ; aucun calcul légal (cotisations, impôts, congés payés, salaire minimum) n'est fait ;
 - l'historique est en ajout seulement (jamais d'effacement), les montants sont figés par version de contrat."""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from handy.storage import KycPrivateStorage

MONEY = dict(max_digits=12, decimal_places=2)


def evidence_path(instance, filename):
    """Justificatif privé sous une clé opaque (le nom d'origine peut contenir une identité)."""
    contract_id = getattr(instance, "contract_id", None) or getattr(getattr(instance, "installment", None), "contract_id", "x")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"engagements/{contract_id}/{uuid.uuid4().hex}.{suffix[:5]}"


class EngagementRule(models.Model):
    """Règles de la plateforme paramétrables par catégorie (Back-Office). `is_default` = règle générale. Ce sont des règles
    de fonctionnement de Tratra, pas un avis juridique : l'emploi salarié est désactivé tant qu'on ne l'active pas."""
    category = models.ForeignKey("handy.ServiceCategory", null=True, blank=True, on_delete=models.CASCADE, related_name="engagement_rules")
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    allow_recurring = models.BooleanField(default=True)
    allow_long_term = models.BooleanField(default=True)
    allow_employment = models.BooleanField(default=False)
    max_duration_months = models.PositiveSmallIntegerField(default=60, validators=[MinValueValidator(1), MaxValueValidator(240)])
    min_notice_days_independent = models.PositiveSmallIntegerField(default=7, validators=[MaxValueValidator(365)])
    min_notice_days_employment = models.PositiveSmallIntegerField(default=30, validators=[MaxValueValidator(365)])
    commission_percent_independent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"), validators=[MinValueValidator(0), MaxValueValidator(50)])
    commission_percent_employment = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"), validators=[MinValueValidator(0), MaxValueValidator(50)])
    commission_payer = models.CharField(max_length=10, choices=[("principal", "Le donneur d'ordre"), ("worker", "Le prestataire")], default="principal")
    max_advance_percent = models.PositiveSmallIntegerField(default=50, validators=[MaxValueValidator(100)])
    late_grace_days = models.PositiveSmallIntegerField(default=5, validators=[MaxValueValidator(60)])
    min_days_for_evaluation = models.PositiveSmallIntegerField(default=30, validators=[MaxValueValidator(365)])
    evaluation_interval_days = models.PositiveSmallIntegerField(default=30, validators=[MaxValueValidator(365)])
    evaluation_edit_days = models.PositiveSmallIntegerField(default=7, validators=[MaxValueValidator(60)])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="eng_one_default_rule"),
            models.UniqueConstraint(fields=["category"], condition=Q(category__isnull=False), name="eng_one_rule_per_category"),
            models.CheckConstraint(check=Q(is_default=True, category__isnull=True) | Q(is_default=False, category__isnull=False), name="eng_rule_scope"),
        ]

    def __str__(self):
        return f"Règles {'générales' if self.is_default else self.category}"


# ═══ Besoins publiés, candidatures, entretiens ══════════════════════════════════════════════════════════════════════

class EngagementPosting(models.Model):
    MISSION_TYPES = [("recurring", "Récurrente"), ("long_term", "Longue durée")]
    RELATIONSHIPS = [("independent", "Prestation indépendante"), ("employment", "Emploi salarié")]
    PERIODS = [("monthly", "Par mois"), ("hourly", "À l'heure"), ("per_visit", "Par intervention")]
    STATUSES = [("draft", "Brouillon"), ("open", "Ouverte"), ("closed", "Clôturée"), ("filled", "Pourvue"), ("cancelled", "Annulée"), ("expired", "Expirée")]

    publisher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="engagement_postings")
    organization = models.ForeignKey("business.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="engagement_postings")
    category = models.ForeignKey("handy.ServiceCategory", on_delete=models.PROTECT, related_name="engagement_postings")
    title = models.CharField(max_length=160)
    description = models.TextField(max_length=4000)
    mission_type = models.CharField(max_length=12, choices=MISSION_TYPES)
    work_relationship = models.CharField(max_length=12, choices=RELATIONSHIPS, default="independent")
    city = models.CharField(max_length=100)
    location_note = models.CharField(max_length=200, blank=True, default="")     # quartier / zone : jamais d'adresse précise ni de coordonnées
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)                           # vide = durée indéterminée
    schedule = models.JSONField(default=list, blank=True)                        # [{weekday, start, end}]
    hours_per_week = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(null=True, blank=True, **MONEY)
    period = models.CharField(max_length=10, choices=PERIODS, default="monthly")
    currency = models.CharField(max_length=3, default="XOF")
    conditions = models.TextField(max_length=4000, blank=True, default="")
    benefits = models.TextField(max_length=2000, blank=True, default="")         # avantages (repas, transport, logement…), tels que déclarés
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(240)])
    employment_notice_ack = models.BooleanField(default=False)                   # mention légale reconnue (emploi salarié)
    application_deadline = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="draft", db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "category"]), models.Index(fields=["publisher", "status"])]

    def __str__(self):
        return f"Besoin #{self.pk} — {self.title}"


class EngagementApplication(models.Model):
    STATUSES = [("submitted", "Reçue"), ("shortlisted", "Présélectionnée"), ("interview", "Entretien"), ("selected", "Retenue"),
                ("rejected", "Refusée"), ("withdrawn", "Retirée")]
    OPEN = ("submitted", "shortlisted", "interview")

    posting = models.ForeignKey(EngagementPosting, on_delete=models.CASCADE, related_name="applications")
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="engagement_applications")
    message = models.TextField(max_length=2000, blank=True, default="")
    proposed_amount = models.DecimalField(null=True, blank=True, **MONEY)
    available_from = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default="submitted", db_index=True)
    decision_note = models.CharField(max_length=500, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["posting", "applicant"], name="eng_one_application_per_posting")]

    def __str__(self):
        return f"Candidature #{self.pk} au besoin #{self.posting_id}"


class EngagementInterview(models.Model):
    MODES = [("phone", "Téléphone"), ("video", "Visioconférence"), ("in_person", "En personne")]
    STATUSES = [("proposed", "Proposé"), ("confirmed", "Confirmé"), ("declined", "Refusé"), ("cancelled", "Annulé"), ("done", "Effectué")]

    application = models.ForeignKey(EngagementApplication, on_delete=models.CASCADE, related_name="interviews")
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=30, validators=[MinValueValidator(5), MaxValueValidator(480)])
    mode = models.CharField(max_length=10, choices=MODES, default="phone")
    place_note = models.CharField(max_length=200, blank=True, default="")        # « Bureau de Cocody », lien de visio : jamais de contact personnel
    status = models.CharField(max_length=10, choices=STATUSES, default="proposed", db_index=True)
    note = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_at", "id"]


# ═══ Contrat ════════════════════════════════════════════════════════════════════════════════════════════════════════

class EngagementContract(models.Model):
    MISSION_TYPES = EngagementPosting.MISSION_TYPES
    RELATIONSHIPS = EngagementPosting.RELATIONSHIPS
    PERIODS = EngagementPosting.PERIODS
    STATUSES = [
        ("draft", "Brouillon"), ("pending_acceptance", "Proposé, en attente d'acceptation"), ("accepted", "Accepté"),
        ("signed", "Signé, avant le début"), ("active", "En cours"), ("suspended", "Suspendu"), ("notice", "En préavis"),
        ("terminated", "Résilié"), ("completed", "Terminé"), ("cancelled", "Annulé avant le début"),
    ]
    # BROUILLON → PROPOSÉ → ACCEPTÉ → SIGNÉ (contrats établis sur un modèle validé juridiquement) → ACTIF → TERMINÉ / RÉSILIÉ.
    LIVE = ("accepted", "signed", "active", "suspended", "notice")          # engagement en vigueur ou sur le point de l'être
    ENDED = ("terminated", "completed", "cancelled")
    BOOKING_MODES = [("none", "Aucune réservation"), ("per_occurrence", "Une réservation par occurrence")]
    PRORATION = [("none", "Aucun prorata"), ("calendar_days", "Prorata des jours calendaires (dernière période)")]

    principal = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="engagements_as_principal")
    organization = models.ForeignKey("business.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="engagement_contracts")
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="engagements_as_worker")
    posting = models.ForeignKey(EngagementPosting, null=True, blank=True, on_delete=models.SET_NULL, related_name="contracts")
    application = models.OneToOneField(EngagementApplication, null=True, blank=True, on_delete=models.SET_NULL, related_name="contract")
    category = models.ForeignKey("handy.ServiceCategory", on_delete=models.PROTECT, related_name="engagement_contracts")
    service = models.ForeignKey("handy.Service", null=True, blank=True, on_delete=models.SET_NULL, related_name="engagement_contracts")

    mission_type = models.CharField(max_length=12, choices=MISSION_TYPES)
    work_relationship = models.CharField(max_length=12, choices=RELATIONSHIPS, default="independent")
    title = models.CharField(max_length=160)
    description = models.TextField(max_length=4000, blank=True, default="")      # missions confiées
    conditions = models.TextField(max_length=4000, blank=True, default="")
    benefits = models.TextField(max_length=2000, blank=True, default="")

    # Modèle juridique (validé par revue humaine) et articles FIGÉS à la proposition : c'est ce texte que les parties acceptent puis
    # signent. Sans modèle validé : ancien parcours (acceptation électronique simple, pas de signature ni de document scellé).
    template = models.ForeignKey("engagements.ContractTemplate", null=True, blank=True, on_delete=models.PROTECT, related_name="contracts")
    articles = models.JSONField(default=list, blank=True)
    signature_required = models.BooleanField(default=False)
    reference = models.CharField(max_length=24, unique=True, null=True, blank=True)   # TRT-CTR-AAAA-NNNNNN

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)                           # vide = durée indéterminée
    auto_renew = models.BooleanField(default=False)
    renewal_term_months = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(120)])
    renewal_count = models.PositiveSmallIntegerField(default=0)
    non_renewal_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    non_renewal_at = models.DateTimeField(null=True, blank=True)

    schedule = models.JSONField(default=list, blank=True)                        # [{weekday, start, end}]
    hours_per_week = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    location_city = models.CharField(max_length=100, blank=True, default="")
    location_address = models.CharField(max_length=255, blank=True, default="")  # connue des seules parties

    amount = models.DecimalField(**MONEY)
    period = models.CharField(max_length=10, choices=PERIODS, default="monthly")
    currency = models.CharField(max_length=3, default="XOF")
    payment_day = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(31)])
    proration_mode = models.CharField(max_length=14, choices=PRORATION, default="none")
    overtime_hourly_rate = models.DecimalField(null=True, blank=True, **MONEY)
    notice_period_days = models.PositiveSmallIntegerField(default=7)
    bookings_mode = models.CharField(max_length=14, choices=BOOKING_MODES, default="none")
    legal_notice_ack = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=STATUSES, default="draft", db_index=True)
    version = models.PositiveIntegerField(default=1)                              # écritures concurrentes
    terms_version = models.PositiveIntegerField(default=1)                        # +1 à chaque avenant appliqué
    terms_hash = models.CharField(max_length=64, blank=True, default="")

    notice_given_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    notice_given_at = models.DateTimeField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)                             # fin effective (préavis, résiliation, terme)
    end_reason = models.CharField(max_length=500, blank=True, default="")
    activated_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "start_date"]), models.Index(fields=["worker", "status"]), models.Index(fields=["principal", "status"])]
        constraints = [
            models.CheckConstraint(check=~Q(principal=models.F("worker")), name="eng_principal_not_worker"),
            models.CheckConstraint(check=Q(end_date__isnull=True) | Q(end_date__gte=models.F("start_date")), name="eng_end_after_start"),
            models.CheckConstraint(check=Q(amount__gte=0), name="eng_amount_gte_0"),
        ]

    def __str__(self):
        return f"Contrat #{self.pk} — {self.title}"

    @property
    def is_indefinite(self) -> bool:
        return self.end_date is None and self.ends_on is None

    @property
    def effective_end(self):
        """Dernier jour de l'engagement (préavis / résiliation prioritaires sur le terme) ; None = indéterminé."""
        return self.ends_on or self.end_date


class ContractAcceptance(models.Model):
    """Preuve d'acceptation d'une version des conditions par une partie (acceptation électronique simple, sans valeur de
    signature qualifiée) : qui, quand, quelle empreinte des conditions."""
    contract = models.ForeignKey(EngagementContract, on_delete=models.CASCADE, related_name="acceptances")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=10, choices=[("principal", "Donneur d'ordre"), ("worker", "Prestataire")])
    terms_version = models.PositiveIntegerField()
    terms_hash = models.CharField(max_length=64)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["accepted_at", "id"]
        constraints = [models.UniqueConstraint(fields=["contract", "role", "terms_version"], name="eng_one_acceptance_per_version")]


class ContractAmendment(models.Model):
    """Modification des conditions proposée par une partie, appliquée seulement après acceptation de l'autre."""
    KINDS = [("change", "Modification des conditions"), ("suspend", "Suspension"), ("end", "Fin d'un commun accord"),
             ("cancel_notice", "Annulation du préavis"), ("renewal", "Renouvellement")]
    STATUSES = [("proposed", "Proposé"), ("accepted", "Accepté"), ("rejected", "Refusé"), ("withdrawn", "Retiré"), ("applied", "Appliqué")]

    contract = models.ForeignKey(EngagementContract, on_delete=models.CASCADE, related_name="amendments")
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=14, choices=KINDS, default="change")
    changes = models.JSONField(default=dict)
    reason = models.CharField(max_length=500, blank=True, default="")
    effective_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUSES, default="proposed", db_index=True)
    responded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    responded_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class ContractSuspension(models.Model):
    contract = models.ForeignKey(EngagementContract, on_delete=models.CASCADE, related_name="suspensions")
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)                             # vide = jusqu'à la reprise
    reason = models.CharField(max_length=500, blank=True, default="")
    source = models.CharField(max_length=8, choices=[("agreed", "D'un commun accord"), ("admin", "Décision de la plateforme")], default="agreed")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_on", "id"]


class ContractEvent(models.Model):
    """Historique en AJOUT SEULEMENT du contrat (création, acceptations, avenants, renouvellements, suspensions, préavis…)."""
    contract = models.ForeignKey(EngagementContract, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    type = models.CharField(max_length=40, db_index=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["contract", "created_at"])]


# ═══ Rémunération ═══════════════════════════════════════════════════════════════════════════════════════════════════

class ContractInstallment(models.Model):
    STATUSES = [("scheduled", "Planifiée"), ("due", "À payer"), ("partial", "Partiellement payée"), ("paid", "Payée"), ("overdue", "En retard"),
                ("on_hold", "Suspendue"), ("waived", "Abandonnée"), ("cancelled", "Annulée")]
    OPEN = ("scheduled", "due", "partial", "overdue")

    contract = models.ForeignKey(EngagementContract, on_delete=models.CASCADE, related_name="installments")
    sequence = models.PositiveIntegerField()
    period_start = models.DateField()
    period_end = models.DateField()
    due_date = models.DateField(db_index=True)
    base_amount = models.DecimalField(null=True, blank=True, **MONEY)             # vide = à l'heure / à l'intervention, calculé en fin de période
    currency = models.CharField(max_length=3, default="XOF")
    terms_version = models.PositiveIntegerField(default=1)
    platform_fee = models.DecimalField(default=Decimal("0"), **MONEY)             # commission Tratra : distincte de la rémunération
    platform_fee_payer = models.CharField(max_length=10, default="principal")
    platform_fee_status = models.CharField(max_length=10, choices=[("none", "Sans objet"), ("due", "À régler"), ("settled", "Réglée"), ("waived", "Abandonnée")], default="none")
    status = models.CharField(max_length=10, choices=STATUSES, default="scheduled", db_index=True)
    computed_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True, default="")
    closed_reason = models.CharField(max_length=500, blank=True, default="")
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["contract_id", "sequence"]
        constraints = [models.UniqueConstraint(fields=["contract", "sequence"], name="eng_one_installment_per_sequence")]
        indexes = [models.Index(fields=["status", "due_date"])]

    def __str__(self):
        return f"Échéance {self.sequence} du contrat #{self.contract_id}"


class InstallmentLine(models.Model):
    """Ajustement d'une échéance (prime, frais remboursables, retenue convenue, heures supplémentaires, correction). Ne
    compte qu'une fois accepté par la contrepartie du proposant."""
    KINDS = [("bonus", "Prime"), ("expense", "Frais à rembourser"), ("deduction", "Retenue convenue"), ("overtime", "Heures supplémentaires"),
             ("correction", "Correction")]
    STATUSES = [("proposed", "Proposé"), ("accepted", "Accepté"), ("rejected", "Refusé")]

    installment = models.ForeignKey(ContractInstallment, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=12, choices=KINDS)
    amount = models.DecimalField(**MONEY)                                          # signé : négatif pour une retenue
    description = models.CharField(max_length=300)
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=STATUSES, default="proposed", db_index=True)
    responded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    responded_at = models.DateTimeField(null=True, blank=True)
    source_event = models.OneToOneField("engagements.ScheduleEvent", null=True, blank=True, on_delete=models.SET_NULL, related_name="payroll_line")
    evidence = models.FileField(upload_to=evidence_path, storage=KycPrivateStorage(), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class InstallmentPayment(models.Model):
    """Paiement DÉCLARÉ par une partie ; il ne compte qu'une fois CONFIRMÉ par l'autre (jamais de confirmation fictive)."""
    METHODS = [("cash", "Espèces"), ("bank_transfer", "Virement"), ("mobile_money", "Mobile Money"), ("other", "Autre")]
    STATUSES = [("declared", "Déclaré"), ("confirmed", "Confirmé"), ("rejected", "Contesté")]

    installment = models.ForeignKey(ContractInstallment, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(**MONEY)
    method = models.CharField(max_length=14, choices=METHODS)
    reference = models.CharField(max_length=100, blank=True, default="")
    paid_on = models.DateField()
    is_advance = models.BooleanField(default=False)
    declared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    declared_by_role = models.CharField(max_length=10, choices=[("principal", "Donneur d'ordre"), ("worker", "Prestataire")])
    declared_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="declared", db_index=True)
    responded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    responded_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True, default="")
    evidence = models.FileField(upload_to=evidence_path, storage=KycPrivateStorage(), null=True, blank=True)

    class Meta:
        ordering = ["paid_on", "id"]
        constraints = [models.CheckConstraint(check=Q(amount__gt=0), name="eng_payment_positive")]


# ═══ Planning ═══════════════════════════════════════════════════════════════════════════════════════════════════════

class ScheduleEvent(models.Model):
    KINDS = [("shift", "Intervention"), ("absence", "Absence"), ("leave", "Congé"), ("rest", "Repos"), ("overtime", "Heures supplémentaires"),
             ("replacement", "Remplacement")]
    STATUSES = [("planned", "Prévu"), ("requested", "À valider"), ("approved", "Validé"), ("rejected", "Refusé"), ("cancelled", "Annulé"), ("replaced", "Remplacé")]
    ATTENDANCE = [("none", "Non déclarée"), ("declared", "Déclarée"), ("confirmed", "Confirmée"), ("disputed", "Contestée")]

    contract = models.ForeignKey(EngagementContract, on_delete=models.CASCADE, related_name="schedule_events")
    kind = models.CharField(max_length=12, choices=KINDS)
    date = models.DateField(db_index=True)
    end_date = models.DateField(null=True, blank=True)                           # congés / absences sur plusieurs jours
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="planned", db_index=True)
    source = models.CharField(max_length=10, choices=[("generated", "Généré"), ("manual", "Saisi")], default="manual")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    responded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    responded_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True, default="")
    # Présence : déclarée par le prestataire, confirmée par le donneur d'ordre — jamais de position GPS.
    attendance_status = models.CharField(max_length=10, choices=ATTENDANCE, default="none")
    actual_start = models.TimeField(null=True, blank=True)
    actual_end = models.TimeField(null=True, blank=True)
    declared_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    replaces = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replaced_by")
    replacement_worker = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    replacement_status = models.CharField(max_length=10, blank=True, default="", choices=[("", "—"), ("proposed", "Proposé"), ("accepted", "Accepté"), ("declined", "Refusé")])
    booking = models.OneToOneField("handy.Booking", null=True, blank=True, on_delete=models.SET_NULL, related_name="engagement_event")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "start_time", "id"]
        indexes = [models.Index(fields=["contract", "date"]), models.Index(fields=["contract", "kind", "status"])]
        constraints = [
            models.UniqueConstraint(fields=["contract", "kind", "date", "start_time"], condition=Q(source="generated"), name="eng_one_generated_shift"),
        ]


# ═══ Évaluations ════════════════════════════════════════════════════════════════════════════════════════════════════

class EngagementEvaluation(models.Model):
    KINDS = [("periodic", "Périodique"), ("final", "Finale")]

    contract = models.ForeignKey(EngagementContract, on_delete=models.CASCADE, related_name="evaluations")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="engagement_evaluations_written")
    subject = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="engagement_evaluations_received")
    kind = models.CharField(max_length=10, choices=KINDS)
    period_key = models.CharField(max_length=10)                                   # « 2027-03 » (mois d'évaluation) ou « final »
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    criteria = models.JSONField(default=dict, blank=True)
    comment = models.TextField(max_length=2000, blank=True, default="")
    reply = models.TextField(max_length=1000, blank=True, default="")
    reply_at = models.DateTimeField(null=True, blank=True)
    edit_until = models.DateTimeField()
    is_hidden = models.BooleanField(default=False, db_index=True)
    hidden_reason = models.CharField(max_length=500, blank=True, default="")
    hidden_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["contract", "author", "kind", "period_key"], name="eng_one_evaluation_per_period")]


class EvaluationReport(models.Model):
    evaluation = models.ForeignKey(EngagementEvaluation, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=500)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["evaluation", "reporter"], name="eng_one_report_per_reporter")]


# ═══ Litiges ════════════════════════════════════════════════════════════════════════════════════════════════════════

class EngagementDispute(models.Model):
    KINDS = [("payment", "Paiement"), ("conditions", "Conditions du contrat"), ("conduct", "Comportement"), ("planning", "Planning et présences"), ("other", "Autre")]
    STATUSES = [("open", "Ouvert"), ("under_review", "En examen"), ("resolved", "Résolu"), ("rejected", "Rejeté")]
    ACTIONS = [("none", "Aucune action"), ("mediated", "Médiation / accord des parties"), ("suspend", "Contrat suspendu"), ("terminate", "Contrat résilié"),
               ("waive_installment", "Échéance abandonnée")]

    contract = models.ForeignKey(EngagementContract, on_delete=models.PROTECT, related_name="disputes")
    installment = models.ForeignKey(ContractInstallment, null=True, blank=True, on_delete=models.SET_NULL, related_name="disputes")
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=12, choices=KINDS, default="other")
    reason = models.TextField(max_length=2000)
    status = models.CharField(max_length=14, choices=STATUSES, default="open", db_index=True)
    resolution = models.TextField(max_length=2000, blank=True, default="")
    resolution_action = models.CharField(max_length=20, choices=ACTIONS, blank=True, default="")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]


# ═══ Modèles juridiques, documents scellés, signatures ══════════════════════════════════════════════════════════════

class ContractTemplate(models.Model):
    """Modèle de contrat versionné (articles + références juridiques), par nature de relation et, si besoin, par métier.

    Statuts : brouillon → « À valider juridiquement » → « Validé par revue juridique » (personnel habilité « contracts.legal_review »,
    après revue par un juriste ; jamais « conforme ») → retiré. Un modèle validé n'est plus modifiable : on en crée une nouvelle
    version. Seul un modèle validé peut servir à un contrat (engagements/legal.py)."""
    DRAFT, TO_REVIEW, VALIDATED, RETIRED = "draft", "to_review", "validated", "retired"
    STATUSES = [(DRAFT, "Brouillon"), (TO_REVIEW, "À valider juridiquement"), (VALIDATED, "Validé par revue juridique"), (RETIRED, "Retiré")]

    code = models.SlugField(max_length=60)
    version = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=160)
    relationship = models.CharField(max_length=12, choices=EngagementPosting.RELATIONSHIPS)
    categories = models.ManyToManyField("handy.ServiceCategory", blank=True, related_name="contract_templates")  # vide = tous les métiers
    articles = models.JSONField(default=list)
    legal_references = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=DRAFT, db_index=True)
    review_note = models.TextField(max_length=2000, blank=True, default="")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="next_versions")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code", "-version"]
        constraints = [models.UniqueConstraint(fields=["code", "version"], name="eng_template_code_version")]

    def __str__(self):
        return f"{self.title} (v{self.version})"


class ContractReferenceCounter(models.Model):
    """Compteur annuel des références TRT-CTR-AAAA-NNNNNN (incrémenté sous verrou : jamais deux fois le même numéro)."""
    year = models.PositiveSmallIntegerField(primary_key=True)
    last = models.PositiveIntegerField(default=0)


class SigningKey(models.Model):
    """Clé de scellement Ed25519 de la plateforme (engagements/signing.py). La clé privée n'est stockée que CHIFFRÉE et n'est jamais
    exposée ; la clé publique est publiée pour permettre la vérification hors de Tratra."""
    ACTIVE, RETIRED, REVOKED = "active", "retired", "revoked"
    STATUSES = [(ACTIVE, "Active"), (RETIRED, "Retirée (vérifie encore)"), (REVOKED, "Révoquée")]

    kid = models.CharField(max_length=40, unique=True)
    algorithm = models.CharField(max_length=10, default="Ed25519")
    public_key = models.CharField(max_length=100)
    private_key_encrypted = models.TextField()
    status = models.CharField(max_length=8, choices=STATUSES, default=ACTIVE, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=300, blank=True, default="")
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["status"], condition=Q(status="active"), name="eng_one_active_signing_key")]

    def __str__(self):
        return f"{self.kid} ({self.status})"


def document_path(instance, filename):
    return f"contracts/{instance.contract_id}/{uuid.uuid4().hex}.pdf"


class ContractDocument(models.Model):
    """Document PDF émis et scellé (engagements/documents.py). IMMUABLE : un déclencheur PostgreSQL refuse toute suppression et toute
    modification autre que la révocation (une seule fois)."""
    KINDS = [("contract", "Contrat"), ("amendment", "Avenant")]
    STAGES = [("for_signature", "À signer"), ("final", "Signé")]

    contract = models.ForeignKey(EngagementContract, on_delete=models.PROTECT, related_name="documents")
    kind = models.CharField(max_length=10, choices=KINDS, default="contract")
    stage = models.CharField(max_length=14, choices=STAGES, default="for_signature")
    reference = models.CharField(max_length=32, db_index=True)
    version = models.PositiveIntegerField()
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    amendment = models.ForeignKey(ContractAmendment, null=True, blank=True, on_delete=models.PROTECT, related_name="documents")
    file = models.FileField(upload_to=document_path, storage=KycPrivateStorage(), max_length=255)
    sha256 = models.CharField(max_length=64, unique=True)
    size = models.PositiveIntegerField(default=0)
    terms_hash = models.CharField(max_length=64)
    token_hash = models.CharField(max_length=64, unique=True)
    signing_key = models.ForeignKey(SigningKey, to_field="kid", db_column="signing_key_kid", on_delete=models.PROTECT, related_name="documents")
    signature = models.CharField(max_length=128)
    issued_at = models.DateTimeField()
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=500, blank=True, default="")
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["issued_at", "id"]
        indexes = [models.Index(fields=["contract", "kind", "stage", "version"])]

    def __str__(self):
        return f"{self.reference} ({self.get_stage_display()}, v{self.version})"


class ContractSignature(models.Model):
    """Signature électronique SIMPLE d'une partie sur un document « à signer » : compte, date, heure, empreinte du document ;
    adresse IP gardée seulement sous forme d'empreinte. Immuable (déclencheur PostgreSQL)."""
    contract = models.ForeignKey(EngagementContract, on_delete=models.PROTECT, related_name="signatures")
    document = models.ForeignKey(ContractDocument, on_delete=models.PROTECT, related_name="signatures")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=10, choices=[("principal", "Donneur d'ordre"), ("worker", "Professionnel")])
    document_sha256 = models.CharField(max_length=64)
    signed_at = models.DateTimeField(auto_now_add=True)
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["signed_at", "id"]
        constraints = [models.UniqueConstraint(fields=["document", "role"], name="eng_one_signature_per_role")]


# ═══ Recrutement : invitations ══════════════════════════════════════════════════════════════════════════════════════

class EngagementInvitation(models.Model):
    """Invitation d'un professionnel vérifié à candidater à un besoin publié ; acceptée, elle devient une candidature."""
    STATUSES = [("sent", "Envoyée"), ("accepted", "Acceptée"), ("declined", "Déclinée"), ("cancelled", "Retirée")]

    posting = models.ForeignKey(EngagementPosting, on_delete=models.CASCADE, related_name="invitations")
    invitee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="engagement_invitations")
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    message = models.CharField(max_length=500, blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUSES, default="sent", db_index=True)
    application = models.OneToOneField(EngagementApplication, null=True, blank=True, on_delete=models.SET_NULL, related_name="invitation")
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["posting", "invitee"], name="eng_one_invitation_per_posting")]
