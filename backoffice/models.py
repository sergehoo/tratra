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


class StaffMessageBatch(models.Model):
    """Envoi de l'équipe à un ou plusieurs membres. Chaque destinataire reçoit SON message dans SON fil « Équipe Tratra » : jamais de groupe,
    jamais de liste de destinataires visible d'un membre. Le suivi (par destinataire) et l'audit sont conservés ici."""
    SERVICE, PROMOTION = "service", "promotion"
    PURPOSES = [(SERVICE, "Information de service"), (PROMOTION, "Promotionnelle (consentement marketing requis)")]
    QUEUED, SENDING, DONE = "queued", "sending", "done"
    STATUSES = [(QUEUED, "En file"), (SENDING, "Envoi en cours"), (DONE, "Terminé")]

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    body = models.TextField(max_length=2000)
    purpose = models.CharField(max_length=10, choices=PURPOSES, default=SERVICE)
    selection = models.JSONField(default=dict, blank=True)             # {"user_ids": [...]} ou {"filters": {...}} — jamais de coordonnées
    recipient_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=8, choices=STATUSES, default=QUEUED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class StaffMessageDelivery(models.Model):
    PENDING, SENT, NO_CONSENT, UNREACHABLE, FAILED = "pending", "sent", "skipped_consent", "skipped_unreachable", "failed"
    STATUSES = [(PENDING, "En attente"), (SENT, "Envoyé"), (NO_CONSENT, "Ignoré : pas de consentement marketing"),
                (UNREACHABLE, "Ignoré : compte inactif ou introuvable"), (FAILED, "Échec")]

    batch = models.ForeignKey(StaffMessageBatch, on_delete=models.CASCADE, related_name="deliveries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=20, choices=STATUSES, default=PENDING, db_index=True)
    message = models.ForeignKey("handy.Message", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    error = models.CharField(max_length=160, blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "user"], name="uniq_staff_delivery")]
        indexes = [models.Index(fields=["batch", "status"])]


class AssistantConversation(models.Model):
    """Conversation d'UN administrateur avec Tratra AI. Privée : jamais lisible par un autre compte, même super-administrateur.
    La suppression est logique (`deleted_at`) puis purgée après la durée de conservation (`purge_assistant_history`)."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_conversations")
    title = models.CharField(max_length=80, default="Nouvelle conversation")
    client_id = models.UUIDField(null=True, blank=True)                 # idempotence : un double clic ne crée jamais deux conversations
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["owner", "client_id"], condition=models.Q(client_id__isnull=False), name="uniq_ai_conversation_client")]
        indexes = [models.Index(fields=["owner", "-updated_at"], name="ai_conv_owner_idx")]

    def __str__(self):
        return f"Conversation IA #{self.pk}"


class AssistantMessage(models.Model):
    """Un échange. `sources` ne garde que le NOM des outils consultés (jamais leurs données) : l'interface montre d'où vient la réponse."""
    USER, ASSISTANT = "user", "assistant"
    ROLES = [(USER, "Administrateur"), (ASSISTANT, "Tratra AI")]

    conversation = models.ForeignKey(AssistantConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLES)
    content = models.TextField(blank=True, default="")
    client_id = models.UUIDField(null=True, blank=True)
    sources = models.JSONField(default=list, blank=True)                 # [{"tool": "bookings_overview", "label": "Réservations", "ok": true}]
    provider = models.CharField(max_length=20, blank=True, default="")
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["conversation", "client_id"], condition=models.Q(client_id__isnull=False), name="uniq_ai_message_client")]
        indexes = [models.Index(fields=["conversation", "-id"], name="ai_msg_conv_idx")]
