"""Tratra Flash & Smart Dispatch : un client décrit son besoin, Tratra le propose par VAGUES aux professionnels éligibles et disponibles,
le premier qui accepte (prix ferme) ou le devis que le client retient (sur devis) obtient la mission — une seule fois.

- `DispatchConfig` : réglages (une ligne, pk=1) modifiables au Back-Office — poids du classement, taille des vagues, délais.
- `MissionRequest` : la demande du client (métier, zone, date, mode, montant). Une demande attribuée porte la réservation créée.
- `MissionOffer` : une proposition à UN professionnel (vague, rang, score expliqué, délai, réponse). Jamais deux fois au même pro.
- `DispatchEvent` : journal horodaté (vagues, propositions, réponses, délais, attribution, expiration) — rien n'est effacé.

Garanties : une demande n'a qu'une proposition acceptée (contrainte d'unicité) et qu'une réservation (OneToOne) ; l'attribution verrouille
la demande puis la proposition (PostgreSQL `SELECT … FOR UPDATE`). Un refus n'est jamais une faute ; aucune donnée privée du client (adresse
exacte, téléphone) n'est montrée avant l'attribution."""
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class DispatchConfig(models.Model):
    # --- Vagues et délais -------------------------------------------------------------------------------------------
    wave_size = models.PositiveSmallIntegerField("Professionnels sollicités par vague", default=3,
                                                 validators=[MinValueValidator(1), MaxValueValidator(20)])
    max_waves = models.PositiveSmallIntegerField("Nombre maximal de vagues (rayon fixe)", default=4, validators=[MinValueValidator(1), MaxValueValidator(20)])
    offer_timeout_seconds = models.PositiveIntegerField("Délai de réponse — mission immédiate (secondes)", default=90,
                                                        validators=[MinValueValidator(20), MaxValueValidator(3600)])
    scheduled_offer_timeout_seconds = models.PositiveIntegerField("Délai de réponse — mission planifiée (secondes)", default=900,
                                                                  validators=[MinValueValidator(60), MaxValueValidator(86400)])
    immediate_horizon_minutes = models.PositiveIntegerField(
        "Une mission est « immédiate » si elle commence dans moins de (minutes)", default=120,
        validators=[MinValueValidator(15), MaxValueValidator(1440)])
    direct_offer_timeout_seconds = models.PositiveIntegerField(
        "Délai de réponse du professionnel CHOISI — mission immédiate (secondes)", default=300,
        validators=[MinValueValidator(60), MaxValueValidator(3600)])
    direct_scheduled_offer_timeout_seconds = models.PositiveIntegerField(
        "Délai de réponse du professionnel CHOISI — mission planifiée (secondes)", default=3600,
        validators=[MinValueValidator(300), MaxValueValidator(86400)])
    quote_window_hours = models.PositiveSmallIntegerField("Durée pendant laquelle le client choisit un devis (heures)", default=24,
                                                          validators=[MinValueValidator(1), MaxValueValidator(168)])
    max_quotes = models.PositiveSmallIntegerField("Devis recherchés (sur devis) avant d'arrêter les vagues", default=3,
                                                  validators=[MinValueValidator(1), MaxValueValidator(10)])
    mission_duration_minutes = models.PositiveIntegerField("Durée estimée d'une mission pour les conflits d'agenda (minutes)", default=120,
                                                           validators=[MinValueValidator(15), MaxValueValidator(1440)])

    # --- Zone ---------------------------------------------------------------------------------------------------------
    radius_km = models.FloatField("Rayon de recherche (km)", default=15, validators=[MinValueValidator(1), MaxValueValidator(100)])

    # --- Recherche progressive (façon VTC) : le rayon s'élargit par paliers tant que personne n'a accepté ------------------
    progressive_search = models.BooleanField("Recherche progressive par rayons (sinon : vagues dans le rayon fixe ci-dessus)", default=True)
    radius_steps = models.CharField("Paliers de rayon (km, du plus petit au plus grand)", max_length=120,
                                    default="0.1,0.5,1,5,10,30,50,100,200")
    step_seconds = models.PositiveIntegerField("Attente avant le palier suivant — mission immédiate (secondes)", default=20,
                                               validators=[MinValueValidator(5), MaxValueValidator(3600)])
    scheduled_step_seconds = models.PositiveIntegerField("Attente avant le palier suivant — mission planifiée (secondes)", default=120,
                                                         validators=[MinValueValidator(10), MaxValueValidator(86400)])
    max_pending_offers = models.PositiveSmallIntegerField("Propositions en attente en même temps (max.)", default=9,
                                                          validators=[MinValueValidator(1), MaxValueValidator(50)])
    max_contacts = models.PositiveSmallIntegerField("Professionnels sollicités au total par demande (max.)", default=30,
                                                    validators=[MinValueValidator(1), MaxValueValidator(200)])
    far_radius_km = models.FloatField("Au-delà de ce rayon : accord du client requis (km)", default=30,
                                      validators=[MinValueValidator(1), MaxValueValidator(500)])
    far_trades = models.CharField("Métiers compatibles au-delà (identifiants séparés par des virgules ; * = tous ; vide = aucun)",
                                  max_length=500, blank=True, default="*")
    far_consent_wait_seconds = models.PositiveIntegerField("Attente de l'accord du client pour élargir (secondes)", default=600,
                                                           validators=[MinValueValidator(30), MaxValueValidator(86400)])

    # --- Propositions (sur devis) et contre-offres ----------------------------------------------------------------------
    proposal_ttl_minutes = models.PositiveIntegerField("Validité d'une proposition de prix — mission immédiate (minutes)", default=30,
                                                       validators=[MinValueValidator(2), MaxValueValidator(1440)])
    max_counter_offers = models.PositiveSmallIntegerField("Contre-offres du client par proposition (0 = aucune)", default=2,
                                                          validators=[MaxValueValidator(5)])
    counter_timeout_seconds = models.PositiveIntegerField("Délai de réponse du professionnel à une contre-offre (secondes)", default=300,
                                                          validators=[MinValueValidator(30), MaxValueValidator(86400)])

    # --- Classement pondéré (chaque critère vaut entre 0 et 1 ; donnée manquante = valeur neutre, jamais zéro) ------------
    weight_distance = models.PositiveSmallIntegerField("Poids : proximité", default=35)
    weight_trust = models.PositiveSmallIntegerField("Poids : score Tratra Trust", default=20)
    weight_rating = models.PositiveSmallIntegerField("Poids : note des clients", default=10)
    weight_reactivity = models.PositiveSmallIntegerField("Poids : réactivité aux propositions", default=15)
    weight_fairness = models.PositiveSmallIntegerField("Poids : répartition équitable (missions récentes)", default=20)
    neutral_value = models.FloatField("Valeur neutre d'un critère sans historique (nouveaux professionnels)", default=0.6,
                                      validators=[MinValueValidator(0), MaxValueValidator(1)])
    min_sample = models.PositiveSmallIntegerField("Historique minimal pour qu'un critère compte", default=3)

    # --- Règles -------------------------------------------------------------------------------------------------------
    auto_pause_after_missed = models.PositiveSmallIntegerField(
        "Passer « Indisponible » après N propositions consécutives sans réponse (0 = jamais)", default=3,
        validators=[MaxValueValidator(20)])
    max_active_requests_per_client = models.PositiveSmallIntegerField("Demandes en cours par client (max.)", default=3,
                                                                      validators=[MinValueValidator(1), MaxValueValidator(20)])
    withdrawal_grace_minutes = models.PositiveSmallIntegerField(
        "Désistement sans conséquence après une acceptation (minutes, erreur de manipulation)", default=5)
    min_amount = models.PositiveIntegerField("Montant minimal d'une mission à prix ferme (FCFA)", default=1000)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "Réglages Smart Dispatch"
        verbose_name_plural = "Réglages Smart Dispatch"

    def __str__(self):
        return "Réglages Smart Dispatch"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls) -> "DispatchConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def current(cls) -> "DispatchConfig":
        """Lecture SANS écriture (supervision, Tratra AI) : la ligne enregistrée, sinon les valeurs par défaut."""
        return cls.objects.filter(pk=1).first() or cls(pk=1)

    WEIGHTS = ("distance", "trust", "rating", "reactivity", "fairness")

    def weights(self) -> dict:
        return {k: getattr(self, f"weight_{k}") for k in self.WEIGHTS}

    def steps_km(self) -> list:
        """Paliers valides, croissants, sans doublon (une saisie erronée au Back-Office est refusée par `clean`)."""
        out = []
        for part in (self.radius_steps or "").replace(";", ",").split(","):
            try:
                km = round(float(part.strip().replace(" ", "")), 3)
            except ValueError:
                continue
            if 0 < km <= 1000 and (not out or km > out[-1]):
                out.append(km)
        return out or [self.radius_km]

    def trade_goes_far(self, category) -> bool:
        """Métier compatible avec une recherche au-delà de `far_radius_km` (le métier ou son métier parent)."""
        allowed = {t.strip().lower() for t in (self.far_trades or "").split(",") if t.strip()}
        if "*" in allowed:
            return True
        slugs = {category.slug}
        if category.parent_id:
            slugs.add(category.parent.slug)
        return bool(allowed & slugs)

    def clean(self):
        from django.core.exceptions import ValidationError

        raw = [p for p in (self.radius_steps or "").replace(";", ",").split(",") if p.strip()]
        if not raw or len(self.steps_km()) != len(raw):
            raise ValidationError({"radius_steps": "Paliers invalides : nombres croissants en km séparés par des virgules (ex. 0.5,1,5,10,30)."})


