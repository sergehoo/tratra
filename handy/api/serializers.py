# handy/api/serializers.py
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.reverse import reverse
from rest_framework.validators import UniqueValidator
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from handy.api.errors import CodedAPIException, field_error
from handy.media.sanitize import sanitize_image
from handy.models import (
    User, HandymanProfile, ServiceCategory, ServiceImage, Service, Booking,
    Payment, PaymentLog, Review, Conversation, Message, Notification,
    HandymanDocument, Report, Device, HeroSlide, Payout, Dispute, TimeOff, ReplacementSuggestion,
    PayoutAccount, SubscriptionPlan, Subscription, CompanyProfile
)
from handy.services.pricing import estimate_price
from handy.services.fees import compute_platform_fee


# ========= IMAGES PUBLIQUES =========

class PublicImageField(serializers.ImageField):
    """Image servie publiquement : JPEG, PNG ou WebP uniquement, réencodée par
    Pillow SANS métadonnées (EXIF/GPS…) et sous un nom aléatoire (§10 L1a)."""

    def to_internal_value(self, data):
        uploaded = super().to_internal_value(data)
        try:
            return sanitize_image(uploaded)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages), code="invalid_image")


# ========= UTIL READ-ONLY MINI SERIALIZERS =========

class UserMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "user_type", "is_verified"]


class ServiceCategorySerializer(serializers.ModelSerializer):
    # Renseigné uniquement quand le queryset est annoté (liste des catégories).
    services_count = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = ["id", "name", "slug", "description", "icon", "is_active", "parent", "services_count"]

    @extend_schema_field(OpenApiTypes.INT)
    def get_services_count(self, obj):
        return getattr(obj, "services_count", None)


# ========= PUBLIC (landing / recherche anonyme) =========
# Ces serializers sont exposés sans authentification : ils ne doivent JAMAIS
# contenir d'email, téléphone, pièce d'identité, licence ni position exacte.

def public_display_name(user) -> str:
    """« Prénom N. » — jamais l'email ni le nom d'utilisateur."""
    first = (getattr(user, "first_name", "") or "").strip()
    last = (getattr(user, "last_name", "") or "").strip()
    if first:
        return f"{first} {last[:1]}." if last else first
    return "Membre Tratra"


def absolute_media_url(request, field) -> Optional[str]:
    if not field:
        return None
    try:
        url = field.url
    except ValueError:
        return None
    if url.startswith(("http://", "https://")):
        return url
    return request.build_absolute_uri(url) if request else url


class PublicUserMiniSerializer(serializers.ModelSerializer):
    """Identité minimale d'un artisan dans les payloads publics (§0.6, L1a) :
    jamais le nom complet, l'email, le rôle ni l'état de vérification du compte."""
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "first_name", "display_name"]
        read_only_fields = fields

    def get_display_name(self, obj) -> str:
        return public_display_name(obj)


class PublicArtisanMiniSerializer(serializers.ModelSerializer):
    """Résumé public d'un profil artisan, embarqué dans les services."""
    display_name = serializers.SerializerMethodField()
    is_verified = serializers.BooleanField(source="is_approved", read_only=True)
    photo = serializers.SerializerMethodField()

    class Meta:
        model = HandymanProfile
        fields = ["id", "display_name", "commune", "rating", "completed_jobs",
                  "experience_years", "is_verified", "online", "photo"]
        read_only_fields = fields

    def get_display_name(self, obj) -> str:
        return public_display_name(obj.user)

    @extend_schema_field(OpenApiTypes.URI)
    def get_photo(self, obj):
        return absolute_media_url(self.context.get("request"), obj.photo)


class PublicArtisanSerializer(PublicArtisanMiniSerializer):
    """Carte artisan publique (artisans à la une) : + spécialités, quartier, tarif."""
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    skills = serializers.SerializerMethodField()
    # Prestations actives (annotation de /handymen/featured/) : 0 -> pas de lien
    # « Voir ses prestations » côté front.
    services_count = serializers.IntegerField(read_only=True, default=0)

    class Meta(PublicArtisanMiniSerializer.Meta):
        fields = PublicArtisanMiniSerializer.Meta.fields + [
            "user_id", "quartier", "hourly_rate", "skills", "services_count"]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_skills(self, obj):
        return [{"id": c.id, "name": c.name, "slug": c.slug} for c in obj.skills.all()]


class PublicReviewSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    artisan = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["id", "rating", "comment", "author", "artisan", "category", "created_at"]
        read_only_fields = fields

    def get_author(self, obj) -> str:
        return public_display_name(obj.booking.client)

    def get_artisan(self, obj) -> str:
        return public_display_name(obj.booking.handyman)

    def get_category(self, obj) -> Optional[str]:
        service = getattr(obj.booking, "service", None)
        return service.category.name if service and service.category_id else None


# ========= USER =========

SIGNUP_UNAVAILABLE_DETAIL = (
    "Inscription impossible avec ces informations. "
    "Si vous avez déjà un compte, connectez-vous."
)
PASSWORD_CHANGE_ENDPOINT_DETAIL = (
    "Le mot de passe ne se modifie pas ici : utilisez la fonction dédiée."
)


def signup_unavailable() -> CodedAPIException:
    # Volontairement sans `fields` : la réponse ne dit pas si c'est l'email ou le
    # nom d'utilisateur qui est déjà pris (anti-énumération, §5.2).
    return CodedAPIException("signup_unavailable", SIGNUP_UNAVAILABLE_DETAIL, status=400)


class UserSerializer(serializers.ModelSerializer):
    """Compte utilisateur (`POST /users/` = inscription legacy, `PATCH /users/{id}/`).

    Règles L1a (§4.12) :
    - inscription : `validate_password`, rôle hors liste blanche refusé (y compris
      `admin`, même pour le staff), `phone` IGNORÉ (enregistré à NULL, à prouver
      ensuite par OTP), conflit d'email ou de username sous le code générique
      `signup_unavailable` (aucun « existe déjà » par champ) ;
    - mise à jour : `password` refusé (400 `password_change_endpoint`, aucun
      stockage en clair), `user_type` en lecture seule.
    """
    password = serializers.CharField(write_only=True, required=False)
    profile_picture = PublicImageField(required=False, allow_null=True)

    class Meta:
        model = User
        # clair et safe (pas de password hash)
        fields = [
            "id", "username", "email", "first_name", "last_name", "user_type",
            "phone", "profile_picture", "address", "city", "postal_code", "country",
            "latitude", "longitude", "is_verified", "date_joined", "last_login",'password',
        ]
        read_only_fields = ['id',"date_joined", "last_login", "is_verified"]

    # Rôles que l'on autorise à l'auto-inscription publique (jamais 'admin').
    SELF_SIGNUP_ROLES = {"client", "employeur", "handyman", "entreprise"}
    _SIGNUP_UNIQUE_FIELDS = ("email", "username", "phone")

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is None:
            # Inscription : mot de passe obligatoire ; téléphone ignoré (M-M5, S-S1).
            fields["password"].required = True
            fields["phone"].read_only = True
            # Pas de « … existe déjà » par champ : le conflit est traité dans
            # validate() sous un code générique (anti-énumération).
            for name in self._SIGNUP_UNIQUE_FIELDS:
                field = fields.get(name)
                if field is not None:
                    field.validators = [v for v in field.validators if not isinstance(v, UniqueValidator)]
        else:
            # `user_type` est déprécié (D14) : jamais modifié après la création.
            fields["user_type"].read_only = True
        return fields

    def to_internal_value(self, data):
        if self.instance is not None and isinstance(data, Mapping) and "password" in data:
            # Auparavant : ModelSerializer.update faisait setattr(password) -> mot de
            # passe stocké EN CLAIR et compte inutilisable.
            raise CodedAPIException(
                "password_change_endpoint", PASSWORD_CHANGE_ENDPOINT_DETAIL, status=400,
                fields={"password": [field_error("password_change_endpoint", PASSWORD_CHANGE_ENDPOINT_DETAIL)]},
            )
        return super().to_internal_value(data)

    def validate_user_type(self, value):
        """Empêche l'escalade de privilège : un compte créé via l'API ne peut pas se
        déclarer 'admin' ni un rôle hors liste blanche (staff compris)."""
        if value not in self.SELF_SIGNUP_ROLES:
            raise serializers.ValidationError(
                "Type de compte non autorisé à l'inscription."
            )
        return value

    def validate_phone(self, value):
        # '' -> NULL : deux chaînes vides violeraient l'unicité du numéro (erreur 500).
        value = (value or "").strip()
        return value or None

    def validate(self, attrs):
        if self.instance is None:
            password = attrs.get("password")
            candidate = User(**{k: attrs.get(k) or "" for k in ("username", "email", "first_name", "last_name")})
            try:
                validate_password(password, user=candidate)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"password": list(exc.messages)})
            email = attrs.get("email") or ""
            username = attrs.get("username") or ""
            if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=username)).exists():
                raise signup_unavailable()
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        validated_data.pop("phone", None)  # inscription legacy : numéro jamais enregistré
        user = User(**validated_data)
        # garde-fou : aucune création publique ne peut octroyer de privilèges Django
        user.is_staff = False
        user.is_superuser = False
        user.set_password(password)
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:
            # Course entre deux inscriptions concurrentes : même réponse générique.
            raise signup_unavailable()
        return user

    def update(self, instance, validated_data):
        # Défense en profondeur : jamais d'écriture brute du mot de passe.
        validated_data.pop("password", None)
        validated_data.pop("user_type", None)
        return super().update(instance, validated_data)

class EmailOrUsernameTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        # champs attendus: username et password (mais on accepte email)
        username = attrs.get("username") or attrs.get("email")
        password = attrs.get("password")

        if not username or not password:
            raise self.fail("no_active_account")

        user = authenticate(
            request=self.context.get("request"),
            username=username,   # ton backend doit supporter username OU email
            password=password,
        )
        if not user:
            raise self.fail("no_active_account")

        data = super().validate({"username": user.get_username(), "password": password})
        # Optionnel: renvoyer un bloc user pour l’app
        data["user"] = {
            "id": user.pk,
            "email": user.email,
            "username": user.get_username(),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
            "date_joined": user.date_joined.isoformat() if user.date_joined else None,
            "user_type": getattr(user, "user_type", "client"),
            "profile_image": getattr(user, "profile_image", None),
            "phone_number": getattr(user, "phone_number", None),
        }
        return data
# ========= HANDYMAN PROFILE =========

class HandymanProfileSerializer(serializers.ModelSerializer):
    """Profil artisan, vu par son PROPRIÉTAIRE (ou le staff) uniquement.

    Champs réservés en lecture seule (§0.6, L1a) : le compte rattaché (`user`),
    l'approbation (`is_approved` : aucune auto-approbation possible), les
    compteurs (`rating`, `completed_jobs`, `quality_score`), la présence
    (`online` : uniquement via POST /handymen/presence/) et les numéros de pièce
    et de licence (`cni_number`, `license_number` : collectés par le KYC).
    """
    # Écriture: skills (ids), latitude/longitude
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    skills = serializers.PrimaryKeyRelatedField(queryset=ServiceCategory.objects.all(), many=True, required=False)
    photo = PublicImageField(required=False, allow_null=True)
    latitude = serializers.FloatField(write_only=True, required=False)
    longitude = serializers.FloatField(write_only=True, required=False)

    # Lecture: détails utiles
    user_detail = UserMiniSerializer(source="user", read_only=True)
    skills_detail = ServiceCategorySerializer(source="skills", many=True, read_only=True)
    location = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = HandymanProfile
        fields = [
            "id", "user", "user_detail",
            "bio", "skills", "skills_detail",
            "experience_years", "license_number", "cni_number", "insurance_info",
            "commune", "quartier",
            "hourly_rate", "daily_rate", "monthly_rate", "travel_fee",
            "availability", "is_approved", "rating", "completed_jobs", "photo",
            "online",
            # géoloc
            "latitude", "longitude", "location",
        ]
        # `quality_score` n'est pas exposé ici (donc jamais accepté en écriture).
        read_only_fields = ["is_approved", "rating", "completed_jobs", "online",
                            "cni_number", "license_number"]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_location(self, obj):
        if getattr(obj, "location", None):
            return {"lat": obj.location.y, "lng": obj.location.x}
        return None

    def create(self, validated_data):
        lat = validated_data.pop("latitude", None)
        lng = validated_data.pop("longitude", None)
        skills = validated_data.pop("skills", [])
        obj = super().create(validated_data)
        if lat is not None and lng is not None:
            obj.location = Point(lng, lat, srid=4326)
        obj.save()
        if skills:
            obj.skills.set(skills)
        return obj

    def update(self, instance, validated_data):
        lat = validated_data.pop("latitude", None)
        lng = validated_data.pop("longitude", None)
        skills = validated_data.pop("skills", None)
        obj = super().update(instance, validated_data)
        if lat is not None and lng is not None:
            obj.location = Point(lng, lat, srid=4326)
            obj.save(update_fields=["location"])
        if skills is not None:
            obj.skills.set(skills)
        return obj


