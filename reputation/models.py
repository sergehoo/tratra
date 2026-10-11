"""Évaluations mutuelles et surveillance.

`ClientReview` : évaluation du DEMANDEUR par le prestataire après une mission ponctuelle terminée (l'inverse, client → prestataire, est
`handy.Review`). Une note n'est publiée qu'une fois révélée (voir reveal.py). La surveillance (`EvaluationWatch`) ne fait que PROPOSER : toute
sanction est une décision humaine motivée, journalisée, avec possibilité de recours."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

RATING = [MinValueValidator(1), MaxValueValidator(5)]


class ClientReview(models.Model):
    CRITERIA = ("courtesy", "clarity", "availability", "payment")
    CRITERIA_LABELS = {"courtesy": "Courtoisie et respect", "clarity": "Clarté de la demande", "availability": "Disponibilité sur place", "payment": "Règlement sans difficulté"}
    EDIT_WINDOW_DAYS = 7

    booking = models.OneToOneField("handy.Booking", on_delete=models.PROTECT, related_name="client_review")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="client_reviews_written")   # le prestataire
    subject = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="client_reviews_received")  # le demandeur
    rating = models.PositiveSmallIntegerField(validators=RATING)
    comment = models.TextField(blank=True, default="", max_length=1000)
    courtesy = models.PositiveSmallIntegerField(null=True, blank=True, validators=RATING)
    clarity = models.PositiveSmallIntegerField(null=True, blank=True, validators=RATING)
    availability = models.PositiveSmallIntegerField(null=True, blank=True, validators=RATING)
    payment = models.PositiveSmallIntegerField(null=True, blank=True, validators=RATING)
    is_hidden = models.BooleanField(default=False, db_index=True)
    hidden_reason = models.CharField(max_length=500, blank=True, default="")
    revealed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self._state.adding and self.revealed_at is None and getattr(settings, "EVALUATION_REVEAL_DAYS", 7) <= 0:
            self.revealed_at = timezone.now()
        super().save(*args, **kwargs)


class EvaluationContest(models.Model):
    """Contestation, par la personne évaluée, d'une évaluation qu'elle juge abusive ou fausse. Décision humaine (Back-Office)."""
    STATUSES = [("open", "À examiner"), ("upheld", "Contestation retenue (évaluation masquée)"), ("rejected", "Contestation rejetée")]
    client_review = models.ForeignKey(ClientReview, null=True, blank=True, on_delete=models.CASCADE, related_name="contests")
    review = models.ForeignKey("handy.Review", null=True, blank=True, on_delete=models.CASCADE, related_name="contests")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=10, choices=STATUSES, default="open", db_index=True)
    resolution = models.CharField(max_length=500, blank=True, default="")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(check=Q(client_review__isnull=False) ^ Q(review__isnull=False), name="contest_one_target"),
            models.UniqueConstraint(fields=["client_review", "author"], condition=Q(client_review__isnull=False), name="contest_once_client_review"),
            models.UniqueConstraint(fields=["review", "author"], condition=Q(review__isnull=False), name="contest_once_review"),
        ]


class EvaluationWatch(models.Model):
    """Dossier de surveillance PROPOSÉ par la détection ; l'humain décide. Un seul dossier ouvert par personne et par type."""
    KINDS = [("low_received", "Mauvaises notes reçues de façon répétée"), ("low_given", "Mauvaises notes données de façon répétée"),
             ("burst", "Rafale d'évaluations en peu de temps"), ("reciprocal", "Notes réciproques suspectes entre mêmes personnes")]
    STATUSES = [("open", "À examiner"), ("investigating", "Enquête en cours"), ("warned", "Avertissement envoyé"), ("suspended", "Compte suspendu"),
                ("banned", "Banni"), ("cleared", "Classé sans suite")]
    ACTIVE = ("open", "investigating", "warned", "suspended")

    subject = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="evaluation_watches")
    kind = models.CharField(max_length=12, choices=KINDS)
    status = models.CharField(max_length=14, choices=STATUSES, default="open", db_index=True)
    priority = models.PositiveSmallIntegerField(default=2)        # 1 faible · 2 moyenne · 3 haute
    explanation = models.TextField(blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)         # chiffres réels qui justifient la proposition
    detected_at = models.DateTimeField(auto_now_add=True)
    last_detected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "-detected_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["subject", "kind"], condition=Q(status__in=("open", "investigating", "warned", "suspended")), name="one_active_watch_per_kind")]


class WatchDecision(models.Model):
    """Historique des décisions humaines (jamais supprimé) : enquête, avertissement, suspension, bannissement, recours, rétablissement."""
    DECISIONS = [("investigate", "Ouvrir une enquête"), ("warn", "Avertir"), ("suspend", "Suspendre le compte"), ("ban", "Bannir"), ("appeal", "Recours reçu"),
                 ("reinstate", "Rétablir"), ("clear", "Classer sans suite")]
    watch = models.ForeignKey(EvaluationWatch, on_delete=models.CASCADE, related_name="decisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    decision = models.CharField(max_length=12, choices=DECISIONS)
    reason = models.CharField(max_length=1000)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
