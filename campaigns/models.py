"""Engagement AUTOMATISÉ : campagnes déclenchées par des événements réels (inscription vérifiée, profil, KYC, services, commandes,
activité), envoyées par le module Annonces (message dans l'application) et FCM (push si autorisé).

  Campaign      message modifiable (bibliothèque), déclencheur, audience (client / artisan / entreprise), communes, progression,
                délai, fréquence, programmation, activation — DÉSACTIVÉE par défaut ;
  CampaignSend  historique : un envoi par (campagne, utilisateur, référence) — jamais deux, même si une tâche est rejouée.

Règles (campaigns.engine) : consentement marketing pour les campagnes marketing, désinscription par la catégorie de notification
« Conseils, rappels et nouveautés », 2 push d'engagement par semaine au plus, envoi seulement aux heures autorisées (fuseau de
l'exploitation), priorité absolue à Tratra Flash, aux réservations et à la sécurité, arrêt dès que l'objectif est atteint, aucun SMS."""
from django.conf import settings
from django.db import models

AUDIENCES = [("clients", "Clients"), ("artisans", "Artisans"), ("companies", "Entreprises")]


class Campaign(models.Model):
    TRIGGERS = [
        ("welcome", "Bienvenue — inscription vérifiée"),
        ("profile_incomplete", "Profil incomplet"),
        ("kyc_pending", "Vérification d'identité à faire"),
        ("kyc_rejected", "Vérification d'identité refusée (nouvelle pièce)"),
        ("first_service", "Premier service (artisan sans offre)"),
        ("first_order", "Première commande (aucune demande ni réservation)"),
        ("review", "Avis après une prestation terminée"),
        ("artisan_reviews", "Premiers avis (artisan sans avis)"),
        ("inactive", "Inactivité"),
        ("news", "Nouveauté (diffusion unique à l'audience)"),
    ]
    PROGRESS = [("verified", "Téléphone vérifié"), ("profile_complete", "Profil complet"),
                ("kyc_approved", "Identité vérifiée"), ("publishable", "Publication autorisée"), ("active", "Actif (offre ou commande)")]

    key = models.SlugField(max_length=80, unique=True, help_text="Code stable du modèle (jamais modifié).")
    name = models.CharField(max_length=140)
    trigger = models.CharField(max_length=24, choices=TRIGGERS, db_index=True)
    audience = models.CharField(max_length=10, choices=AUDIENCES)
    communes = models.JSONField(default=list, blank=True, help_text="Villes ou communes DÉCLARÉES (vide = partout).")
    progress = models.JSONField(default=list, blank=True, help_text="Étapes de progression ciblées (vide = toutes).")
    # Délais et fréquence
    delay_hours = models.PositiveIntegerField(default=24, help_text="Délai après l'événement déclencheur.")
    inactive_days = models.PositiveIntegerField(default=30, help_text="Inactivité : jours sans connexion.")
    max_age_days = models.PositiveIntegerField(default=14, help_text="Événements plus anciens que délai + ce nombre de jours ignorés.")
    min_gap_hours = models.PositiveIntegerField(default=48, help_text="Écart minimal avec le précédent message d'engagement reçu.")
    # Message (bibliothèque modifiable) et action
    title = models.CharField(max_length=140)
    body = models.TextField(max_length=600)
    action_label = models.CharField(max_length=40, blank=True, default="")
    action_value = models.CharField(max_length=120, blank=True, default="", help_text="Écran du registre central (ex. « kyc », « flash_order »).")
    marketing = models.BooleanField(default=True, help_text="Marketing : consentement exigé. Sinon information sur le compte de l'utilisateur.")
    send_push = models.BooleanField(default=True)
    feature = models.CharField(max_length=40, blank=True, default="", help_text="Fonction annoncée : activable seulement si elle est déployée.")
    priority = models.PositiveSmallIntegerField(default=100, help_text="Plus petit = prioritaire quand plusieurs messages sont dus.")
    # Activation et programmation
    is_active = models.BooleanField(default=False, db_index=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    announcement = models.OneToOneField("announcements.Announcement", on_delete=models.SET_NULL, null=True, blank=True, related_name="campaign")
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "key"]
        verbose_name = "Campagne d'engagement"
        verbose_name_plural = "Campagnes d'engagement"

    def __str__(self):
        return self.name


class CampaignSend(models.Model):
    STATUSES = [("scheduled", "Programmé"), ("sent", "Envoyé"), ("skipped", "Non envoyé"), ("goal_met", "Objectif déjà atteint"),
                ("cancelled", "Annulé")]
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="sends")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="campaign_sends")
    ref = models.CharField(max_length=40, blank=True, default="", help_text="Objet déclencheur (ex. réservation) ; vide = une fois par compte.")
    status = models.CharField(max_length=10, choices=STATUSES, default="scheduled", db_index=True)
    due_at = models.DateTimeField(db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reason = models.CharField(max_length=40, blank=True, default="")
    push = models.BooleanField(default=False)            # push demandé (compté dans la limite hebdomadaire)
    notification = models.ForeignKey("handy.Notification", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    converted_at = models.DateTimeField(null=True, blank=True)   # objectif atteint APRÈS l'envoi
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "user", "ref"], name="uniq_campaign_send")]
        indexes = [models.Index(fields=["user", "-sent_at"]), models.Index(fields=["status", "due_at"])]