# ========= SERVICE / IMAGES =========

class ServiceImageSerializer(serializers.ModelSerializer):
    """Image d'un service. Écriture : uniquement sur SES services ; le service
    d'une image n'est plus modifiable après sa création (IDOR, §0.6)."""
    image = PublicImageField()

    class Meta:
        model = ServiceImage
        fields = ["id", "service", "image", "alt_text", "uploaded_at"]
        read_only_fields = ["uploaded_at"]

    def get_fields(self):
        fields = super().get_fields()
        service = fields.get("service")
        if service is not None and not service.read_only:
            request = self.context.get("request")
            user = getattr(request, "user", None)
            # Le service d'autrui est traité comme inexistant (400 « pk invalide »),
            # sans révéler son existence.
            service.queryset = (Service.objects.filter(handyman=user)
                                if user is not None and user.is_authenticated
                                else Service.objects.none())
        return fields

    def validate_service(self, value):
        if self.instance is not None and value.pk != self.instance.service_id:
            raise serializers.ValidationError("Le service d'une image n'est pas modifiable.")
        return value


def _allowed_media_hosts():
    return {h.strip().lower().rstrip(".") for h in getattr(settings, "MEDIA_PUBLIC_HOSTS", []) if h.strip()}


def _invalid_image_url() -> CodedAPIException:
    detail = "Adresse d'image refusée : seules les images https hébergées par Tratra sont acceptées."
    return CodedAPIException("invalid_image_url", detail, status=400,
                             fields={"image_url": [field_error("invalid_image_url", detail)]})


class ServiceSerializer(serializers.ModelSerializer):
    # `handyman` est posé par le serveur (= request.user) : jamais au nom d'autrui,
    # jamais de changement de propriétaire (§4.7).
    handyman = serializers.PrimaryKeyRelatedField(read_only=True)
    category = serializers.PrimaryKeyRelatedField(queryset=ServiceCategory.objects.all())
    banner = PublicImageField(required=False, allow_null=True)
    # lecture — /services/ est public : identité minimale SANS email.
    handyman_detail = PublicUserMiniSerializer(source="handyman", read_only=True)
    category_detail = ServiceCategorySerializer(source="category", read_only=True)
    images = ServiceImageSerializer(many=True, read_only=True)
    # Profil public de l'artisan (note, commune, vérifié, en ligne) ; None sans profil.
    artisan = serializers.SerializerMethodField()
    # Distance en km : renseignée uniquement quand le queryset est annoté
    # `distance` (/services/nearby/, alternatives) ; None sinon.
    distance_km = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            "id", "handyman", "handyman_detail", "artisan",
            "category", "category_detail",
            "title", "description",
            "price_type", "price", "duration",'banner','image_url',
            "is_active", "created_at", "updated_at",
            "images", "distance_km",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_image_url(self, value):
        """`https` vers un hôte de stockage du projet (MEDIA_PUBLIC_HOSTS) uniquement :
        ni pixel de pistage tiers, ni http, ni identifiants dans l'URL."""
        if not value:
            return value
        try:
            parts = urlsplit(value)
            hostname = (parts.hostname or "").lower().rstrip(".")
            parts.port  # noqa: B018 - lève ValueError si le port est invalide
        except ValueError:
            raise _invalid_image_url()
        if (parts.scheme.lower() != "https" or not hostname or parts.username is not None
                or parts.password is not None or hostname not in _allowed_media_hosts()):
            raise _invalid_image_url()
        return value

    @extend_schema_field(PublicArtisanMiniSerializer(allow_null=True))
    def get_artisan(self, obj):
        handyman = getattr(obj, "handyman", None)
        # RelatedObjectDoesNotExist hérite d'AttributeError : getattr(..., None) suffit.
        profile = getattr(handyman, "handyman_profile", None) if handyman else None
        if profile is None:
            return None
        return PublicArtisanMiniSerializer(profile, context=self.context).data

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_distance_km(self, obj) -> Optional[float]:
        distance = getattr(obj, "distance", None)
        if distance is None or not hasattr(distance, "km"):
            return None
        return round(float(distance.km), 2)


# ========= BOOKING =========

