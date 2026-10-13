"""Vérification faciale biométrique du KYC : consentement traçable, sessions courtes, captures chiffrées, décisions humaines.

Principes : la biométrie n'est PAS de l'IA générative (aucun visage n'est envoyé à DeepSeek ni à Anthropic) ; seul un fournisseur spécialisé de
liveness et de comparaison visage/document, configuré par l'exploitant, reçoit les captures. Sans fournisseur réel, le dossier reste EN ATTENTE
d'une revue humaine : jamais de validation fondée sur une simulation. Aucune base de reconnaissance faciale générale : les captures ne servent
qu'à la session qui les a produites et sont supprimées selon la durée de conservation."""
from django.conf import settings
from django.db import models

from handy.storage import KycPrivateStorage


def capture_path(instance, filename):
    return f"biometric/{instance.session_id}/{instance.index}.bin"


class BiometricConsent(models.Model):
    """Consentement explicite et traçable (version du texte, empreinte du texte, date, adresse IP hachée) ; retirable."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="biometric_consents")
    version = models.CharField(max_length=20)
    text_sha256 = models.CharField(max_length=64)
    granted_at = models.DateTimeField(auto_now_add=True)
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-granted_at", "-id"]


class BiometricVerification(models.Model):
    """État biométrique d'un profil prestataire (une ligne). Le badge « Vérifié » ne lit que `satisfied`."""
    NOT_STARTED, IN_PROGRESS, PENDING_REVIEW, PASSED, FAILED, INCONCLUSIVE = "not_started", "in_progress", "pending_review", "passed", "failed", "inconclusive"
    MANUAL_APPROVED, ALTERNATIVE_APPROVED, REJECTED, RECAPTURE, DOCUMENTS = "manual_approved", "alternative_approved", "rejected", "recapture_requested", "documents_requested"
    STATUSES = [(NOT_STARTED, "Non commencée"), (IN_PROGRESS, "En cours"), (PENDING_REVIEW, "En attente de revue humaine"), (PASSED, "Satisfaisante (fournisseur)"),
                (FAILED, "Échec du liveness"), (INCONCLUSIVE, "Non concluante"), (MANUAL_APPROVED, "Approuvée après revue humaine"),
                (ALTERNATIVE_APPROVED, "Procédure alternative approuvée"), (REJECTED, "Refusée"), (RECAPTURE, "Nouvelle capture demandée"),
                (DOCUMENTS, "Pièces complémentaires demandées")]
    SATISFIED = (PASSED, MANUAL_APPROVED, ALTERNATIVE_APPROVED)

    profile = models.OneToOneField("handy.HandymanProfile", on_delete=models.CASCADE, related_name="biometric")
    status = models.CharField(max_length=24, choices=STATUSES, default=NOT_STARTED, db_index=True)
    human_review_requested_at = models.DateTimeField(null=True, blank=True)
    human_review_reason = models.CharField(max_length=30, blank=True, default="")      # camera_refused | accessibility | provider_unavailable | other
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decision_reason = models.CharField(max_length=1000, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def satisfied(self) -> bool:
        return self.status in self.SATISFIED


class BiometricSession(models.Model):
    CREATED, CAPTURING, SUBMITTED, COMPLETED, EXPIRED, CANCELLED = "created", "capturing", "submitted", "completed", "expired", "cancelled"
    STATUSES = [(CREATED, "Créée"), (CAPTURING, "Captures en cours"), (SUBMITTED, "Soumise"), (COMPLETED, "Terminée"), (EXPIRED, "Expirée"), (CANCELLED, "Annulée")]
    OUTCOMES = [("passed", "Satisfaisante"), ("failed", "Liveness échoué"), ("inconclusive", "Non concluante"), ("pending_review", "En attente de revue humaine"),
                ("provider_error", "Fournisseur indisponible")]

    verification = models.ForeignKey(BiometricVerification, on_delete=models.CASCADE, related_name="sessions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="biometric_sessions")
    consent = models.ForeignKey(BiometricConsent, null=True, on_delete=models.SET_NULL, related_name="+")
    document = models.ForeignKey("handy.HandymanDocument", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    token_hash = models.CharField(max_length=64, db_index=True)
    token_uses = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=12, choices=STATUSES, default=CREATED, db_index=True)
    outcome = models.CharField(max_length=16, choices=OUTCOMES, blank=True, default="")
    challenges = models.JSONField(default=list)                       # ordre ALÉATOIRE propre à la session
    attempt_no = models.PositiveSmallIntegerField(default=1)
    provider = models.CharField(max_length=20, blank=True, default="")
    liveness_passed = models.BooleanField(null=True)
    liveness_score = models.FloatField(null=True, blank=True)
    match_score = models.FloatField(null=True, blank=True)
    thresholds = models.JSONField(default=dict, blank=True)           # seuils appliqués (traçabilité)
    anomalies = models.JSONField(default=list, blank=True)            # codes techniques suspects, explicables
    expires_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class BiometricCapture(models.Model):
    """Capture CHIFFRÉE (Fernet) dans le stockage privé ; supprimée à l'échéance de conservation. Jamais d'URL publique."""
    session = models.ForeignKey(BiometricSession, on_delete=models.CASCADE, related_name="captures")
    index = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=20)                            # front | left | right | up | down | smile
    file = models.FileField(upload_to=capture_path, storage=KycPrivateStorage(), max_length=200)
    sha256 = models.CharField(max_length=64, db_index=True)
    size = models.PositiveIntegerField(default=0)
    quality = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["session_id", "index"]
        constraints = [models.UniqueConstraint(fields=["session", "index"], name="one_capture_per_index")]   # rejeu d'un même rang refusé


class BiometricDecision(models.Model):
    DECISIONS = [("approve_manual", "Approuver après revue"), ("approve_alternative", "Approuver la procédure alternative"), ("reject", "Refuser"),
                 ("request_recapture", "Demander une nouvelle capture"), ("request_documents", "Demander des pièces complémentaires"), ("open_review", "Ouvrir une revue manuelle")]
    verification = models.ForeignKey(BiometricVerification, on_delete=models.CASCADE, related_name="decisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    decision = models.CharField(max_length=24, choices=DECISIONS)
    reason = models.CharField(max_length=1000)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
