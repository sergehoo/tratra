"""Annonces Tratra : communications ciblées, programmées, mesurées et soumises au consentement.

Règles de conformité (appliquées par announcements.services, pas par l'interface) :
 - une annonce PROMOTIONNELLE n'est diffusée (push ni affichage) qu'aux utilisateurs ayant donné leur consentement marketing ;
 - le ciblage géographique n'utilise QUE les villes/communes DÉCLARÉES dans les profils — jamais une position GPS ;
 - une annonce n'atteint un utilisateur qu'une fois (livraison unique), jamais après son expiration."""
from django.conf import settings
from django.db import models


class Announcement(models.Model):
    KIND_CHOICES = [("service", "Information de service"), ("promotion", "Promotionnelle")]
    STATUS_CHOICES = [("draft", "Brouillon"), ("scheduled", "Programmée"), ("published", "Publiée"),
                      ("expired", "Expirée"), ("cancelled", "Annulée")]
    ACTION_CHOICES = [("none", "Aucune action"), ("link", "Lien web (https)"), ("deeplink", "Écran de l'application")]
    # Écrans de l'application : registre central `handy.destinations` (rôles, paramètres, équivalent web).

    title = models.CharField(max_length=140)
    body = models.TextField(max_length=2000)
    image = models.ImageField(upload_to="announcements/", blank=True, null=True)
    # Variante de l'image pour les notifications push : JPEG 2:1 (1024 x 512 au plus), légère, générée à la diffusion.
    push_image = models.ImageField(upload_to="announcements/push/", blank=True, null=True, editable=False)
    push_image_source = models.CharField(max_length=255, blank=True, default="", editable=False)   # image d'origine de la variante
    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default="service", db_index=True)

    action_kind = models.CharField(max_length=10, choices=ACTION_CHOICES, default="none")
    action_label = models.CharField(max_length=40, blank=True, default="")
    action_value = models.CharField(max_length=300, blank=True, default="")   # URL https ou « kind » / « kind/id »

    # Audience : rôles (au moins un) et villes déclarées (vide = partout).
    to_clients = models.BooleanField(default=False)
    to_artisans = models.BooleanField(default=False)
    to_companies = models.BooleanField(default=False)
    cities = models.JSONField(default=list, blank=True)

    send_push = models.BooleanField(default=True)
    publish_at = models.DateTimeField(null=True, blank=True, db_index=True)   # vide = dès la publication manuelle
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft", db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)   # contrôle des écritures concurrentes (If-Match côté API)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "publish_at"])]

    def __str__(self):
        return self.title


class AnnouncementDelivery(models.Model):
    """Une livraison = une annonce pour UN utilisateur ; porte les statistiques d'envoi et d'ouverture."""
    PUSH_CHOICES = [("", "Sans push"), ("queued", "En file"), ("sent", "Envoyé"), ("no_device", "Aucun appareil"),
                    ("disabled", "Désactivé par l'utilisateur"), ("unconfigured", "Firebase non configuré"), ("failed", "Échec")]
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="deliveries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="announcement_deliveries")
    notification = models.ForeignKey("handy.Notification", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    delivered_at = models.DateTimeField(auto_now_add=True)
    seen_at = models.DateTimeField(null=True, blank=True)      # affichée dans l'application
    opened_at = models.DateTimeField(null=True, blank=True)    # ouverte / action touchée
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["announcement", "user"], name="uniq_announcement_delivery")]
        indexes = [models.Index(fields=["user", "-delivered_at"])]
