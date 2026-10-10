from django.conf import settings
from django.db import models


class SupportNote(models.Model):
    """Note INTERNE du support sur un compte (contexte d'un échange, décision, suivi). Jamais visible de l'utilisateur."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"Note #{self.pk} sur le compte #{self.user_id}"


class StaffMFA(models.Model):
    """Appareil TOTP d'un compte d'administration (voir backoffice/mfa.py). Le secret n'est jamais stocké en clair."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa")
    secret_enc = models.TextField()
    confirmed_at = models.DateTimeField(null=True, blank=True)       # vide tant que l'enrôlement n'est pas confirmé par un code valide
    last_used_step = models.BigIntegerField(null=True, blank=True)   # dernier pas TOTP accepté (anti-rejeu)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    backup_hashes = models.JSONField(default=list, blank=True)       # empreintes HMAC des codes de secours restants
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"MFA du compte #{self.user_id} ({'actif' if self.confirmed_at else 'en attente'})"
