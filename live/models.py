"""Suivi GPS en direct d'une mission (Tratra Live).

Principes : consentement explicite et révocable de chaque partie ; positions enregistrées UNIQUEMENT pendant
l'intervention (artisan en route) ; historique minimal (purgé) ; aucune position hors d'une mission autorisée."""
from django.contrib.gis.db import models as gis_models
from django.db import models


class TrackingSession(models.Model):
    """État du suivi d'UNE réservation. Les statuts « confirmée / en cours / terminée / annulée » restent ceux de
    la machine à états de la réservation ; « en route » et « arrivé » sont des jalons de cette session."""
    booking = models.OneToOneField("handy.Booking", on_delete=models.CASCADE, related_name="tracking_session")

    artisan_sharing = models.BooleanField(default=False)
    artisan_consent_at = models.DateTimeField(null=True, blank=True)
    client_sharing = models.BooleanField(default=False)
    client_consent_at = models.DateTimeField(null=True, blank=True)

    en_route_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    # Distance entre l'artisan et le lieu au moment où il déclare son arrivée (si les deux positions sont connues) :
    # sert à ne pas créditer en ponctualité une arrivée déclarée loin du lieu.
    arrival_distance_m = models.PositiveIntegerField(null=True, blank=True)

    # Dernier itinéraire calculé (cache) : [[lat, lng], ...]
    route_polyline = models.JSONField(default=list, blank=True)
    route_eta_seconds = models.PositiveIntegerField(null=True, blank=True)
    route_distance_m = models.PositiveIntegerField(null=True, blank=True)
    route_source = models.CharField(max_length=20, blank=True, default="")  # osrm | estimate
    route_updated_at = models.DateTimeField(null=True, blank=True)
    route_origin = gis_models.PointField(srid=4326, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Suivi mission #{self.booking_id}"


class LivePosition(models.Model):
    ARTISAN, CLIENT = "artisan", "client"
    ROLES = [(ARTISAN, "Artisan"), (CLIENT, "Client")]

    session = models.ForeignKey(TrackingSession, on_delete=models.CASCADE, related_name="positions")
    role = models.CharField(max_length=10, choices=ROLES)
    loc = gis_models.PointField(srid=4326)
    accuracy = models.FloatField(null=True, blank=True)   # mètres
    speed = models.FloatField(null=True, blank=True)      # m/s
    heading = models.FloatField(null=True, blank=True)    # degrés
    captured_at = models.DateTimeField()                  # heure de la mesure sur l'appareil
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-captured_at", "-id"]
        indexes = [models.Index(fields=["session", "role", "-captured_at"]), models.Index(fields=["received_at"])]
