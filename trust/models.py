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
