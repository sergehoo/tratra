from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Sum, UniqueConstraint, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GistIndex

# Create your models here.


class User(AbstractUser):
    email = models.EmailField(unique=True)

    USER_TYPES = (
        ('client', 'Client'),
        ('employeur', 'Employeur'),
        ('handyman', 'Artisan'),
        ('admin', 'Administrateur'),
    )
    user_type = models.CharField(max_length=20, choices=USER_TYPES, blank=True, null=True, default='client')

    # Conseil: stocker le téléphone en E.164 (ex: +2250500...) et indexer
    phone = models.CharField(max_length=20, blank=True, null=True, unique=True, db_index=True)

    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)

    # ⚠️ Préfère PointField côté profil artisan (voir HandymanProfile)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    last_location = gis_models.PointField(srid=4326, null=True, blank=True)  # pour suggestions
    last_location_ts = models.DateTimeField(null=True, blank=True)

    is_verified = models.BooleanField(default=False, db_index=True)

    groups = models.ManyToManyField(
        Group, verbose_name=_('groups'), blank=True,
        help_text=_('The groups this user belongs to...'),
        related_name="handy_user_groups", related_query_name="handy_user",
    )
    user_permissions = models.ManyToManyField(
        Permission, verbose_name=_('user permissions'), blank=True,
        help_text=_('Specific permissions for this user.'),
        related_name="handy_user_permissions", related_query_name="handy_user",
    )

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["is_verified"]),
        ]

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.user_type or '-'})"


# ---- HANDYMAN PROFILE ----

class HandymanProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='handyman_profile')
    bio = models.TextField(blank=True, null=True)
    skills = models.ManyToManyField('ServiceCategory', related_name='handymen', blank=True)  # <- remove null=True
    experience_years = models.PositiveIntegerField(default=0)
    license_number = models.CharField(max_length=100, blank=True, null=True)
    cni_number = models.CharField(max_length=100, blank=True, null=True)
    insurance_info = models.TextField(blank=True, null=True)
    commune = models.CharField(max_length=100, blank=True, null=True)
    quartier = models.CharField(max_length=100, blank=True, null=True)

    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monthly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    travel_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    availability = models.JSONField(default=dict, blank=True)  # <- null False, default dict
    is_approved = models.BooleanField(default=False, db_index=True)
    rating = models.FloatField(default=0)
    completed_jobs = models.PositiveIntegerField(default=0)
    quality_score = models.PositiveSmallIntegerField(default=0, db_index=True)  # score composite 0-100
    photo = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    # Localisation précise (si dispo)
    location = gis_models.PointField(srid=4326, null=True, blank=True)

    online = models.BooleanField(default=False, db_index=True)  # dispo temps réel

    class Meta:
        indexes = [
            models.Index(fields=["is_approved", "rating"]),
            models.Index(fields=["completed_jobs"]),
            GistIndex(fields=["location"])
        ]

        constraints = [
            models.CheckConstraint(check=Q(hourly_rate__gte=0), name="hm_hourly_rate_gte_0"),
            models.CheckConstraint(check=Q(daily_rate__gte=0), name="hm_daily_rate_gte_0"),
            models.CheckConstraint(check=Q(monthly_rate__gte=0), name="hm_monthly_rate_gte_0"),
            models.CheckConstraint(check=Q(travel_fee__gte=0), name="hm_travel_fee_gte_0"),
        ]

    @property
    def deposit_balance(self) -> Decimal:
        total = self.user.deposit_transactions.filter(status='completed').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        return total

    def has_sufficient_deposit(self, service_amount: Decimal, category_id=None) -> bool:
        # Source unique de vérité : PricingRule via compute_platform_fee (fallback 11%).
        from handy.services.fees import compute_platform_fee
        required = compute_platform_fee(Decimal(service_amount), category_id=category_id)
        return self.deposit_balance >= required

    def deduct_platform_fee(self, service_amount: Decimal, category_id=None) -> bool:
        """
        Déduit la commission plateforme (PricingRule, fallback 11%) en créant une
        transaction négative (DB-safe & traçable). Retourne False si caution insuffisante.
        """
        from handy.services.fees import compute_platform_fee
        fee = compute_platform_fee(Decimal(service_amount), category_id=category_id)
        if self.deposit_balance >= fee:
            DepositTransaction.objects.create(
                handyman=self.user, type='deduction', amount=-fee, status='completed',
                reference=f"PLATFORM_FEE:{timezone.now().isoformat(timespec='seconds')}"
            )
            return True
        return False

    def profile_completion(self) -> int:
        fields = [
            bool(self.bio),
            self.skills.exists(),
            self.experience_years > 0,
            bool(self.license_number),
            bool(self.cni_number),
            bool(self.insurance_info),
            bool(self.photo),
            self.documents.exists()
        ]
        completed = sum(fields)
        return int((completed / len(fields)) * 100)

    @property
    def is_fully_completed(self) -> bool:
        return self.profile_completion() == 100

    # Documents requis pour valider le KYC (au minimum une pièce d'identité approuvée)
    REQUIRED_KYC_DOCS = {'id_card'}

    def has_required_kyc(self) -> bool:
        approved = set(
            self.documents.filter(status='approved').values_list('document_type', flat=True)
        )
        return self.REQUIRED_KYC_DOCS.issubset(approved)

    def is_on_timeoff(self, at=None) -> bool:
        """L'artisan est-il en congé/absence à l'instant `at` (par défaut maintenant) ?"""
        at = at or timezone.now()
        return self.time_off.filter(start__lte=at, end__gte=at).exists()

    def compute_quality_score(self) -> int:
        """Score de confiance composite 0-100 :
        note (50) + volume de missions (25, plafonné à 50) + KYC vérifié (15)
        + complétude du profil (10)."""
        rating_pts = (Decimal(str(self.rating or 0)) / Decimal('5')) * Decimal('50')
        jobs = min(self.completed_jobs or 0, 50)
        jobs_pts = (Decimal(jobs) / Decimal('50')) * Decimal('25')
        kyc_pts = Decimal('15') if self.is_approved else Decimal('0')
        completion_pts = (Decimal(self.profile_completion()) / Decimal('100')) * Decimal('10')
        total = rating_pts + jobs_pts + kyc_pts + completion_pts
        return int(max(Decimal('0'), min(total, Decimal('100'))))

    def refresh_quality_score(self) -> int:
        self.quality_score = self.compute_quality_score()
        self.save(update_fields=['quality_score'])
        return self.quality_score

    def __str__(self):
        return f"Profil de {self.user.get_full_name() or self.user.username}"


