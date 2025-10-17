from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
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

    def has_sufficient_deposit(self, service_amount: Decimal) -> bool:
        required = Decimal(service_amount) * Decimal('0.11')
        return self.deposit_balance >= required

    def deduct_platform_fee(self, service_amount: Decimal) -> bool:
        """
        Déduit 11% en créant une transaction négative (DB-safe & traçable).
        """
        fee = (Decimal(service_amount) * Decimal('0.11')).quantize(Decimal('0.01'))
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

    handyman = models.ForeignKey('HandymanProfile', on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPES)
    file = models.FileField(upload_to='handyman_documents/')
    description = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.handyman.user.get_full_name()} - {self.get_document_type_display()}"


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
        if self.type in ['withdrawal', 'deduction'] and self.status == 'completed':
            balance = DepositTransaction.get_balance(self.handyman)
            if abs(self.amount) > balance:
                raise ValidationError("Solde insuffisant pour effectuer cette opération.")
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
    created_at = models.DateTimeField(auto_now_add=True)


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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
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
        # étendre plus tard: ('om','OrangeMoney'), ('mtn','MTN'), ('moov','Moov')
    ]
    PAYMENT_STATUS = [('pending', 'En attente'), ('completed', 'Complété'), ('failed', 'Échoué'),
                      ('refunded', 'Remboursé')]

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

    payment_date = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        # garder is_paid en phase avec status
        self.is_paid = (self.status == 'completed')
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Paiement #{self.id} - {self.amount} {self.currency}"


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


class Dispute(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='disputes')
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='disputes_made')
    reason = models.TextField()
    resolution = models.TextField(blank=True, null=True)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


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