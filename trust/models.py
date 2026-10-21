"""Tratra Trust : critères configurables, attributions de badges auditées, journal d'audit.

Les badges (NOUVEAU, VERIFIE, EXPERT, SUR) ne sont JAMAIS saisis : ils sont attribués et retirés
automatiquement par `trust.engine` à partir de données réelles (KYC, documents approuvés par l'équipe,
missions terminées, avis, ponctualité mesurée). Chaque changement laisse une trace dans `BadgeAward`
(historique) et `AuditEvent`.
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class TrustConfig(models.Model):
    """Critères des badges et du score, modifiables en administration (une seule ligne, pk=1)."""

    # --- EXPERT : expertise démontrée et validée -------------------------------------------------
    expert_min_certifications = models.PositiveSmallIntegerField(
        "Justificatifs professionnels approuvés (min.)", default=1)
    expert_min_completed = models.PositiveIntegerField("Missions terminées (min.)", default=10)
    expert_min_reviews = models.PositiveIntegerField("Avis clients retenus (min.)", default=5)
    expert_min_rating = models.FloatField("Note moyenne (min. /5)", default=4.3,
                                          validators=[MinValueValidator(1), MaxValueValidator(5)])
    expert_min_experience_years = models.PositiveSmallIntegerField("Années d'expérience déclarées (min.)", default=2)

    # --- SUR : fiabilité démontrée par les interventions ------------------------------------------
    sure_min_completed = models.PositiveIntegerField("Missions terminées sur la période (min.)", default=15)
    sure_min_punctuality = models.FloatField("Taux de ponctualité (min.)", default=0.85,
                                             validators=[MinValueValidator(0), MaxValueValidator(1)])
    sure_min_punctuality_sample = models.PositiveIntegerField("Missions mesurées pour la ponctualité (min.)", default=10)
    sure_max_dispute_rate = models.FloatField("Taux de litiges (max.)", default=0.05,
                                              validators=[MinValueValidator(0), MaxValueValidator(1)])
    sure_min_rating = models.FloatField("Note moyenne (min. /5)", default=4.0,
                                        validators=[MinValueValidator(1), MaxValueValidator(5)])
    sure_min_reviews = models.PositiveIntegerField("Avis clients retenus (min.)", default=5)
    sure_window_days = models.PositiveIntegerField("Période d'observation (jours)", default=365)

    # --- Mesures -------------------------------------------------------------------------------------
    punctuality_tolerance_minutes = models.PositiveSmallIntegerField(
        "Tolérance de ponctualité (minutes après l'heure prévue)", default=15)
    min_sample = models.PositiveSmallIntegerField(
        "Échantillon minimal pour qu'une mesure compte dans le score", default=3)
    reevaluation_hours = models.PositiveSmallIntegerField("Réévaluation périodique (heures)", default=24)

    # --- Poids du score de confiance (0-100) ---------------------------------------------------------
    weight_identity = models.PositiveSmallIntegerField("Poids : identité vérifiée (KYC)", default=25)
    weight_satisfaction = models.PositiveSmallIntegerField("Poids : satisfaction clients", default=30)
    weight_reliability = models.PositiveSmallIntegerField("Poids : fiabilité (ponctualité, litiges)", default=20)
    weight_reactivity = models.PositiveSmallIntegerField("Poids : réactivité", default=10)
    weight_track_record = models.PositiveSmallIntegerField("Poids : missions terminées", default=10)
    weight_certifications = models.PositiveSmallIntegerField("Poids : justificatifs professionnels", default=5)
    weight_commitment = models.PositiveSmallIntegerField("Poids : engagements tenus (missions acceptées puis honorées)", default=10)

    # --- XP (expérience cumulée, distincte du score de confiance) ------------------------------------------------------
    xp_per_mission = models.PositiveSmallIntegerField("XP par mission réellement terminée", default=100)
    xp_flash_bonus = models.PositiveSmallIntegerField("XP en plus pour une mission Tratra Flash terminée", default=20)
    xp_pair_cap = models.PositiveSmallIntegerField(
        "Missions récompensées par client sur 30 jours (anti-fraude ; au-delà : 0 XP)", default=3)

    # --- Pénalités (faits vérifiables uniquement) ------------------------------------------------------------------------
    penalty_validity_days = models.PositiveSmallIntegerField("Durée de prise en compte d'une pénalité (jours)", default=180)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Critères Tratra Trust"
        verbose_name_plural = "Critères Tratra Trust"

    def __str__(self):
        return "Critères Tratra Trust"

    def save(self, *args, **kwargs):
        self.pk = 1  # configuration unique
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls) -> "TrustConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class BadgeAward(models.Model):
    """Historique des badges d'un artisan : une ligne par période d'attribution (ended_at NULL = actif)."""
    NOUVEAU, VERIFIE, EXPERT, SUR = "NOUVEAU", "VERIFIE", "EXPERT", "SUR"
    CODES = [(NOUVEAU, "Nouveau"), (VERIFIE, "Vérifié"), (EXPERT, "Expert"), (SUR, "Sûr")]
    LABELS = dict(CODES)
    ORDER = [VERIFIE, EXPERT, SUR, NOUVEAU]  # ordre d'affichage

    profile = models.ForeignKey("handy.HandymanProfile", on_delete=models.CASCADE, related_name="badge_awards")
    code = models.CharField(max_length=10, choices=CODES, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    start_reason = models.TextField(blank=True, default="")
    end_reason = models.TextField(blank=True, default="")
    snapshot = models.JSONField(default=dict, blank=True)  # valeurs mesurées au moment de l'attribution

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "code"], condition=Q(ended_at__isnull=True),
                                    name="trust_one_active_badge_per_code"),
        ]
        indexes = [models.Index(fields=["profile", "ended_at"])]

    def __str__(self):
        return f"{self.get_code_display()} — profil #{self.profile_id}"

    @property
    def active(self) -> bool:
        return self.ended_at is None


class AuditEvent(models.Model):
    """Journal d'audit commun (badges, Tratra ID, organisations) : qui a fait quoi, sur quoi, quand."""
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="audit_events")
    action = models.CharField(max_length=80, db_index=True)       # ex. « badge.awarded »
    target_type = models.CharField(max_length=60, db_index=True)  # ex. « handymanprofile »
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    organization_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["target_type", "target_id", "-created_at"])]

    def __str__(self):
        return f"{self.action} #{self.target_id}"