class HandymanDocument(models.Model):
    DOCUMENT_TYPES = [
        ('id_card', 'Carte d\'identité'),
        ('license', 'Permis de conduire'),
        ('casier', 'Casier Judiciaire'),
        ('insurance', 'Assurance'),
        ('certification', 'Certificats/diplomes'),
        ('other', 'Autre'),
    ]

    STATUS_CHOICES = [('pending', 'En attente'), ('approved', 'Approuvé'), ('rejected', 'Rejeté')]

    handyman = models.ForeignKey('HandymanProfile', on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPES)
    file = models.FileField(upload_to='handyman_documents/')
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='documents_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.handyman.user.get_full_name()} - {self.get_document_type_display()}"

    def approve(self, *, by):
        self.status = 'approved'
        self.reviewed_by = by
        self.reviewed_at = timezone.now()
        self.rejection_reason = ''
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'rejection_reason'])
        return self

    def reject(self, *, by, reason=''):
        self.status = 'rejected'
        self.reviewed_by = by
        self.reviewed_at = timezone.now()
        self.rejection_reason = reason
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'rejection_reason'])
        return self


# ---- WALLET / CAUTION ----
class DepositTransaction(models.Model):
    TRANSACTION_TYPES = [('deposit', 'Dépôt'), ('withdrawal', 'Retrait'), ('deduction', 'Déduction mission')]
    STATUS_CHOICES = [('completed', 'Complété'), ('pending', 'En attente'), ('failed', 'Échoué')]

    handyman = models.ForeignKey(User, on_delete=models.CASCADE, related_name='deposit_transactions')
    type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed', db_index=True)
    reference = models.CharField(max_length=100, blank=True, null=True, db_index=True)

    class Meta:
        ordering = ['-date']
        verbose_name = "Transaction de caution"
        verbose_name_plural = "Transactions de cautions"
        indexes = [
            models.Index(fields=["handyman", "status", "-date"]),
        ]
        constraints = [
            # dépôt > 0
            models.CheckConstraint(check=Q(type='deposit', amount__gt=0) | ~Q(type='deposit'), name="dt_deposit_gt0"),
            # retrait/déduction < 0
            models.CheckConstraint(
                check=Q(type__in=['withdrawal', 'deduction'], amount__lt=0) | ~Q(type__in=['withdrawal', 'deduction']),
                name="dt_withdrawal_neg"),
        ]

    def __str__(self):
        return f"{self.get_type_display()} - {self.amount} XOF"

    @staticmethod
    def get_balance(handyman: User):
        total = DepositTransaction.objects.filter(handyman=handyman, status='completed').aggregate(total=Sum('amount'))[
            'total']
        return total or Decimal('0.00')

    def clean(self):
        if self.type == 'deposit' and self.amount <= 0:
            raise ValidationError("Le montant du dépôt doit être positif.")
        if self.type in ['withdrawal', 'deduction'] and self.amount >= 0:
            raise ValidationError("Le montant doit être négatif pour un retrait ou une déduction.")

    def save(self, *args, **kwargs):
        # Débits (retrait/déduction) : contrôle de solde SOUS VERROU pour éviter
        # les race conditions (deux opérations concurrentes lisant le même solde).
        if self.type in ['withdrawal', 'deduction'] and self.status == 'completed':
            with transaction.atomic():
                # verrou pessimiste sur le wallet de l'artisan -> sérialise les débits
                User.objects.select_for_update().get(pk=self.handyman_id)
                balance = DepositTransaction.get_balance(self.handyman)
                if abs(self.amount) > balance:
                    raise ValidationError("Solde insuffisant pour effectuer cette opération.")
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