class MissionRequest(models.Model):
    FIRM, QUOTE = "firm", "quote"
    MODES = [(FIRM, "Prix ferme (le premier qui accepte)"), (QUOTE, "Sur devis (le client choisit)")]
    # Attribution : Smart Dispatch (vagues) ou professionnel choisi par le client (proposition ciblée). UNE seule commande, un seul
    # flux (propositions → acceptation atomique → réservation) ; on peut passer d'un mode à l'autre sans ressaisie (hybrid.switch).
    AUTO, DIRECT = "auto", "direct"
    MATCHINGS = [(AUTO, "Trouvez-moi un professionnel"), (DIRECT, "Choisir mon professionnel")]
    SEARCHING, QUOTING, ASSIGNED, UNFULFILLED, CANCELLED = "searching", "quoting", "assigned", "unfulfilled", "cancelled"
    AWAITING = "awaiting"
    STATUSES = [(SEARCHING, "Recherche en cours"), (QUOTING, "Devis à choisir"), (AWAITING, "Votre choix est attendu"), (ASSIGNED, "Attribuée"),
                (UNFULFILLED, "Aucun professionnel disponible"), (CANCELLED, "Annulée par le client")]
    OPEN = (SEARCHING, QUOTING, AWAITING)

    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="flash_requests")
    category = models.ForeignKey("handy.ServiceCategory", on_delete=models.PROTECT, related_name="flash_requests")
    description = models.TextField(blank=True, default="", max_length=1000)
    # Adresse exacte : communiquée au professionnel UNIQUEMENT après l'attribution. Avant : métier, zone (commune), date, montant.
    address = models.CharField(max_length=255)
    commune = models.CharField(max_length=100, blank=True, default="")
    city = models.CharField(max_length=100, default="Abidjan")
    postal_code = models.CharField(max_length=20, blank=True, default="")
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    scheduled_for = models.DateTimeField(db_index=True)
    is_immediate = models.BooleanField(default=False, db_index=True)
    mode = models.CharField(max_length=5, choices=MODES, default=FIRM)
    matching = models.CharField(max_length=6, choices=MATCHINGS, default=AUTO, db_index=True)
    target = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="flash_targeted")
    service = models.ForeignKey("handy.Service", null=True, blank=True, on_delete=models.SET_NULL, related_name="flash_requests")
    switches = models.PositiveSmallIntegerField(default=0)
    amount = models.DecimalField(max_digits=10, decimal_places=0, null=True, blank=True,
                                 validators=[MinValueValidator(0)])                      # prix ferme (FCFA, déplacement compris)

    status = models.CharField(max_length=12, choices=STATUSES, default=SEARCHING, db_index=True)
    wave = models.PositiveSmallIntegerField(default=0)                                  # dernière vague lancée
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="flash_missions")
    booking = models.OneToOneField("handy.Booking", null=True, blank=True, on_delete=models.PROTECT, related_name="flash_request")
    quote_deadline = models.DateTimeField(null=True, blank=True)
    # Recherche progressive : palier courant, prochaine extension, accord du client au-delà de `far_radius_km`, compteurs exacts.
    radius_index = models.PositiveSmallIntegerField(default=0)
    radius_m = models.PositiveIntegerField(default=0)                                   # rayon courant (0 : commune / rayon fixe)
    next_step_at = models.DateTimeField(null=True, blank=True, db_index=True)
    allow_far = models.BooleanField(default=False)
    consent_asked_at = models.DateTimeField(null=True, blank=True)
    eligible_count = models.PositiveIntegerField(default=0)                            # éligibles trouvés dans le rayon courant
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=200, blank=True, default="")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Demande Tratra Flash"
        verbose_name_plural = "Demandes Tratra Flash"
        indexes = [models.Index(fields=["status", "created_at"]), models.Index(fields=["client", "-created_at"])]
        constraints = [
            models.CheckConstraint(check=Q(mode="quote") | Q(amount__isnull=False), name="flash_firm_has_amount"),
            models.CheckConstraint(check=~Q(status="assigned") | Q(assigned_to__isnull=False, booking__isnull=False),
                                   name="flash_assigned_has_booking"),
        ]

    def __str__(self):
        return f"Demande Flash #{self.pk} — {self.category}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN


class MissionOffer(models.Model):
    PENDING, ACCEPTED, QUOTED, DECLINED, EXPIRED, WITHDRAWN = "pending", "accepted", "quoted", "declined", "expired", "withdrawn"
    COUNTERED, LAPSED, RESIGNED = "countered", "lapsed", "resigned"
    STATUSES = [(PENDING, "En attente de réponse"), (ACCEPTED, "Acceptée"), (QUOTED, "Devis envoyé"), (DECLINED, "Refusée"),
                (EXPIRED, "Sans réponse"), (WITHDRAWN, "Retirée (mission attribuée, annulée ou devis non retenu)"),
                (COUNTERED, "Contre-offre du client en attente"), (LAPSED, "Proposition échue"),
                (RESIGNED, "Désistement après attribution")]
    ANSWERED = (ACCEPTED, QUOTED, DECLINED, COUNTERED, LAPSED, RESIGNED)        # le professionnel a répondu
    PROPOSALS = (QUOTED, COUNTERED)                                            # propositions de prix encore valables
    DECLINE_REASONS = [("busy", "Déjà occupé"), ("too_far", "Trop loin"), ("price", "Montant insuffisant"),
                       ("skills", "Hors de mes compétences"), ("other", "Autre raison")]

    request = models.ForeignKey(MissionRequest, on_delete=models.CASCADE, related_name="offers")
    handyman = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flash_offers")
    wave = models.PositiveSmallIntegerField()
    rank = models.PositiveSmallIntegerField()
    score = models.FloatField()
    score_detail = models.JSONField(default=dict, blank=True)          # critères, valeurs, poids : pourquoi ce pro, à ce rang
    distance_km = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    targeted = models.BooleanField(default=False)                     # proposition au professionnel CHOISI par le client
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    seen_at = models.DateTimeField(null=True, blank=True)              # ouverte dans l'application (aucun effet sur le classement)
    responded_at = models.DateTimeField(null=True, blank=True)
    response_seconds = models.PositiveIntegerField(null=True, blank=True)
    decline_reason = models.CharField(max_length=10, choices=DECLINE_REASONS, blank=True, default="")
    quote_amount = models.DecimalField(max_digits=10, decimal_places=0, null=True, blank=True, validators=[MinValueValidator(0)])
    quote_message = models.CharField(max_length=500, blank=True, default="")
    proposal_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    counter_amount = models.DecimalField(max_digits=10, decimal_places=0, null=True, blank=True, validators=[MinValueValidator(0)])
    counter_at = models.DateTimeField(null=True, blank=True)
    counter_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    counters = models.PositiveSmallIntegerField(default=0)
    push_status = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        ordering = ["-sent_at", "-id"]
        verbose_name = "Proposition Tratra Flash"
        verbose_name_plural = "Propositions Tratra Flash"
        indexes = [models.Index(fields=["handyman", "status", "-sent_at"]), models.Index(fields=["status", "expires_at"])]
        constraints = [
            models.UniqueConstraint(fields=["request", "handyman"], name="flash_one_offer_per_pro"),
            # Une demande n'est attribuée qu'une fois, même si deux acceptations arrivent à la même milliseconde.
            models.UniqueConstraint(fields=["request"], condition=Q(status="accepted"), name="flash_one_accepted_offer"),
            models.CheckConstraint(check=~Q(status="quoted") | Q(quote_amount__isnull=False), name="flash_quote_has_amount"),
            models.CheckConstraint(check=~Q(status="countered") | Q(quote_amount__isnull=False, counter_amount__isnull=False),
                                   name="flash_counter_has_amounts"),
        ]

    def __str__(self):
        return f"Proposition #{self.pk} (demande #{self.request_id})"