def audit(action: str, *, actor=None, target=None, target_type: str = "", target_id=None, organization_id=None,
          **data) -> AuditEvent:
    """Enregistre un événement d'audit (cible = instance de modèle ou type + id)."""
    if target is not None:
        target_type = target_type or target._meta.model_name
        target_id = target_id if target_id is not None else target.pk
    return AuditEvent.objects.create(actor=actor, action=action, target_type=target_type, target_id=target_id,
                                     organization_id=organization_id, data=data)


class ProfessionalId(models.Model):
    """Identifiant professionnel Tratra ID d'un artisan : unique, permanent, sans donnée sensible.

    Le code (« TR-XXXX-XXXX ») est la seule chose encodée dans le QR permanent (sous forme d'URL de
    vérification). La VALIDITÉ n'est jamais stockée : elle est recalculée à chaque vérification à partir de
    la règle d'éligibilité (KYC approuvé, compte actif, profil validé) — une suspension révoque donc le badge
    immédiatement, sans délai ni cache."""
    profile = models.OneToOneField("handy.HandymanProfile", on_delete=models.CASCADE, related_name="professional_id")
    code = models.CharField(max_length=14, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tratra ID"
        verbose_name_plural = "Tratra ID"

    def __str__(self):
        return self.code


class BookingPass(models.Model):
    """QR temporaire lié à UNE réservation : l'artisan l'affiche à son arrivée, le client le scanne.

    Court (quelques minutes), à usage unique, révoqué par un nouveau QR. Seul l'empreinte SHA-256 du jeton est
    conservée : un accès à la base ne permet pas de reconstituer un QR valide."""
    booking = models.ForeignKey("handy.Booking", on_delete=models.CASCADE, related_name="identity_passes")
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["booking", "-created_at"])]

    def __str__(self):
        return f"QR mission #{self.booking_id}"