# ---- CATALOGUE ----
class ServiceCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, null=True)
    icon = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, blank=True, null=True, related_name='children')

    class Meta:
        verbose_name_plural = "Service Categories"
        constraints = [
            UniqueConstraint(fields=["parent", "name"], name="uniq_category_per_parent"),
        ]

    def __str__(self):
        return self.name


class Service(models.Model):
    PRICE_TYPES = [('hourly', "À l'heure"), ('fixed', 'Prix fixe'), ('quote', 'Sur devis')]
    handyman = models.ForeignKey('User', on_delete=models.CASCADE, related_name='services', db_index=True)
    category = models.ForeignKey('ServiceCategory', on_delete=models.CASCADE, related_name='services', db_index=True)
    title = models.CharField(max_length=200, db_index=True)
    description = models.TextField()
    price_type = models.CharField(max_length=20, choices=PRICE_TYPES)
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    duration = models.PositiveIntegerField(blank=True, null=True)  # minutes
    is_active = models.BooleanField(default=True, db_index=True)
    banner = models.ImageField(upload_to='service_images/',null=True)
    image_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["handyman", "is_active"]),
            models.Index(fields=["category", "is_active"]),
        ]
        constraints = [
            # si quote => price is null ; sinon price >= 0
            models.CheckConstraint(
                check=Q(price_type='quote', price__isnull=True) | Q(price_type__in=['hourly', 'fixed'], price__gte=0),
                name="svc_price_logic"
            )
        ]

    def clean(self):
        if self.price_type == 'fixed' and self.price is None:
            raise ValidationError("Prix fixe requis.")
        if self.price_type == 'quote' and self.price is not None:
            raise ValidationError("Un devis n'a pas de prix fixe.")

    def __str__(self):
        return f"{self.title} par {self.handyman.get_full_name() or self.handyman.username}"


class ServiceImage(models.Model):
    service = models.ForeignKey('Service', on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='service_images/')
    alt_text = models.CharField(max_length=255, blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image pour {self.service.title}"


class ServiceArea(models.Model):
    handyman = models.OneToOneField(HandymanProfile, on_delete=models.CASCADE, related_name='service_area')
    center = gis_models.PointField(srid=4326, null=True, blank=True)
    radius_km = models.FloatField(default=10)  # simple
    polygon = gis_models.PolygonField(srid=4326, null=True, blank=True)  # optionnel


class AvailabilitySlot(models.Model):
    handyman = models.ForeignKey(HandymanProfile, on_delete=models.CASCADE, related_name='availability_slots')
    weekday = models.PositiveSmallIntegerField(choices=[(i, i) for i in range(7)])  # 0=Mon
    start_time = models.TimeField()
    end_time = models.TimeField()


class SearchLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    query_text = models.CharField(max_length=255, blank=True, null=True)
    category = models.ForeignKey(ServiceCategory, on_delete=models.SET_NULL, null=True, blank=True)
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ReplacementSuggestion(models.Model):
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='replacement_suggestions')
    original_service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, related_name='+')
    suggested_service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='+')
    score = models.FloatField(default=0)
    accepted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['booking', 'suggested_service'],
                                    name='uniq_replacement_per_service'),
        ]

    @transaction.atomic
    def accept(self):
        """Réassigne la réservation à l'artisan/service suggéré."""
        booking = self.booking
        booking.handyman = self.suggested_service.handyman
        booking.service = self.suggested_service
        booking.save(update_fields=['handyman', 'service', 'updated_at'])
        self.accepted = True
        self.save(update_fields=['accepted'])
        return booking


class TimeOff(models.Model):
    handyman = models.ForeignKey(HandymanProfile, on_delete=models.CASCADE, related_name='time_off')
    start = models.DateTimeField()
    end = models.DateTimeField()
    reason = models.CharField(max_length=200, blank=True, null=True)


