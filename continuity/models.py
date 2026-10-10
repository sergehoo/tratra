from django.conf import settings
from django.db import models


class IdempotencyRecord(models.Model):
    """Réponse mémorisée d'une écriture rejouable (création de réservation, changement de statut…).

    Un client qui renvoie la MÊME requête avec la même `Idempotency-Key` (double appui, nouvelle tentative après une
    coupure réseau ou un crash, file d'attente hors ligne) reçoit la réponse d'origine ; rien n'est exécuté deux fois.
    Seules les réussites sont mémorisées : une erreur laisse la clé réutilisable. Purgé après 48 h (continuity.tasks)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    scope = models.CharField(max_length=60)
    key = models.CharField(max_length=80)
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "scope", "key"], name="uniq_idempotency_user_scope_key")]

    def __str__(self):
        return f"{self.scope}:{self.key[:8]}"
