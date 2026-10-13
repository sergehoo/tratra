"""Statuts éphémères (texte, photo, vidéo, texte + média) : visibles 24 h par défaut, vues enregistrées côté serveur.

Règles portées par `statuses.services`, jamais par l'interface :
 - visibilité : contacts Tratra (relation dérivée des données métier : `handy.contacts`) ou, au choix de l'auteur, tout membre ;
   exclusions individuelles et blocages respectés dans les deux sens ;
 - une vue n'existe que si le statut a réellement été affiché (appel explicite du client) ; seul l'auteur voit la liste nominative ;
 - l'expiration est vérifiée à chaque lecture (`expires_at`), le nettoyage des médias n'est qu'une purge de stockage."""
from django.conf import settings
from django.db import models


class Status(models.Model):
    TEXT, PHOTO, VIDEO = "text", "photo", "video"
    KINDS = [(TEXT, "Texte"), (PHOTO, "Photo"), (VIDEO, "Vidéo")]
    CONTACTS, EXTENDED = "contacts", "extended"
    AUDIENCES = [(CONTACTS, "Mes contacts Tratra"), (EXTENDED, "Tous les membres")]

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="statuses")
    kind = models.CharField(max_length=6, choices=KINDS)
    text = models.CharField(max_length=2000, blank=True, default="")          # texte ou légende (limite métier : STATUS_TEXT_MAX)
    background = models.CharField(max_length=20, blank=True, default="")      # couleur d'un statut texte seul
    media = models.FileField(upload_to="statuses/%Y/%m/", null=True, blank=True, max_length=255)
    media_mime = models.CharField(max_length=60, blank=True, default="")
    media_size = models.PositiveIntegerField(default=0)
    media_meta = models.JSONField(default=dict, blank=True)                    # largeur, hauteur, durée MESURÉES côté serveur
    audience = models.CharField(max_length=10, choices=AUDIENCES, default=CONTACTS)
    allow_replies = models.BooleanField(default=True)
    client_id = models.UUIDField(null=True, blank=True)                        # idempotence : un renvoi après coupure ne publie pas deux fois
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    removed_by_staff = models.BooleanField(default=False)
    media_purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["author", "client_id"], condition=models.Q(client_id__isnull=False),
                                               name="uniq_status_client_id")]
        indexes = [models.Index(fields=["author", "-created_at"], name="status_author_idx"),
                   models.Index(fields=["audience", "expires_at"], name="status_aud_exp_idx")]

    @property
    def type(self) -> str:
        """Type affiché : text, photo, video ou text_media (média accompagné d'un texte)."""
        return "text_media" if self.kind != self.TEXT and self.text else self.kind

    def __str__(self):
        return f"Statut #{self.pk} de {self.author_id}"


class StatusView(models.Model):
    """UNE ligne par (statut, lecteur) : première et dernière consultation, nombre de consultations (répétées si activé)."""
    status = models.ForeignKey(Status, on_delete=models.CASCADE, related_name="views")
    viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="status_views")
    first_viewed_at = models.DateTimeField()
    last_viewed_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["status", "viewer"], name="uniq_status_view")]
        indexes = [models.Index(fields=["status", "-first_viewed_at"], name="status_view_idx"),
                   models.Index(fields=["viewer", "status"], name="status_view_viewer_idx")]


class StatusPreference(models.Model):
    """Réglages de l'auteur : audience par défaut et réponses par message."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="status_preference")
    audience = models.CharField(max_length=10, choices=Status.AUDIENCES, default=Status.CONTACTS)
    allow_replies = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class StatusExclusion(models.Model):
    """Membre à qui l'auteur ne montre jamais ses statuts (sans que ce membre soit prévenu)."""
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="status_exclusions_made")
    excluded = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="status_exclusions_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["author", "excluded"], name="uniq_status_exclusion"),
                       models.CheckConstraint(check=~models.Q(author=models.F("excluded")), name="status_exclusion_not_self")]


class StatusReport(models.Model):
    """Signalement d'un statut par un membre qui peut le voir ; traité par la modération du Back-Office."""
    status = models.ForeignKey(Status, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=500)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["status", "reporter"], name="uniq_status_report")]