class Booking(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'), ('confirmed', 'Confirmé'), ('in_progress', 'En cours'),
        ('completed', 'Terminé'), ('cancelled', 'Annulé'),
    ]
    client = models.ForeignKey('User', on_delete=models.CASCADE, related_name='client_bookings', db_index=True)
    handyman = models.ForeignKey('User', on_delete=models.CASCADE, related_name='handyman_bookings', db_index=True)
    service = models.ForeignKey('Service', on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')

    booking_date = models.DateTimeField()
    end_date = models.DateTimeField(blank=True, null=True)
    address = models.TextField()
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    description = models.TextField(blank=True, null=True)

    proposed_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    handyman_comment = models.TextField(blank=True, null=True)
    response_date = models.DateTimeField(blank=True, null=True)
    job_location = gis_models.PointField(srid=4326, null=True, blank=True)
    requested_start = models.DateTimeField(null=True, blank=True, db_index=True)
    requested_end = models.DateTimeField(null=True, blank=True, db_index=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    cancellation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # pénalité d'annulation appliquée
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    booking_type = models.CharField(
        max_length=20, choices=[('instant', 'Instantané'), ('scheduled', 'Planifié')],
        default='scheduled', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "booking_date"]),
            models.Index(fields=["client", "created_at"]),
            models.Index(fields=["handyman", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(check=Q(end_date__gte=models.F('booking_date')) | Q(end_date__isnull=True),
                                   name="bk_end_after_start"),
            models.CheckConstraint(check=~Q(client=models.F('handyman')), name="bk_client_not_handyman"),
        ]

    def __str__(self):
        return f"Réservation #{self.id} - {self.client} / {self.handyman}"

    @property
    def is_immediate(self) -> bool:
        return self.booking_type == 'instant'

    def generate_replacement_suggestions(self, limit=5):
        """Propose des services de remplacement (même catégorie, autre artisan,
        approuvé) — utilisé quand l'artisan devient indisponible (absence)."""
        if not self.service or not self.service.category_id:
            return []
        candidates = (Service.objects
                      .filter(category_id=self.service.category_id, is_active=True,
                              handyman__handyman_profile__is_approved=True)
                      .exclude(handyman_id=self.handyman_id)
                      .select_related('handyman__handyman_profile')
                      .order_by('-handyman__handyman_profile__rating')[:limit])
        out = []
        for svc in candidates:
            sugg, _ = ReplacementSuggestion.objects.get_or_create(
                booking=self, suggested_service=svc,
                defaults=dict(
                    original_service=self.service,
                    score=float(getattr(svc.handyman.handyman_profile, 'rating', 0) or 0),
                ),
            )
            out.append(sugg)
        return out

    # ----- Machine à états -----
    # Transitions autorisées : source -> {destinations}
    TRANSITIONS = {
        'pending': {'confirmed', 'cancelled'},
        'confirmed': {'in_progress', 'cancelled'},
        'in_progress': {'completed', 'cancelled'},
        'completed': set(),
        'cancelled': set(),
    }

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.TRANSITIONS.get(self.status, set())

    def compute_cancellation_fee(self) -> Decimal:
        """Pénalité d'annulation selon la CancellationPolicy active et le délai
        avant la mission. Gratuit si l'on annule plus de `free_until_minutes`
        avant le début prévu ; sinon `fee_percent` % du montant."""
        policy = CancellationPolicy.objects.filter(active=True).order_by('id').first()
        if not policy:
            return Decimal('0.00')
        payment = getattr(self, 'payment', None)
        base = (payment.amount if payment is not None else None) or self.total_price or Decimal('0')
        if base <= 0:
            return Decimal('0.00')
        if self.booking_date and timezone.now() <= self.booking_date - timedelta(minutes=policy.free_until_minutes):
            return Decimal('0.00')  # dans la fenêtre d'annulation gratuite
        return (Decimal(base) * policy.fee_percent / Decimal('100')).quantize(Decimal('1.'))

    @transaction.atomic
    def transition_to(self, new_status: str, *, actor=None, save: bool = True):
        """Change le statut en validant la transition, horodate dans
        BookingTimeline, et incrémente completed_jobs UNE seule fois à la
        complétion. Lève ValidationError si la transition est interdite.

        `actor` (User) est accepté pour traçabilité/contrôles éventuels.
        """
        if new_status == self.status:
            return self
        if not self.can_transition_to(new_status):
            raise ValidationError(
                f"Transition invalide: {self.status} -> {new_status}."
            )

        previous = self.status
        self.status = new_status
        update_fields = ['status', 'updated_at']
        if new_status == 'completed' and not self.end_date:
            self.end_date = timezone.now()
            update_fields.append('end_date')
        if new_status == 'cancelled':
            self.cancellation_fee = self.compute_cancellation_fee()
            update_fields.append('cancellation_fee')

        if save:
            # PK existant -> update ciblé; sinon save complet
            self.save(update_fields=update_fields if self.pk else None)

        # Horodatage du nouveau statut
        BookingTimeline.objects.create(booking=self, status=new_status)

        # Incrément idempotent : seulement à l'ENTRÉE dans 'completed'
        if new_status == 'completed' and previous != 'completed':
            HandymanProfile.objects.filter(user=self.handyman).update(
                completed_jobs=models.F('completed_jobs') + 1
            )
            prof = HandymanProfile.objects.filter(user=self.handyman).first()
            if prof:
                prof.refresh_quality_score()

        # Escrow : libère (mission terminée) ou rembourse (annulation) le séquestre.
        # getattr fonctionne car le reverse O2O 'payment' lève une DoesNotExist
        # qui hérite d'AttributeError quand aucun paiement n'existe.
        payment = getattr(self, 'payment', None)
        if payment is not None:
            if new_status == 'completed' and payment.status in ('held', 'completed'):
                payment.release(note=f"booking #{self.pk} completed")
            elif new_status == 'cancelled' and payment.status in ('pending', 'held'):
                # remboursement NET de la pénalité d'annulation (le reste est retenu)
                refund_amount = max(payment.amount - (self.cancellation_fee or Decimal('0')), Decimal('0'))
                payment.refund(amount=refund_amount,
                               note=f"booking #{self.pk} cancelled (pénalité={self.cancellation_fee})")
        return self


class Quotation(models.Model):
    STATUS_CHOICES = [('pending', 'En attente'), ('accepted', 'Accepté'), ('rejected', 'Refusé'), ('expired', 'Expiré')]

    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='quotations')
    handyman = models.ForeignKey('User', on_delete=models.CASCADE, related_name='quotations_made')
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    valid_until = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Devis"
        verbose_name_plural = "Devis"
        ordering = ['-created_at']
        unique_together = ('booking', 'handyman')


class Payment(models.Model):
    PAYMENT_METHODS = [
        ('card', 'Carte'), ('transfer', 'Virement'), ('cash', 'Espèces'), ('check', 'Chèque'),
        ('om', 'Orange Money'), ('mtn', 'MTN MoMo'), ('moov', 'Moov Money'), ('wave', 'Wave'),
    ]
    PAYMENT_STATUS = [
        ('pending', 'En attente'),
        ('held', 'Sous séquestre (escrow)'),
        ('released', "Versé à l'artisan"),
        ('completed', 'Complété'),  # legacy / compat
        ('failed', 'Échoué'),
        ('refunded', 'Remboursé'),
    ]
    # États où l'argent du client a effectivement été reçu par la plateforme.
    PAID_STATUSES = ('held', 'released', 'completed')
    # Machine à états de l'escrow : source -> {destinations}
    ESCROW_TRANSITIONS = {
        'pending': {'held', 'failed', 'refunded'},
        'held': {'released', 'refunded'},
        'completed': {'released', 'refunded'},  # tolère l'ancien flux 'completed'
        'released': set(),
        'refunded': set(),
        'failed': set(),
    }

    booking = models.OneToOneField('Booking', on_delete=models.CASCADE, related_name='payment')
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    # <-- Interpréter platform_fee comme MONTANT (pas taux). Pour un taux, créer platform_fee_rate.
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)],
                                       help_text="Montant frais plateforme")
    method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending', db_index=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True, unique=True, db_index=True)
    is_paid = models.BooleanField(default=False, db_index=True)  # garde pour compat; synchro dans save()
    currency = models.CharField(max_length=8, default='XOF')
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # montant remboursé (partiel possible)
    coupon = models.ForeignKey('Coupon', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # réduction appliquée

    payment_date = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        # garder is_paid en phase avec status (escrow : held/released/completed = payé)
        self.is_paid = (self.status in self.PAID_STATUSES)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Paiement #{self.id} - {self.amount} {self.currency}"

    # ----- Escrow / séquestre -----
    def _set_status(self, new_status: str, note: str = ""):
        old = self.status
        self.status = new_status
        if new_status in self.PAID_STATUSES and not self.payment_date:
            self.payment_date = timezone.now()
        self.save(update_fields=["status", "is_paid", "payment_date", "updated_at"])
        PaymentLog.objects.create(
            payment=self, previous_status=old, new_status=new_status, notes=note
        )

    def _check(self, new_status: str):
        if new_status not in self.ESCROW_TRANSITIONS.get(self.status, set()):
            raise ValidationError(
                f"Transition paiement invalide: {self.status} -> {new_status}."
            )

    @transaction.atomic
    def mark_held(self, note: str = "provider confirmed"):
        """Encaissement confirmé par le fournisseur -> fonds placés en séquestre."""
        self._check('held')
        self._set_status('held', note)
        return self

    @transaction.atomic
    def release(self, note: str = "job completed"):
        """Libère les fonds vers l'artisan (mission terminée) + génère la facture."""
        self._check('released')
        self._set_status('released', note)
        Invoice.objects.get_or_create(
            booking=self.booking,
            defaults=dict(
                number=f"INV-{self.booking_id}-{int(timezone.now().timestamp())}",
                amount=self.amount,
                fee=self.platform_fee,
                total=self.amount,
            ),
        )
        return self

    @transaction.atomic
    def refund(self, amount=None, note: str = "refund"):
        """Rembourse le client (annulation / litige). `amount` partiel possible :
        le solde non remboursé correspond à la pénalité retenue."""
        self._check('refunded')
        self.refunded_amount = self.amount if amount is None else min(Decimal(str(amount)), self.amount)
        old = self.status
        self.status = 'refunded'
        self.save(update_fields=["status", "is_paid", "refunded_amount", "updated_at"])
        PaymentLog.objects.create(
            payment=self, previous_status=old, new_status='refunded', notes=note
        )
        return self


class PaymentLog(models.Model):
    payment = models.ForeignKey('Payment', on_delete=models.CASCADE, related_name='logs')
    previous_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    notes = models.TextField(blank=True, null=True)


class Payout(models.Model):
    handyman = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payouts', db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    status = models.CharField(max_length=20,
                              choices=[('pending', 'En attente'), ('sent', 'Envoyé'), ('failed', 'Échoué')],
                              db_index=True)
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)