class BookingCreateSerializer(serializers.ModelSerializer):
    # écriture: IDs + infos pratiques
    service = serializers.PrimaryKeyRelatedField(queryset=Service.objects.all(), required=False, allow_null=True)
    handyman = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    type = serializers.ChoiceField(source='booking_type',
                                   choices=[('instant', 'Instantané'), ('scheduled', 'Planifié')],
                                   required=False, default='scheduled')
    is_immediate = serializers.BooleanField(read_only=True)

    # champs annexes côté pricing/matching (NON stockés sur Booking, retirés avant create)
    category_id = serializers.IntegerField(write_only=True, required=False)
    minutes = serializers.IntegerField(write_only=True, required=False, default=60)

    class Meta:
        model = Booking
        fields = [
            "id", "client", "handyman", "service",
            "booking_date", "end_date",
            "address", "city", "postal_code",
            "description", "proposed_price", "handyman_comment",
            "response_date", "status", "type", "is_immediate",
            # auxiliaires (write_only)
            "category_id", "minutes",
        ]
        read_only_fields = ["client", "status", "response_date", "is_immediate"]

    def validate(self, attrs):
        start = attrs.get("booking_date")
        end = attrs.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError("end_date doit être >= booking_date.")
        return self._validate_parties(attrs)

    def _validate_parties(self, attrs):
        """Cohérence service / artisan / client (§3.4, L1a ; la condition
        « publiable » s'ajoute en L5a). Erreurs au format codé (§4.0)."""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        service = attrs.get("service")
        handyman = attrs.get("handyman")

        if service is not None:
            if not service.is_active or not service.handyman.is_active:
                detail = "Cette prestation n'est plus disponible."
                raise CodedAPIException("service_unavailable", detail, status=400,
                                        fields={"service": [field_error("service_unavailable", detail)]})
            if handyman is not None and handyman.pk != service.handyman_id:
                detail = "L'artisan indiqué ne propose pas cette prestation."
                raise CodedAPIException("handyman_mismatch", detail, status=400,
                                        fields={"handyman": [field_error("handyman_mismatch", detail)]})
            # Sans `handyman` explicite : celui de la prestation (auparavant : erreur 500).
            attrs["handyman"] = handyman = service.handyman
        elif handyman is None:
            raise serializers.ValidationError({"handyman": ["Indiquez une prestation ou un artisan."]})
        elif not handyman.is_active or not HandymanProfile.objects.filter(user=handyman).exists():
            detail = "Cet artisan n'est pas disponible à la réservation."
            raise CodedAPIException("handyman_unavailable", detail, status=400,
                                    fields={"handyman": [field_error("handyman_unavailable", detail)]})

        if user is not None and handyman.pk == user.pk:
            detail = "Vous ne pouvez pas réserver votre propre prestation."
            raise CodedAPIException("self_booking_forbidden", detail, status=400,
                                    fields={"handyman": [field_error("self_booking_forbidden", detail)]})
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        # retirer les champs auxiliaires non persistés sur Booking
        validated_data.pop("category_id", None)
        validated_data.pop("minutes", None)
        validated_data["client"] = request.user
        # tarification non gérée ici : c'est le rôle de /payments/initiate/
        return super().create(validated_data)


class BookingSerializer(serializers.ModelSerializer):
    client_detail = UserMiniSerializer(source="client", read_only=True)
    handyman_detail = UserMiniSerializer(source="handyman", read_only=True)
    service_detail = ServiceSerializer(source="service", read_only=True)
    type = serializers.CharField(source="booking_type", read_only=True)
    is_immediate = serializers.BooleanField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id", "client", "client_detail",
            "handyman", "handyman_detail",
            "service", "service_detail",
            "booking_date", "end_date",
            "address", "city", "postal_code",
            "description", "proposed_price", "handyman_comment",
            "response_date", "status", "type", "is_immediate",
            "created_at", "updated_at",
        ]
        # 'status' n'est PAS modifiable via PATCH : passer par /bookings/{id}/transition/.
        read_only_fields = ["created_at", "updated_at", "status"]


# ========= PAYMENTS =========

class PaymentSerializer(serializers.ModelSerializer):
    booking_detail = BookingSerializer(source="booking", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id", "booking", "booking_detail",
            "amount", "platform_fee", "method", "status",
            "transaction_id", "is_paid", "currency",
            "payment_date", "created_at", "updated_at",
        ]
        read_only_fields = ["is_paid", "created_at", "updated_at"]


class TimeOffSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeOff
        fields = ["id", "handyman", "start", "end", "reason"]
        read_only_fields = ["handyman"]  # posé serveur = profil du requérant

    def validate(self, attrs):
        start, end = attrs.get("start"), attrs.get("end")
        if start and end and end < start:
            raise serializers.ValidationError("end doit être >= start.")
        return attrs


class ReplacementSuggestionSerializer(serializers.ModelSerializer):
    suggested_service_detail = ServiceSerializer(source="suggested_service", read_only=True)

    class Meta:
        model = ReplacementSuggestion
        fields = ["id", "booking", "original_service", "suggested_service",
                  "suggested_service_detail", "score", "accepted", "created_at"]
        read_only_fields = fields


class DisputeSerializer(serializers.ModelSerializer):
    reporter_detail = UserMiniSerializer(source="reporter", read_only=True)

    class Meta:
        model = Dispute
        fields = ["id", "booking", "reporter", "reporter_detail", "reason", "status",
                  "resolution", "resolution_action", "resolved_at", "created_at"]
        # le client/artisan ne fournit que booking + reason ; le reste est serveur/admin.
        read_only_fields = ["reporter", "status", "resolution", "resolution_action",
                            "resolved_at", "created_at"]


class PayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = ["id", "handyman", "amount", "status", "requested_at", "processed_at", "notes"]
        # handyman & statut posés côté serveur (l'artisan ne fait que demander un montant)
        read_only_fields = ["handyman", "status", "requested_at", "processed_at", "notes"]


class CompanyProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyProfile
        fields = ["id", "user", "company_name", "registration_number", "industry",
                  "address", "city", "contact_person", "phone", "website", "verified", "created_at"]
        read_only_fields = ["user", "verified", "created_at"]  # user serveur ; verified par admin


class PayoutAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutAccount
        fields = ["id", "provider", "account_ref", "verified", "created_at"]
        read_only_fields = ["verified", "created_at"]  # la vérification est faite côté admin


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ["id", "name", "slug", "audience", "price", "interval", "features", "active"]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan_detail = SubscriptionPlanSerializer(source="plan", read_only=True)

    class Meta:
        model = Subscription
        fields = ["id", "user", "plan", "plan_detail", "status",
                  "started_at", "current_period_end", "cancelled_at"]
        read_only_fields = ["user", "status", "started_at", "current_period_end", "cancelled_at"]


class PaymentLogSerializer(serializers.ModelSerializer):
    payment_id = serializers.IntegerField(source="payment.id", read_only=True)

    class Meta:
        model = PaymentLog
        fields = ["id", "payment", "payment_id", "previous_status", "new_status", "changed_at", "notes"]
        read_only_fields = ["changed_at"]


# ========= REVIEWS =========