class DispatchEvent(models.Model):
    KINDS = [
        ("created", "Demande créée"), ("wave", "Vague lancée"), ("offer_sent", "Proposition envoyée"), ("seen", "Proposition ouverte"),
        ("accepted", "Proposition acceptée"), ("declined", "Proposition refusée"), ("expired", "Proposition sans réponse"),
        ("quoted", "Devis reçu"), ("quote_chosen", "Devis retenu"), ("assigned", "Mission attribuée"), ("no_candidate", "Aucun professionnel éligible"),
        ("unfulfilled", "Demande sans professionnel"), ("cancelled", "Demande annulée"), ("auto_paused", "Professionnel passé « Indisponible »"),
        ("conflict", "Acceptation refusée (conflit)"), ("withdrawal", "Désistement après acceptation"),
        ("targeted", "Proposition au professionnel choisi"), ("awaiting", "Choix du client attendu"), ("switched", "Changement de mode"),
        ("radius", "Rayon élargi"), ("far_consent", "Accord du client pour élargir"), ("consent_asked", "Accord du client demandé"),
        ("counter", "Contre-offre du client"), ("counter_ok", "Contre-offre acceptée"), ("counter_no", "Contre-offre non retenue"),
        ("lapsed", "Proposition échue"), ("reopened", "Recherche reprise après désistement"), ("quoting", "Propositions à choisir"),
    ]
    request = models.ForeignKey(MissionRequest, on_delete=models.CASCADE, related_name="events")
    offer = models.ForeignKey(MissionOffer, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    kind = models.CharField(max_length=14, choices=KINDS, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    data = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["at", "id"]
        verbose_name = "Événement Smart Dispatch"
        verbose_name_plural = "Journal Smart Dispatch"

    def __str__(self):
        return f"{self.get_kind_display()} — demande #{self.request_id}"