def artisan_available_earnings(handyman) -> Decimal:
    """Gains disponibles d'un artisan = somme des paiements LIBÉRÉS (net de commission)
    moins les retraits déjà demandés/envoyés (pending|sent)."""
    earned = Payment.objects.filter(
        booking__handyman=handyman, status='released'
    ).aggregate(
        net=Sum(models.F('amount') - models.F('platform_fee'))
    )['net'] or Decimal('0.00')
    withdrawn = Payout.objects.filter(
        handyman=handyman, status__in=['pending', 'sent']
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    return earned - withdrawn


class Dispute(models.Model):
    STATUS_CHOICES = [
        ('open', 'Ouvert'),
        ('under_review', 'En examen'),
        ('resolved', 'Résolu'),
        ('rejected', 'Rejeté'),
    ]
    RESOLUTION_ACTIONS = [
        ('refund_client', 'Remboursement client'),
        ('release_artisan', "Versement à l'artisan"),
        ('none', 'Aucune action'),
    ]
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='disputes')
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='disputes_made')
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open', db_index=True)
    resolution = models.TextField(blank=True, null=True)
    resolution_action = models.CharField(max_length=20, choices=RESOLUTION_ACTIONS, blank=True, default='')
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='disputes_resolved')
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Litige #{self.id} - réservation #{self.booking_id} ({self.status})"

    @transaction.atomic
    def resolve(self, action: str, *, by, resolution: str = ''):
        """Résout le litige et applique l'effet sur l'escrow :
        refund_client -> remboursement du séquestre ; release_artisan -> versement."""
        if action not in dict(self.RESOLUTION_ACTIONS):
            raise ValidationError("Action de résolution invalide.")
        self.status = 'resolved'
        self.resolution_action = action
        self.resolution = resolution
        self.resolved_by = by
        self.resolved_at = timezone.now()
        self.is_resolved = True
        self.save(update_fields=['status', 'resolution_action', 'resolution',
                                 'resolved_by', 'resolved_at', 'is_resolved', 'updated_at'])
        payment = getattr(self.booking, 'payment', None)
        if payment is not None:
            if action == 'refund_client' and payment.status in ('pending', 'held'):
                payment.refund(note=f"dispute #{self.pk}: remboursement client")
            elif action == 'release_artisan' and payment.status in ('held', 'completed'):
                payment.release(note=f"dispute #{self.pk}: versement artisan")
        return self

    @transaction.atomic
    def reject(self, *, by, resolution: str = ''):
        self.status = 'rejected'
        self.resolution = resolution
        self.resolved_by = by
        self.resolved_at = timezone.now()
        self.is_resolved = True
        self.save(update_fields=['status', 'resolution', 'resolved_by',
                                 'resolved_at', 'is_resolved', 'updated_at'])
        return self