class IdentityCheck(models.Model):
    """Vérification d'identité réussie à l'arrivée : le client a scanné le QR de mission de l'artisan attendu."""
    booking = models.ForeignKey("handy.Booking", on_delete=models.CASCADE, related_name="identity_checks")
    professional = models.ForeignKey(ProfessionalId, on_delete=models.PROTECT, related_name="checks")
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    verified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-verified_at"]
        indexes = [models.Index(fields=["booking", "-verified_at"])]

    def __str__(self):
        return f"Vérification #{self.pk} — mission #{self.booking_id}"


class XpEntry(models.Model):
    """XP cumulés : gagnés UNIQUEMENT sur des missions réellement terminées, jamais retirés, sans effet sur le score de confiance.
    Une ligne par (professionnel, mission, motif) : un rejeu ne double jamais les points."""
    MISSION, FLASH_BONUS = "mission", "flash_bonus"
    REASONS = [(MISSION, "Mission terminée"), (FLASH_BONUS, "Mission Tratra Flash terminée")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="xp_entries")
    booking = models.ForeignKey("handy.Booking", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.CharField(max_length=12, choices=REASONS)
    points = models.PositiveIntegerField()
    detail = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "XP"
        verbose_name_plural = "XP"
        constraints = [models.UniqueConstraint(fields=["user", "booking", "reason"], name="xp_once_per_mission_reason")]


class TrustPenalty(models.Model):
    """Pénalité fondée sur un FAIT VÉRIFIABLE (jamais un refus, jamais une absence de réponse) : désistement après une acceptation ferme
    (constaté automatiquement), absence ou manquement constaté par l'équipe sur une mission précise. Contestable ; annulée si la
    contestation est retenue. Elle pèse sur la composante « Engagements tenus » du score pendant `penalty_validity_days`."""
    WITHDRAWAL, NO_SHOW, OTHER = "withdrawal", "no_show", "other"
    KINDS = [(WITHDRAWAL, "Désistement après une acceptation ferme"), (NO_SHOW, "Absence au rendez-vous constatée"),
             (OTHER, "Manquement constaté par l'équipe")]
    ACTIVE, CONTESTED, CANCELLED = "active", "contested", "cancelled"
    STATUSES = [(ACTIVE, "En vigueur"), (CONTESTED, "Contestée — en cours d'examen"), (CANCELLED, "Annulée")]
    COUNTED = (ACTIVE, CONTESTED)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trust_penalties")
    kind = models.CharField(max_length=12, choices=KINDS)
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE, db_index=True)
    booking = models.ForeignKey("handy.Booking", null=True, blank=True, on_delete=models.SET_NULL, related_name="trust_penalties")
    explanation = models.CharField(max_length=500)
    evidence = models.JSONField(default=dict, blank=True)               # faits datés qui fondent la pénalité
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    contest_reason = models.CharField(max_length=1000, blank=True, default="")
    contested_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Pénalité Tratra Trust"
        verbose_name_plural = "Pénalités Tratra Trust"
        constraints = [models.UniqueConstraint(fields=["user", "kind", "booking"], condition=Q(booking__isnull=False),
                                               name="trust_one_penalty_per_fact")]


class TrustScoreChange(models.Model):
    """Historique consultable du score : une ligne à chaque changement, avec le détail des composantes à cet instant."""
    profile = models.ForeignKey("handy.HandymanProfile", on_delete=models.CASCADE, related_name="trust_score_changes")
    previous = models.PositiveSmallIntegerField(null=True, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    components = models.JSONField(default=list, blank=True)
    trigger = models.CharField(max_length=40, blank=True, default="")
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-at", "-id"]
