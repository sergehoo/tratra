"""Journaux anti-fraude (SMS, inscriptions) et désactivations en lot RÉVERSIBLES.

Aucun texte de SMS ni code OTP n'est jamais enregistré : le numéro est masqué (+225••••34) et accompagné d'une empreinte
(HMAC) qui permet de regrouper les envois vers un même numéro sans le stocker en clair."""
from django.conf import settings
from django.db import models


class SmsLog(models.Model):
    """Une tentative d'envoi de SMS : envoyé, bloqué (raison) ou en échec chez le fournisseur."""
    SENT, BLOCKED, FAILED = "sent", "blocked", "failed"
    STATUSES = [(SENT, "Envoyé"), (BLOCKED, "Bloqué"), (FAILED, "Échec fournisseur")]
    PURPOSES = [("otp_signup", "Code de vérification"), ("otp_recovery", "Code de récupération"), ("alert", "Alerte de service")]

    purpose = models.CharField(max_length=20, choices=PURPOSES, db_index=True)
    status = models.CharField(max_length=10, choices=STATUSES, db_index=True)
    reason = models.CharField(max_length=40, blank=True, default="", db_index=True)   # kill_switch, quota_global_day, …
    number_masked = models.CharField(max_length=24, blank=True, default="")
    number_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    country_code = models.CharField(max_length=4, blank=True, default="", db_index=True)   # indicatif (225)
    provider = models.CharField(max_length=40, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Envoi de SMS"
        verbose_name_plural = "Journal des SMS"
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"{self.get_purpose_display()} → {self.number_masked} ({self.get_status_display()})"


class SignupLog(models.Model):
    """Inscription acceptée ou refusée : IP, appareil (si fourni), anti-robot, raison du refus."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="signup_log")
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    device = models.CharField(max_length=64, blank=True, default="", db_index=True)   # empreinte de l'identifiant d'installation
    channel = models.CharField(max_length=10, blank=True, default="")                 # web | app
    captcha = models.CharField(max_length=10, blank=True, default="")                 # ok | absent | failed | off
    accepted = models.BooleanField(default=True, db_index=True)
    reason = models.CharField(max_length=40, blank=True, default="", db_index=True)
    name_key = models.CharField(max_length=64, blank=True, default="", db_index=True)   # empreinte du nom complet normalisé
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Inscription (journal)"
        verbose_name_plural = "Journal des inscriptions"


class SuspensionBatch(models.Model):
    """Désactivation en lot décidée après relecture d'un rapport ; annulable (réactivation à l'identique)."""
    label = models.CharField(max_length=120)
    criteria = models.JSONField(default=dict, blank=True)         # filtres du rapport (période, seuils)
    created_by = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    reverted_at = models.DateTimeField(null=True, blank=True)
    reverted_by = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Lot de désactivation"
        verbose_name_plural = "Lots de désactivation"

    def __str__(self):
        return f"#{self.pk} {self.label}"


class AccountSuspension(models.Model):
    batch = models.ForeignKey(SuspensionBatch, on_delete=models.CASCADE, related_name="items")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    was_active = models.BooleanField()
    reasons = models.JSONField(default=list, blank=True)
    restored = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "user"], name="antifraud_one_suspension_per_batch")]
        verbose_name = "Compte désactivé"
        verbose_name_plural = "Comptes désactivés"