class FavoriteHandyman(models.Model):
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorite_handymen')
    handyman = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)


class Review(models.Model):
    booking = models.OneToOneField('Booking', on_delete=models.CASCADE, related_name='review')
    rating = models.PositiveSmallIntegerField(choices=[(i, i) for i in range(1, 6)])
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Avis pour la réservation #{self.booking.id}"


class Conversation(models.Model):
    participants = models.ManyToManyField(User, related_name='conversations')
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='conversation', null=True,
                                blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.booking:
            return f"Conversation pour la réservation #{self.booking.id}"
        return f"Conversation #{self.id}"


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message de {self.sender} dans la conversation #{self.conversation.id}"


class Notification(models.Model):
    TYPES = [
        ('profile_incomplete', 'Profil incomplet'),
        ('profile_completed', 'Profil complété'),
        ('booking_request', 'Demande de réservation'),
        ('booking_confirmed', 'Réservation confirmée'),
        ('booking_cancelled', 'Réservation annulée'),
        ('payment_received', 'Paiement reçu'),
        ('review_received', 'Avis reçu'),
        ('message_received', 'Message reçu'),
        ('booking_status', 'Changement de statut de réservation'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', db_index=True)
    notification_type = models.CharField(max_length=50, choices=TYPES, db_index=True)
    message = models.TextField()
    is_read = models.BooleanField(default=False, db_index=True)

    # Generic relation (remplace related_id)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class Report(models.Model):
    REPORT_TYPE = [
        ('review', 'Avis'),
        ('message', 'Message'),
    ]

    reporter = models.ForeignKey('User', on_delete=models.CASCADE, related_name='reports_made')
    report_type = models.CharField(max_length=50, choices=REPORT_TYPE)
    review = models.ForeignKey('Review', on_delete=models.CASCADE, null=True, blank=True, related_name='reports')
    message = models.ForeignKey('Message', on_delete=models.CASCADE, null=True, blank=True, related_name='reports')
    reason = models.TextField()
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Signalement {self.report_type} par {self.reporter}"


class Device(models.Model):
    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='devices')
    device_token = models.CharField(max_length=255, unique=True)
    device_type = models.CharField(max_length=50, choices=[
        ('android', 'Android'),
        ('ios', 'iOS'),
        ('web', 'Web'),
    ])
    last_active = models.DateTimeField(auto_now=True)
    created_at=models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Device {self.device_type} pour {self.user}"


class IPBlacklist(models.Model):
    ip_address = models.GenericIPAddressField(unique=True)
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.ip_address} - {'Actif' if self.is_active else 'Inactif'}"