class ReviewSerializer(serializers.ModelSerializer):
    booking = serializers.PrimaryKeyRelatedField(queryset=Booking.objects.all())
    booking_detail = BookingSerializer(source="booking", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "booking", "booking_detail", "rating", "comment", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_booking(self, value):
        # Un avis reste attaché à SA mission : sinon il s'afficherait au nom d'un autre client.
        if self.instance is not None and value.pk != self.instance.booking_id:
            raise serializers.ValidationError("La réservation d'un avis n'est pas modifiable.")
        return value


# ========= CONVERSATION / MESSAGE =========

class ConversationSerializer(serializers.ModelSerializer):
    # écriture par IDs
    participants = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), many=True)
    # lecture
    participants_detail = UserMiniSerializer(source="participants", many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "participants", "participants_detail", "booking", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def create(self, validated_data):
        participants = validated_data.pop("participants", [])
        obj = super().create(validated_data)
        if participants:
            obj.participants.set(participants)
        return obj

    def update(self, instance, validated_data):
        participants = validated_data.pop("participants", None)
        obj = super().update(instance, validated_data)
        if participants is not None:
            obj.participants.set(participants)
        return obj


class MessageSerializer(serializers.ModelSerializer):
    sender_detail = UserMiniSerializer(source="sender", read_only=True)

    class Meta:
        model = Message
        fields = ["id", "conversation", "sender", "sender_detail", "content", "is_read", "created_at"]
        read_only_fields = ["created_at"]


# ========= NOTIFICATIONS / DOCUMENTS / REPORTS / DEVICES =========

class NotificationSerializer(serializers.ModelSerializer):
    user_detail = UserMiniSerializer(source="user", read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "user", "user_detail", "notification_type", "message", "is_read", "created_at"]
        read_only_fields = ["created_at"]


class HandymanDocumentSerializer(serializers.ModelSerializer):
    # lecture détail (le 'handyman' est posé côté serveur = profil du requérant)
    handyman_detail = HandymanProfileSerializer(source="handyman", read_only=True)
    # Do not serialize the storage URL.  The guarded action issues an expiring
    # signed URL only after it has checked document ownership/staff access.
    file = serializers.FileField(write_only=True, required=True, allow_empty_file=False)
    download_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = HandymanDocument
        fields = ["id", "handyman", "handyman_detail", "document_type", "file", "download_url", "description",
                  "status", "reviewed_at", "rejection_reason", "uploaded_at"]
        # statut & revue posés par l'admin ; handyman par le serveur (anti-usurpation)
        read_only_fields = ["handyman", "status", "reviewed_at", "rejection_reason", "uploaded_at"]

    def validate_file(self, uploaded_file):
        max_size = settings.KYC_MAX_UPLOAD_BYTES
        if uploaded_file.size > max_size:
            raise serializers.ValidationError(
                f"Le document ne doit pas dépasser {max_size // (1024 * 1024)} Mo."
            )

        content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
        allowed_extensions = {
            "application/pdf": {".pdf"},
            "image/jpeg": {".jpg", ".jpeg"},
            "image/png": {".png"},
        }
        extension = Path(uploaded_file.name).suffix.lower()
        if (
            content_type not in settings.KYC_ALLOWED_CONTENT_TYPES
            or extension not in allowed_extensions.get(content_type, set())
        ):
            raise serializers.ValidationError(
                "Formats autorisés : PDF, JPEG et PNG."
            )
        return uploaded_file

    @extend_schema_field(OpenApiTypes.URI)
    def get_download_url(self, obj) -> str:
        request = self.context.get("request")
        return reverse("handyman-docs-download", kwargs={"pk": obj.pk}, request=request)


class ReportSerializer(serializers.ModelSerializer):
    reporter_detail = UserMiniSerializer(source="reporter", read_only=True)

    class Meta:
        model = Report
        fields = ["id", "reporter", "reporter_detail", "report_type", "review", "message", "reason", "is_resolved", "created_at"]
        read_only_fields = ["created_at"]


class DeviceSerializer(serializers.ModelSerializer):
    user_detail = UserMiniSerializer(source="user", read_only=True)

    class Meta:
        model = Device
        fields = ["id", "user", "user_detail", "device_token", "device_type", "last_active", "created_at"]
        read_only_fields = ["last_active", "created_at"]


# ========= EXTRA SERIALIZERS (matching, pricing, payments) =========

class MatchRequestSerializer(serializers.Serializer):
    category_id = serializers.IntegerField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class MatchResponseSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="user.get_full_name")
    distance_m = serializers.SerializerMethodField()

    class Meta:
        model = HandymanProfile
        fields = ["id", "full_name", "rating", "completed_jobs", "distance_m"]

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_distance_m(self, obj):
        # L'annotation Distance() renvoie un objet mesure GeoDjango, pas un float.
        d = getattr(obj, "distance_m", None)
        if d is None:
            return None
        return float(d.m) if hasattr(d, "m") else float(d)


class PriceEstimateSerializer(serializers.Serializer):
    category_slug = serializers.CharField()
    minutes = serializers.IntegerField(min_value=1)

    def to_representation(self, instance):
        # instance == validated_data
        amount = estimate_price(instance["category_slug"], instance["minutes"])
        return {"amount_xof": int(amount)}


class PaymentInitSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField()
    method = serializers.ChoiceField(choices=Payment.PAYMENT_METHODS)
    category_id = serializers.IntegerField(required=False)
    minutes = serializers.IntegerField(min_value=1)
    coupon_code = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        try:
            booking = (Booking.objects.select_related("service", "service__category", "client")
                       .get(pk=attrs["booking_id"]))
        except Booking.DoesNotExist:
            raise serializers.ValidationError({"booking_id": "Réservation introuvable."})

        user = self.context["request"].user
        if not user.is_staff and booking.client_id != user.id:
            raise serializers.ValidationError({"booking_id": "Vous ne pouvez payer que vos propres réservations."})
        if booking.status == "cancelled":
            raise serializers.ValidationError({"booking_id": "Une réservation annulée ne peut pas être payée."})

        if attrs.get("category_id") and booking.service_id:
            if attrs["category_id"] != booking.service.category_id:
                raise serializers.ValidationError({"category_id": "La catégorie ne correspond pas à la réservation."})

        attrs["booking"] = booking
        return attrs

    def create(self, validated):
        """
        Initialise un paiement uniquement lorsqu'un vrai fournisseur existe.

        Les méthodes non intégrées échouent explicitement sans créer de faux
        Payment pending ni de référence prédictible.
        """
        from handy.services.gateway import PaymentProviderUnavailable, provider_for_method

        booking = validated["booking"]
        svc = booking.service
        category_id = validated.get("category_id") or (svc.category_id if svc else None)
        category_slug = svc.category.slug if svc and svc.category else "menage"
        minutes = validated["minutes"]

        # pricing
        amount = Decimal(estimate_price(category_slug, minutes))

        # coupon éventuel (ignoré silencieusement si invalide)
        coupon, discount = None, Decimal('0')
        code = (validated.get("coupon_code") or "").strip()
        if code:
            from handy.models import Coupon
            c = Coupon.objects.filter(code=code).first()
            if c and c.is_valid():
                discount = c.discount_for(amount)
                amount = c.apply(amount)
                coupon = c

        # frais plateforme sur le montant NET
        fee = compute_platform_fee(amount, category_id=category_id)

        method = validated["method"]
        provider = provider_for_method(method)
        if not provider.is_available:
            raise PaymentProviderUnavailable(method)

        # An existing payment must never be silently rebound to a different
        # provider reference or amount.  It is safe to return the manual cash
        # record because it does not claim that funds were received.
        existing = Payment.objects.filter(booking=booking).first()
        if existing:
            if existing.method != method:
                raise serializers.ValidationError(
                    {"method": "Un paiement existe déjà pour cette réservation avec une autre méthode."}
                )
            if existing.status != "pending":
                raise serializers.ValidationError({"booking_id": "Ce paiement n'est plus réinitialisable."})
            if method == "cash":
                return {
                    "payment_id": existing.id,
                    "provider": "cash",
                    "status": existing.status,
                    "requires_customer_action": True,
                    "instructions": "Paiement en espèces à confirmer manuellement après la prestation.",
                }
            if existing.transaction_id:
                return {
                    "payment_id": existing.id,
                    "provider": existing.method,
                    "provider_ref": existing.transaction_id,
                    "status": existing.status,
                    "already_initiated": True,
                }
            raise serializers.ValidationError({"booking_id": "Une tentative de paiement est déjà en cours."})

        # This call fails closed for the placeholder adapters.  It happens
        # before a Payment row is created so the UI cannot mistake a stub for
        # an actionable payment flow.
        res = provider.create(booking, int(amount))
        provider_ref = res.get("provider_ref")
        if method != "cash" and not provider_ref:
            raise serializers.ValidationError({"method": "Le prestataire n'a pas retourné de référence de transaction."})

        payment = Payment.objects.create(
            booking=booking,
            amount=amount,
            platform_fee=fee,
            method=method,
            status="pending",
            currency="XOF",
            coupon=coupon,
            discount=discount,
            transaction_id=provider_ref,
        )
        return {"payment_id": payment.id, **res}

class HeroSlideSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    gradient = serializers.SerializerMethodField()
    ctaParams = serializers.SerializerMethodField()

    class Meta:
        model = HeroSlide
        fields = [
            'id',
            'title',
            'subtitle',
            'image',          # URL resolue
            'gradient',       # ["#start", "#end"]
            'cta_label',
            'cta_action',
            'ctaParams',      # dict: {category_id:..., url:...}
            'ordering',
        ]

    def get_image(self, obj: HeroSlide) -> str:
        return obj.image_src

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_gradient(self, obj: HeroSlide):
        return [obj.gradient_start, obj.gradient_end]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_ctaParams(self, obj: HeroSlide):
        if obj.cta_action == 'open_category' and obj.category_id:
            return {'category_id': obj.category_id}
        if obj.cta_action == 'open_url' and obj.target_url:
            return {'url': obj.target_url}
        return {}
