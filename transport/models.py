"""Frais de déplacement configurables : aucun tarif n'est codé en dur. Une configuration unique (versionnée), des zones et des tranches
horaires par jour. Chaque modification crée une version (instantané) : une réservation conserve la version qui l'a calculée."""
from datetime import time
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


def all_days() -> list:
    return [0, 1, 2, 3, 4, 5, 6]


class TransportConfig(models.Model):
    """Ligne unique (pk=1). Désactivée par défaut : tant qu'un administrateur ne l'active pas, aucun frais n'est ajouté."""
    ROUND_TRIP_BILLED = "round_trip_billed"
    ROUND_TRIP_INCLUDED = "round_trip_included"
    MODES = [
        (ROUND_TRIP_BILLED, "Tarif par km parcouru : l'aller ET le retour sont facturés (km aller × 2 × tarif)"),
        (ROUND_TRIP_INCLUDED, "Tarif par km d'aller simple, retour inclus (km aller × tarif ; le retour n'est jamais facturé en plus)"),
    ]
    ROUND_METHODS = [("nearest", "Au plus proche"), ("up", "Au supérieur"), ("down", "À l'inférieur")]

    enabled = models.BooleanField(default=False)
    threshold_km = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("1.00"), validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default="XOF")
    mode = models.CharField(max_length=20, choices=MODES, default=ROUND_TRIP_BILLED)
    fallback_flat_amount = models.PositiveIntegerField(default=1000)
    rounding_step = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    rounding_method = models.CharField(max_length=8, choices=ROUND_METHODS, default="nearest")
    effective_from = models.DateField(null=True, blank=True)  # date d'application ; vide = immédiat
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuration du transport"

    def __str__(self):
        return f"Transport v{self.version} ({'actif' if self.enabled else 'inactif'})"

    @classmethod
    def current(cls) -> "TransportConfig":
        return cls.objects.order_by("id").first() or cls.objects.create()


class TransportZone(models.Model):
    """Zone géographique = liste de communes / villes (comparées sans casse ni accents à l'adresse de la mission)."""
    name = models.CharField(max_length=80, unique=True)
    communes = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class TransportBand(models.Model):
    """Tranche horaire : jours concernés, plage [start, end[ en heure d'Abidjan, tarif par km, zone facultative (vide = partout)."""
    name = models.CharField(max_length=80)
    zone = models.ForeignKey(TransportZone, null=True, blank=True, on_delete=models.CASCADE, related_name="bands")
    start_time = models.TimeField(default=time(6, 0))
    end_time = models.TimeField(default=time(9, 0))
    weekdays = models.JSONField(default=all_days)  # 0 = lundi … 6 = dimanche
    rate_per_km = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    is_active = models.BooleanField(default=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["start_time", "id"]

    def __str__(self):
        return f"{self.name} {self.start_time:%H:%M}–{self.end_time:%H:%M}"


class TransportConfigVersion(models.Model):
    """Historique : instantané complet (configuration + zones + tranches) à chaque modification."""
    version = models.PositiveIntegerField(unique=True)
    snapshot = models.JSONField(default=dict)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-version"]