class PricingRule(models.Model):
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, null=True, blank=True)
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('11.00'))  # ex: 11%
    fee_min_xof = models.PositiveIntegerField(default=500)
    active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=['active'])]


class JobTracking(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='track_points', db_index=True)
    handyman = models.ForeignKey(User, on_delete=models.CASCADE, db_index=True)
    loc = gis_models.PointField(srid=4326)
    speed = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    ts = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=['booking', '-ts'])]

class BookingRoute(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='route')
    polyline = gis_models.LineStringField(srid=4326, null=True, blank=True)  # chemin prévu
    eta_minutes = models.PositiveIntegerField(default=0)  # ETA courant
    source = models.CharField(max_length=50, default='device')  # device|provider
    updated_at = models.DateTimeField(auto_now=True)

# horodatage des statuts
class BookingTimeline(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='timeline')
    status = models.CharField(max_length=20, choices=Booking.STATUS_CHOICES)
    at = models.DateTimeField(auto_now_add=True)
class PayoutAccount(models.Model):
    handyman = models.OneToOneField(User, on_delete=models.CASCADE, related_name='payout_account')
    provider = models.CharField(max_length=30, choices=[('bank','Bank'), ('om','OrangeMoney'), ('mtn','MTN')])
    account_ref = models.CharField(max_length=120)  # IBAN / phone / wallet id
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class Coupon(models.Model):
    code = models.CharField(max_length=30, unique=True)
    percent_off = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amount_off = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.code

    def is_valid(self, at=None) -> bool:
        at = at or timezone.now()
        return bool(self.active and self.valid_from <= at <= self.valid_to)

    def discount_for(self, amount) -> Decimal:
        amount = Decimal(amount)
        if self.percent_off:
            d = amount * (Decimal(self.percent_off) / Decimal('100'))
        elif self.amount_off:
            d = Decimal(self.amount_off)
        else:
            d = Decimal('0')
        return min(d, amount).quantize(Decimal('1.'))

    def apply(self, amount) -> Decimal:
        """Montant net après réduction (plancher 0)."""
        return (Decimal(amount) - self.discount_for(amount)).quantize(Decimal('1.'))


class OTPCode(models.Model):
    PURPOSES = [('signup', 'Inscription'), ('login', 'Connexion'), ('phone', 'Vérification téléphone')]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_codes')
    code = models.CharField(max_length=6, db_index=True)
    purpose = models.CharField(max_length=20, choices=PURPOSES, default='signup')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=['user', 'used', '-created_at'])]

    def is_valid(self) -> bool:
        return (not self.used) and timezone.now() <= self.expires_at

    @classmethod
    def issue(cls, user, purpose='signup', ttl_minutes=10):
        import secrets
        code = f"{secrets.randbelow(1000000):06d}"
        return cls.objects.create(
            user=user, code=code, purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
        )


class SubscriptionPlan(models.Model):
    AUDIENCES = [('client', 'Client'), ('handyman', 'Artisan'), ('business', 'Entreprise (B2B)')]
    INTERVALS = [('monthly', 'Mensuel'), ('yearly', 'Annuel')]
    name = models.CharField(max_length=80)
    slug = models.SlugField(unique=True)
    audience = models.CharField(max_length=20, choices=AUDIENCES, default='client', db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    interval = models.CharField(max_length=20, choices=INTERVALS, default='monthly')
    features = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.get_interval_display()})"


class Subscription(models.Model):
    STATUS_CHOICES = [('active', 'Actif'), ('cancelled', 'Annulé'), ('expired', 'Expiré')]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions', db_index=True)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    current_period_end = models.DateTimeField()
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'status'])]

    def is_active(self, at=None) -> bool:
        at = at or timezone.now()
        return self.status == 'active' and at <= self.current_period_end

    @classmethod
    def subscribe(cls, user, plan):
        """Souscrit/renouvelle un abonnement actif (annule le précédent actif)."""
        cls.objects.filter(user=user, status='active').update(
            status='cancelled', cancelled_at=timezone.now())
        days = 365 if plan.interval == 'yearly' else 30
        return cls.objects.create(
            user=user, plan=plan, status='active',
            current_period_end=timezone.now() + timedelta(days=days),
        )

    def cancel(self):
        self.status = 'cancelled'
        self.cancelled_at = timezone.now()
        self.save(update_fields=['status', 'cancelled_at'])
        return self

class Invoice(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='invoice')
    number = models.CharField(max_length=50, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    fee = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    issued_at = models.DateTimeField(auto_now_add=True)

class ReviewMedia(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='media')
    image = models.ImageField(upload_to='review_images/')

class CancellationPolicy(models.Model):
    name = models.CharField(max_length=50)
    free_until_minutes = models.PositiveIntegerField(default=60)
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    active = models.BooleanField(default=True)


# handy/api/models/hero_slide.py  (ou dans ton models.py si tu préfères)

User = get_user_model()

# HEX validator (#RRGGBB)
hex_color_re = RegexValidator(
    regex=r'^#(?:[0-9a-fA-F]{3}){1,2}$',
    message="Couleur hex valide attendue (#RRGGBB)"
)

class HeroSlideQuerySet(models.QuerySet):
    def active_now(self):
        now = timezone.now()
        return self.filter(
            is_active=True
        ).filter(
            models.Q(starts_at__isnull=True) | models.Q(starts_at__lte=now),
            models.Q(ends_at__isnull=True) | models.Q(ends_at__gte=now)
        ).order_by('ordering', '-id')

class HeroSlide(models.Model):
    """
    Slide d'accueil : 100% pilotable par l'admin, avec CTA typé.
    """
    CTA_CHOICES = [
        ('open_services', "Ouvrir la liste des services"),
        ('open_categories', "Ouvrir la liste des catégories"),
        ('open_category', "Ouvrir une catégorie précise"),
        ('open_artisans', "Ouvrir la liste des artisans/populaires"),
        ('open_url', "Ouvrir une URL externe"),
    ]

    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=200, blank=True, null=True)

    # image soit uploadée (ImageField) soit URL distante
    image = models.ImageField(upload_to='hero_slides/', blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)

    # dégradé (front: [start, end])
    gradient_start = models.CharField(max_length=7, validators=[hex_color_re], default="#00B14F")
    gradient_end   = models.CharField(max_length=7, validators=[hex_color_re], default="#00D25F")

    cta_label = models.CharField(max_length=40, default="Découvrir")
    cta_action = models.CharField(max_length=30, choices=CTA_CHOICES, default='open_services')

    # params CTA — selon le type d'action (ex. open_category)
    category = models.ForeignKey(ServiceCategory, on_delete=models.SET_NULL, null=True, blank=True)
    target_url = models.URLField(blank=True, null=True)

    # activation/tri
    is_active = models.BooleanField(default=True, db_index=True)
    ordering = models.PositiveIntegerField(default=100, validators=[MinValueValidator(0)], db_index=True)
    starts_at = models.DateTimeField(blank=True, null=True, db_index=True)
    ends_at = models.DateTimeField(blank=True, null=True, db_index=True)

    # tracking simple
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = HeroSlideQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=['is_active', 'ordering']),
            models.Index(fields=['starts_at']),
            models.Index(fields=['ends_at']),
        ]
        ordering = ['ordering', '-id']
        verbose_name = "Slide d'accueil"
        verbose_name_plural = "Slides d'accueil"

    def __str__(self):
        return f"{self.title} [{self.cta_action}]"

    @property
    def image_src(self) -> str:
        """
        Renvoie l'URL de l'image (upload prioritaire, sinon image_url).
        """
        if self.image:
            try:
                return self.image.url
            except Exception:
                pass
        return self.image_url or ""

    def clean(self):
        # Validation CTA
        if self.cta_action == 'open_category' and not self.category:
            from django.core.exceptions import ValidationError
            raise ValidationError("Sélectionnez une catégorie pour l'action 'open_category'.")
        if self.cta_action == 'open_url' and not self.target_url:
            from django.core.exceptions import ValidationError
            raise ValidationError("Renseignez target_url pour l'action 'open_url'.")