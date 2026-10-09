# handy/api/views.py
import hashlib
import hmac
import logging
import math
import re
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from math import radians, cos, sqrt, sin, asin
from pathlib import Path
from typing import Optional

from django.conf import settings

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, models
from django.db.models import Avg, Count, Exists, F, OuterRef, Q
from django.db.models.functions import Trim
from django.http import FileResponse, Http404
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers as drf_serializers
from rest_framework import generics, viewsets, permissions, status, mixins
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from drf_spectacular.utils import (
    extend_schema, extend_schema_view, inline_serializer, OpenApiParameter, OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from rest_framework.pagination import PageNumberPagination

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.authentication import JWTAuthentication

from handy.api.errors import CodedAPIException
from handy.eligibility import (
    can_receive_missions, not_on_timeoff, publishable, publishable_user_ids, published_services,
    restrict_public_services,
)
from handy.models import (
    User, HandymanProfile, ServiceCategory, Service, ServiceImage, Booking,
    Payment, PaymentLog, Review, Conversation, Message, Notification,
    HandymanDocument, Report, Device, Payout, Dispute, TimeOff, ReplacementSuggestion,
    Coupon, OTPCode, PayoutAccount, SubscriptionPlan, Subscription, CompanyProfile,
    artisan_available_earnings,
    # ↓ suivants : assure-toi de les avoir dans tes models (cf. reco précédentes)
    BookingRoute, JobTracking, HeroSlide,  # tracking & ETA
    # Optionnel si tu as ajouté ces modèles :
    # ServiceArea, AvailabilitySlot, TimeOff, ReplacementSuggestion, SearchLog
)


# ---- Permissions simples ----
class IsAuthenticatedOrReadOnly(permissions.IsAuthenticatedOrReadOnly):
    pass


class IsOwnerOrAdmin(permissions.BasePermission):
    """Object-level : lecture pour tout utilisateur authentifié, écriture
    (PUT/PATCH/DELETE) réservée au propriétaire de l'objet ou au staff.

    La vue indique le chemin vers le propriétaire via `owner_lookup`
    (ex: "user", "handyman", "booking__client"). Plusieurs chemins possibles
    avec `owner_lookups` (tuple) : OR logique.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_staff:
            return True
        lookups = getattr(view, "owner_lookups", None) or (getattr(view, "owner_lookup", "user"),)
        for lookup in lookups:
            owner = obj
            for part in lookup.split("__"):
                owner = getattr(owner, part, None)
            if owner == user:
                return True
        return False


class OwnerScopedQuerysetMixin:
    """Restreint le queryset aux objets appartenant à `request.user`.

    `owner_lookups` liste les filtres ORM rattachant un objet à l'utilisateur
    (OR logique). Le staff voit tout. Empêche l'IDOR en lecture ET en écriture
    (get_object part de ce queryset filtré → 404 pour les objets d'autrui).
    """

    owner_lookups = ("user",)

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not (user and user.is_authenticated):
            return qs.none()
        if user.is_staff:
            return qs
        q = Q()
        for lookup in self.owner_lookups:
            q |= Q(**{lookup: user})
        return qs.filter(q).distinct()


# ---- Helpers géo / suggestions ----
def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def update_eta_from_last_point(booking: Booking, avg_kmh=25):
    """Fallback ETA si pas d'API d'itinéraire."""
    if not booking.job_location:
        return
    last = booking.track_points.order_by('-ts').first()
    if not last:
        return
    d_m = _haversine_m(
        last.loc.y, last.loc.x,
        booking.job_location.y, booking.job_location.x
    )
    speed_ms = max((avg_kmh * 1000 / 3600), 1.0)
    eta_min = int(d_m / speed_ms / 60)
    route, _ = BookingRoute.objects.get_or_create(booking=booking)
    route.eta_minutes = max(eta_min, 0)
    route.updated_at = timezone.now()
    route.save()


def search_services_nearby_qs(origin_point: Point, category=None, max_km=15):
    qs = (Service.objects
          .filter(is_active=True)
          .select_related('handyman__handyman_profile', 'category')
          .annotate(distance=Distance('handyman__handyman_profile__location', origin_point))
          .filter(distance__lte=max_km * 1000))
    if category:
        qs = qs.filter(category=category)
    # 'id' en dernier : tri total, donc pagination LIMIT/OFFSET stable (sinon les
    # ex aequo — services d'un même artisan — sortent en doublon ou jamais).
    return qs.order_by('distance', '-handyman__handyman_profile__rating',
                       F('price').asc(nulls_last=True), 'id')


def suggest_alternatives_qs(booking: Booking, price_tolerance=Decimal('0.15'), km=10):
    """Services proches, même catégorie, ~même prix."""
    if not booking.service or not booking.job_location:
        return Service.objects.none()

    target_price = booking.service.price or Decimal('0')
    # si le service est "quote", on ne peut pas comparer les prix
    if target_price == 0:
        base = (Service.objects.filter(category=booking.service.category, is_active=True)
                .exclude(pk=booking.service.pk))
    else:
        min_price = target_price * (Decimal('1.0') - price_tolerance)
        max_price = target_price * (Decimal('1.0') + price_tolerance)
        base = (Service.objects.filter(
            category=booking.service.category,
            is_active=True,
            price__gte=min_price, price__lte=max_price)
                .exclude(pk=booking.service.pk))

    return (base.filter(handyman_id__in=publishable_user_ids())
            .select_related('handyman__handyman_profile')
            .annotate(distance=Distance('handyman__handyman_profile__location', booking.job_location))
            .filter(distance__lte=km * 1000)
            .order_by('distance', '-handyman__handyman_profile__rating', 'price'))[:10]


# ---- Pagination (cohérente partout) ----
class DefaultPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ---- Paramètres publics (recherche anonyme, landing) ----
# Les valeurs invalides sont IGNORÉES (jamais de 500) : un lien partagé avec un
# paramètre mal formé doit afficher des résultats, pas une erreur.
logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on", "oui"}
_MAX_PK = 2_147_483_647  # borne d'un IntegerField Postgres
PUBLIC_STATS_CACHE_KEY = "public_stats_v1"
PUBLIC_STATS_TTL = 60


def _flag(params, name) -> bool:
    return str(params.get(name) or "").strip().lower() in _TRUTHY


def _id_list(raw, max_items=50) -> list:
    """« 1,2,x,3 » -> [1, 2, 3] (entiers > 0 uniquement, sans doublon)."""
    ids = []
    for part in str(raw or "").split(","):
        try:
            value = int(part.strip())
        except (TypeError, ValueError):
            continue
        if 0 < value <= _MAX_PK and value not in ids:
            ids.append(value)
            if len(ids) >= max_items:
                break
    return ids


def _text_param(raw, max_len=100) -> str:
    """Texte libre public : sans octet NUL (refusé par Postgres -> 500), rogné, borné."""
    return str(raw or "").replace("\x00", "").strip()[:max_len]


# Bornes de Service.price (DecimalField max_digits=10, decimal_places=2).
_PRICE_BOUND = Decimal("99999999.99")
_CENT = Decimal("0.01")


def _decimal_param(raw) -> Optional[Decimal]:
    """Prix public ramené dans NUMERIC(10,2) : 1e131072 ou 1e-20000 ne lèvent jamais de DataError."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    # Borner AVANT quantize (qui lèverait InvalidOperation au-delà de 28 chiffres).
    # Le sens du filtre est conservé : min_price au-delà de la borne -> aucun résultat,
    # max_price au-delà -> pas de plafond.
    value = max(-_PRICE_BOUND, min(_PRICE_BOUND, value))
    return value.quantize(_CENT)


def _bounded_int(raw, default: int, lo: int, hi: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _round2(value) -> Optional[float]:
    return round(float(value), 2) if value is not None else None


def published_reviews():
    """Avis publiables : liés à une mission TERMINÉE (écarte aussi les avis déjà en
    base créés avant ce contrôle). Même règle que refresh_handyman_rating
    (handy/signal.py). L'auto-évaluation est exclue par construction : la contrainte
    bk_client_not_handyman interdit une réservation dont le client est l'artisan.
    Publics seulement pour un artisan éligible (handy/eligibility.py) : un avis ne met pas
    en avant un artisan qui n'est pas publié.
    """
    return Review.objects.filter(booking__status="completed", booking__handyman_id__in=publishable_user_ids())


def apply_public_service_filters(qs, params, *, restrict=True):
    """Filtres de recherche publics communs à /services/ et /services/nearby/.

    categories=1,2 · category__name=<nom> · commune=<commune ou quartier> · verified=1 · online=1 · urgent=1 · min_price · max_price
    """
    # Publication : seuls les services ACTIFS d'artisans éligibles (compte actif, profil approuvé,
    # KYC approuvé, profil complet) sont publics — règle unique : handy/eligibility.py.
    # `restrict=False` : l'artisan consulte SES propres services (actifs ou non, publiés ou non).
    if restrict:
        qs = restrict_public_services(qs)

    category_ids = _id_list(params.get("categories"))
    if category_ids:
        qs = qs.filter(category_id__in=category_ids)

    commune = _text_param(params.get("commune"))
    if commune:
        # Chemin FK + OneToOne : pas de doublon, pas de .distinct() nécessaire.
        qs = qs.filter(Q(handyman__handyman_profile__commune__icontains=commune)
                       | Q(handyman__handyman_profile__quartier__icontains=commune))

    if _flag(params, "verified"):
        qs = qs.filter(handyman__handyman_profile__is_approved=True)

    if _flag(params, "online"):
        # « En ligne » n'a de sens que pour un profil vérifié (cf. /handymen/presence/).
        qs = qs.filter(handyman__handyman_profile__online=True,
                       handyman__handyman_profile__is_approved=True)

    category_name = _text_param(params.get("category__name"))
    if category_name:
        # Compatibilité app mobile : filtre par nom de catégorie (insensible à la casse).
        qs = qs.filter(category__name__iexact=category_name)

    if _flag(params, "urgent"):
        # « Urgent » = intervention immédiate possible : artisan en ligne MAINTENANT et hors
        # congé/absence (même sens que « Intervention immédiate » sur la landing).
        qs = qs.filter(handyman__handyman_profile__online=True).filter(not_on_timeoff(timezone.now()))

    min_price = _decimal_param(params.get("min_price"))
    if min_price is not None:
        qs = qs.filter(price__gte=min_price)
    max_price = _decimal_param(params.get("max_price"))
    if max_price is not None:
        qs = qs.filter(price__lte=max_price)
    return qs


# Tris publics (?sort=) — complémentaires du paramètre DRF ?ordering= qui reste prioritaire.
SERVICE_SORTS = {
    "recent": ("-created_at", "-id"),
    "price_asc": (F("price").asc(nulls_last=True), "-created_at", "-id"),
    "price_desc": (F("price").desc(nulls_last=True), "-created_at", "-id"),
    "rating": (F("handyman__handyman_profile__rating").desc(nulls_last=True), "-created_at", "-id"),
}

_PUBLIC_SERVICE_FILTER_PARAMS = [
    OpenApiParameter("categories", OpenApiTypes.STR,
                     description="Ids de catégories séparés par des virgules (ex. 1,2,3)."),
    OpenApiParameter("commune", OpenApiTypes.STR,
                     description="Commune ou quartier de l'artisan (contient)."),
    OpenApiParameter("verified", OpenApiTypes.BOOL, description="1 = artisans vérifiés uniquement."),
    OpenApiParameter("online", OpenApiTypes.BOOL, description="1 = artisans vérifiés et en ligne."),
    OpenApiParameter("min_price", OpenApiTypes.NUMBER, description="Prix minimum (FCFA)."),
    OpenApiParameter("max_price", OpenApiTypes.NUMBER, description="Prix maximum (FCFA)."),
]


# ---- Serializers (tu les as déjà) ----
from .serializers import (
    UserSerializer, HandymanProfileSerializer, ServiceCategorySerializer, ServiceSerializer,
    ServiceImageSerializer, BookingSerializer, BookingCreateSerializer,
    PaymentSerializer, PaymentLogSerializer, ReviewSerializer,
    ConversationSerializer, MessageSerializer, NotificationSerializer,
    HandymanDocumentSerializer, ReportSerializer, DeviceSerializer,
    MatchRequestSerializer, MatchResponseSerializer, PriceEstimateSerializer, PaymentInitSerializer,
    EmailOrUsernameTokenObtainPairSerializer, HeroSlideSerializer, PayoutSerializer, DisputeSerializer,
    TimeOffSerializer, ReplacementSuggestionSerializer,
    PayoutAccountSerializer, SubscriptionPlanSerializer, SubscriptionSerializer, CompanyProfileSerializer,
    PublicArtisanSerializer, PublicReviewSerializer,
)

class EmailOrUsernameTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenObtainPairSerializer
    throttle_scope = "login"  # limite anti-bruteforce (cf. DEFAULT_THROTTLE_RATES)
# ---- Users ----
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().only("id", "email", "first_name", "last_name", "user_type", "is_verified")
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    # DELETE -> 405 (L1a) : la suppression effaçait le compte EN CASCADE (réservations,
    # paiements…). La désactivation passera par POST /users/me/deactivate/ (L3b).
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["-id"]
    pagination_class = DefaultPageNumberPagination

    def get_queryset(self):
        # Un utilisateur non-staff ne voit/modifie que son propre compte (anti-IDOR).
        qs = super().get_queryset()
        user = self.request.user
        if user and user.is_authenticated and not user.is_staff:
            return qs.filter(pk=user.pk)
        return qs

    def get_permissions(self):
        if self.action in ['create']:  # inscription
            return [AllowAny()]
        if self.action in ['me']:  # profil courant
            return [IsAuthenticated()]
        return super().get_permissions()

    @action(detail=False, methods=['get'], url_path='me',
            permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        """Retourne le profil de l'utilisateur authentifié."""
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def update_location(self, request, pk=None):
        """
        Body: { "lat": ..., "lng": ... }
        Sauvegarde la dernière position du user (pour suggestions "près de moi").
        """
        user = self.get_object()
        lat = request.data.get("lat")
        lng = request.data.get("lng")
        if lat is None or lng is None:
            return Response({"detail": "lat et lng requis."}, status=status.HTTP_400_BAD_REQUEST)
        user.last_location = Point(float(lng), float(lat), srid=4326)
        user.last_location_ts = timezone.now()
        user.save(update_fields=["last_location", "last_location_ts"])
        return Response({"ok": True})


# ---- Profils artisans ----
def public_profile_queryset():
    """Profils dont la carte publique peut être servie : artisans ÉLIGIBLES (compte actif, profil
    approuvé, KYC approuvé, profil complet — handy/eligibility.py). Même règle que le catalogue,
    /handymen/featured/ et la fiche publique. Annoté pour PublicArtisanSerializer."""
    return (publishable()
            .annotate(services_count=Count("user__services",
                                           filter=Q(user__services__is_active=True),
                                           distinct=True))
            .select_related("user")
            .prefetch_related("skills"))


@extend_schema_view(
    retrieve=extend_schema(description=(
        "Propriétaire (ou staff) : profil complet. Tiers : 404, SAUF pont de compatibilité "
        "(application mobile installée) : un artisan ÉLIGIBLE (compte actif, profil approuvé, KYC "
        "approuvé, profil complet) est renvoyé sous sa forme PUBLIQUE (PublicArtisan, sans email, téléphone, pièce, "
        "licence, assurance ni position).")),
)
class HandymanProfileViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                             mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Profils artisans (L1a, §4.12).

    - Liste et détail : le propriétaire seulement (le staff garde la lecture globale
      jusqu'à L1b, où elle passera à la permission `view_all_records`).
    - `POST /handymen/` et `DELETE /handymen/{id}/` : 405 (pas de mixin create/destroy) ;
      le profil naît du signal `user_type='handyman'` puis de `PUT /users/me/handyman/` (L3b).
    - `PATCH/PUT` : propriétaire, champs réservés en lecture seule (serializer).
    """
    queryset = (
        HandymanProfile.objects.select_related("user")
        .prefetch_related("skills")
        .all()
    )
    serializer_class = HandymanProfileSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
    owner_lookup = "user"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["is_approved", "online", "commune"]
    search_fields = ["user__first_name", "user__last_name", "commune", "quartier"]
    ordering = ["-rating", "-completed_jobs"]
    pagination_class = DefaultPageNumberPagination

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not (user and user.is_authenticated):
            return qs.none()
        if user.is_staff:
            return qs  # L1b : remplacé par la permission view_all_records
        # Auparavant : tout compte connecté lisait le CNI, la licence, l'assurance,
        # la position exacte et l'email de tous les artisans.
        return qs.filter(user=user)

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            # Pont de compatibilité : l'écran Flutter `artisan_profile_screen` appelle
            # GET /handymen/{id}/ pour afficher un artisan. Un tiers ne reçoit QUE la
            # carte publique d'un profil approuvé et actif ; sinon le même 404
            # (inexistant et non publiable indiscernables).
            lookup = self.kwargs[self.lookup_url_kwarg or self.lookup_field]
            public = generics.get_object_or_404(public_profile_queryset(), pk=lookup)
            return Response(PublicArtisanSerializer(public, context=self.get_serializer_context()).data)
        return Response(self.get_serializer(instance).data)

    @action(detail=False, methods=["post"], url_path="presence")
    def presence(self, request):
        """
        POST { "online": true|false } — bascule la présence (dispo temps réel)
        de l'artisan courant. Sans ce flag, /match/ ne renvoie aucun artisan.
        """
        profile = HandymanProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response({"detail": "Profil artisan introuvable."},
                            status=status.HTTP_404_NOT_FOUND)
        online = request.data.get("online")
        if online is None:
            return Response({"detail": "online (booléen) requis."},
                            status=status.HTTP_400_BAD_REQUEST)
        # Conformité : un profil non vérifié ne peut pas se rendre disponible.
        if bool(online) and not profile.is_approved:
            return Response(
                {"detail": "Profil non vérifié : impossible de passer en ligne."},
                status=status.HTTP_403_FORBIDDEN,
            )
        profile.online = bool(online)
        profile.save(update_fields=["online"])
        return Response({"online": profile.online})

    @extend_schema(
        tags=["Public"],
        summary="Artisans vérifiés à la une (public)",
        description=(
            "Artisans approuvés (KYC validé) dont le compte est actif, classés en ligne d'abord "
            "puis par score qualité, note et missions réalisées. Aucune donnée sensible "
            "(email, téléphone, pièce d'identité, licence, position exacte)."
        ),
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, description="Nombre de résultats (1-24, défaut 8)."),
            OpenApiParameter("category", OpenApiTypes.INT, description="Id d'une catégorie."),
            OpenApiParameter("categories", OpenApiTypes.STR,
                             description="Ids de catégories séparés par des virgules."),
            OpenApiParameter("commune", OpenApiTypes.STR,
                             description="Commune ou quartier de l'artisan (contient)."),
            OpenApiParameter("online", OpenApiTypes.BOOL, description="1 = en ligne uniquement."),
        ],
        responses=inline_serializer(
            name="FeaturedArtisansResponse",
            fields={
                "count": drf_serializers.IntegerField(),
                "results": PublicArtisanSerializer(many=True),
            },
        ),
    )
    @action(detail=False, methods=["get"], url_path="featured",
            permission_classes=[AllowAny], authentication_classes=[],
            filter_backends=[], pagination_class=None)
    def featured(self, request):
        """GET /handymen/featured/?limit=8&category=&categories=&commune=&online=1"""
        params = request.query_params
        limit = _bounded_int(params.get("limit"), default=8, lo=1, hi=24)

        # services_count = prestations ACTIVES : le front n'affiche « Voir ses prestations »
        # que s'il y en a (un artisan vérifié peut ne travailler que via /match/).
        qs = public_profile_queryset()

        category_ids = _id_list(params.get("categories"))
        single = _id_list(params.get("category"), max_items=1)
        category_ids = list(dict.fromkeys(single + category_ids))
        if category_ids:
            # Spécialité déclarée OU service actif dans la catégorie. EXISTS évite
            # les doublons d'une jointure m2m (pas de .distinct() nécessaire).
            has_skill = HandymanProfile.skills.through.objects.filter(
                handymanprofile_id=OuterRef("pk"), servicecategory_id__in=category_ids)
            has_service = Service.objects.filter(
                handyman_id=OuterRef("user_id"), is_active=True, category_id__in=category_ids)
            qs = qs.filter(Q(Exists(has_skill)) | Q(Exists(has_service)))

        commune = _text_param(params.get("commune"))
        if commune:
            qs = qs.filter(Q(commune__icontains=commune) | Q(quartier__icontains=commune))
        if _flag(params, "online"):
            qs = qs.filter(online=True)

        qs = qs.order_by("-online", "-quality_score", "-rating", "-completed_jobs", "id")
        total = qs.count()
        data = PublicArtisanSerializer(qs[:limit], many=True, context={"request": request}).data
        return Response({"count": total, "results": data})


# ---- Catégories ----
class ServiceCategoryViewSet(viewsets.ModelViewSet):
    queryset = ServiceCategory.objects.all()
    serializer_class = ServiceCategorySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "slug", "description"]
    ordering_fields = ["name", "services_count"]
    ordering = ["name"]
    pagination_class = DefaultPageNumberPagination

    def get_queryset(self):
        # services_count = nombre de services PUBLIÉS (actifs, artisan éligible) : chiffre réel
        # affiché au public.
        qs = super().get_queryset().annotate(
            services_count=Count(
                "services",
                filter=Q(services__is_active=True, services__handyman_id__in=publishable_user_ids()),
                distinct=True)
        )
        user = getattr(self.request, "user", None)
        if not (user and user.is_authenticated and user.is_staff):
            # Public / non-staff : jamais de catégorie désactivée (liste ET détail).
            qs = qs.filter(is_active=True)
        return qs


# ---- Services ----
_CANONICAL_ID = re.compile(r"[1-9][0-9]{0,18}")


def strict_id_param(params, name):
    """Identifiant en égalité STRICTE : `None` si absent ou vide, `-1` (aucun
    résultat) si la valeur n'est pas un entier canonique unique (« 08 », « 8.0 »,
    « 8abc », plusieurs valeurs…), l'entier sinon. Jamais d'oracle d'existence."""
    values = [v for v in params.getlist(name) if v != ""]
    if not values:
        return None
    if len(values) != 1 or not _CANONICAL_ID.fullmatch(values[0]) or int(values[0]) > _MAX_PK:
        return -1
    return int(values[0])


def handyman_profile_required(user) -> HandymanProfile:
    profile = HandymanProfile.objects.filter(user=user).first() if user.is_authenticated else None
    if profile is None:
        raise CodedAPIException(
            "handyman_profile_required",
            "Un profil artisan est nécessaire pour proposer un service.",
            status=status.HTTP_403_FORBIDDEN,
        )
    return profile


@extend_schema_view(
    list=extend_schema(parameters=_PUBLIC_SERVICE_FILTER_PARAMS + [
        OpenApiParameter("sort", OpenApiTypes.STR,
                         enum=list(SERVICE_SORTS.keys()),
                         description="Tri public : recent | price_asc | price_desc | rating "
                                     "(ignoré si ?ordering= est fourni)."),
        OpenApiParameter("handyman", OpenApiTypes.INT,
                         description="Id utilisateur de l'artisan (égalité stricte ; valeur "
                                     "invalide ou inconnue = liste vide)."),
    ]),
)
class ServiceViewSet(viewsets.ModelViewSet):
    """Catalogue des services. Lecture publique ; écriture par l'artisan propriétaire
    uniquement : `handyman` = request.user, profil artisan requis (403
    `handyman_profile_required`), aucun changement de propriétaire (L1a, §4.7)."""
    queryset = (
        Service.objects.select_related("handyman", "category", "handyman__handyman_profile")
        .prefetch_related("images")
        .all()
    )
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrAdmin]
    owner_lookup = "handyman"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    # `handyman` est filtré à part (égalité stricte, cf. strict_id_param) : le filtre
    # django-filter renvoyait 400 pour un id inconnu (oracle d'existence des comptes).
    filterset_fields = ["category", "is_active", "price_type"]
    # category__* : « plomberie », « ménage » (nom) ou « electricite » (slug sans accent)
    # trouvent le métier. Category est une FK : pas de doublon.
    search_fields = ["title", "description", "category__name", "category__slug",
                     "handyman__first_name", "handyman__last_name"]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination

    def get_queryset(self):
        # Fiche, modification, suppression : un service n'est visible que s'il est PUBLIÉ (actif,
        # artisan éligible) — sauf pour son propriétaire (et le staff). Sinon : 404.
        return published_services(super().get_queryset(), self.request.user)

    def perform_create(self, serializer):
        handyman_profile_required(self.request.user)
        serializer.save(handyman=self.request.user)

    def perform_update(self, serializer):
        user = self.request.user
        handyman_profile_required(user)
        if serializer.instance.handyman_id != user.pk:
            # Staff compris : modifier le service d'autrui reviendrait à se l'approprier.
            raise PermissionDenied("Seul l'artisan propriétaire peut modifier ce service.")
        serializer.save(handyman=user)

    def perform_destroy(self, instance):
        # Un service déjà réservé est désactivé plutôt que supprimé : les réservations
        # (Booking.service, SET_NULL) gardent leur prestation (M-S1).
        if instance.bookings.exists():
            if instance.is_active:
                instance.is_active = False
                instance.save(update_fields=["is_active", "updated_at"])
            return
        instance.delete()

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if getattr(self, "action", None) != "list":
            return queryset
        params = self.request.query_params
        handyman_id = strict_id_param(params, "handyman")
        if handyman_id is not None:
            # L5a : le filtre « public() » ne sera levé que si handyman_id == request.user.pk.
            queryset = queryset.filter(handyman_id=handyman_id)
        # Un artisan qui filtre sur SON propre id voit tous ses services ; tout autre cas : publiés.
        own = handyman_id is not None and self.request.user.is_authenticated and handyman_id == self.request.user.pk
        queryset = apply_public_service_filters(queryset, params, restrict=not own)
        # ?ordering= (DRF) reste prioritaire ; ?sort= ne s'applique qu'en son absence.
        sort = SERVICE_SORTS.get(str(params.get("sort") or "").strip().lower())
        if sort and not params.get(OrderingFilter.ordering_param):
            queryset = queryset.order_by(*sort)
        return queryset

    @extend_schema(
        tags=["Public"],
        summary="Services proches d'une position (public)",
        description="Services actifs dont l'artisan est dans le rayon, triés par distance "
                    "(champ distance_km). lat/lng obligatoires.",
        parameters=[
            OpenApiParameter("lat", OpenApiTypes.NUMBER, required=True),
            OpenApiParameter("lng", OpenApiTypes.NUMBER, required=True),
            OpenApiParameter("radius_km", OpenApiTypes.NUMBER, description="Rayon en km (défaut 15)."),
            OpenApiParameter("category_id", OpenApiTypes.INT,
                             description="Id de catégorie (400 si inexistante)."),
            *_PUBLIC_SERVICE_FILTER_PARAMS,
        ],
        responses=ServiceSerializer(many=True),
    )
    @action(detail=False, methods=["get"],
            permission_classes=[permissions.AllowAny],
            authentication_classes=[], filter_backends=[])
    def nearby(self, request):
        """
        GET /services/nearby/?lat=..&lng=..&radius_km=15&category_id=...
            [&categories=1,2&commune=..&verified=1&online=1&min_price=..&max_price=..]
        Renvoie les services triés par distance.
        """
        params = request.query_params
        lat = params.get("lat")
        lng = params.get("lng")
        cat_id = params.get("category_id")

        if lat in (None, "") or lng in (None, ""):
            return Response({"detail": "lat et lng requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            lat_f, lng_f = float(lat), float(lng)
            radius_km = float(params.get("radius_km") or 15)
        except (TypeError, ValueError):
            return Response({"detail": "lat, lng et radius_km doivent être numériques."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180
                and math.isfinite(radius_km) and radius_km > 0):
            return Response({"detail": "Coordonnées ou rayon hors limites."},
                            status=status.HTTP_400_BAD_REQUEST)

        origin = Point(lng_f, lat_f, srid=4326)
        category = None
        if cat_id:
            parsed = _id_list(cat_id, max_items=1)
            category = ServiceCategory.objects.filter(pk=parsed[0]).first() if parsed else None
            if category is None:
                return Response({"detail": "category_id invalide."}, status=status.HTTP_400_BAD_REQUEST)

        qs = search_services_nearby_qs(origin, category, radius_km).prefetch_related("images")
        qs = apply_public_service_filters(qs, params)
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page, many=True)
        return self.get_paginated_response(ser.data)


class ServiceImageViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    """Images des services de l'artisan courant (L1a). Auparavant : queryset global,
    tout compte connecté pouvait modifier, déplacer ou supprimer l'image d'autrui.
    Un tiers reçoit 404 ; le staff garde la lecture globale jusqu'à L1b."""
    queryset = ServiceImage.objects.select_related("service").order_by("-uploaded_at", "-id")
    serializer_class = ServiceImageSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("service__handyman",)
    pagination_class = DefaultPageNumberPagination


# ---- Booking ----
class BookingViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = (
        # service__handyman__handyman_profile : champ `artisan` de service_detail sans N+1.
        Booking.objects.select_related("client", "handyman", "service", "service__category",
                                       "service__handyman__handyman_profile")
        .prefetch_related("service__images")
        .all()
    )
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("client", "handyman")
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    # ⚠️ "type" n'existe pas dans Booking -> supprimé
    filterset_fields = ["status", "client", "handyman", "service", "booking_date"]
    search_fields = ["city", "postal_code", "description", "address"]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination

    def get_serializer_class(self):
        return BookingCreateSerializer if self.action == "create" else BookingSerializer

    def perform_create(self, serializer):
        # Missions : seuls les artisans éligibles (actif, approuvé, KYC approuvé, profil complet)
        # peuvent recevoir une réservation — règle unique : handy/eligibility.py.
        if not can_receive_missions(serializer.validated_data.get("handyman")):
            raise drf_serializers.ValidationError(
                {"handyman": ["Cet artisan n'est pas éligible aux missions pour le moment."]})
        booking = serializer.save()
        # (option) notifier l'artisan via push (Device) / mail / task Celery

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """Retourne status + logs paiement (simple)."""
        b = self.get_object()
        logs = []
        if hasattr(b, "payment") and b.payment:
            logs = list(b.payment.logs.values("previous_status", "new_status", "changed_at", "notes"))
        return Response(
            {"status": b.status, "created_at": b.created_at, "payment_logs": logs},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def alternatives(self, request, pk=None):
        """
        Alternatives (catégorie identique, +-15% prix, proches).
        À consommer quand l'artisan se déclare indisponible.
        """
        booking = self.get_object()
        qs = suggest_alternatives_qs(booking)
        ser = ServiceSerializer(qs, many=True, context={"request": request})
        return Response(ser.data)

    @action(detail=True, methods=["post"])
    def track(self, request, pk=None):
        """
        POST: { "lat": ..., "lng": ..., "speed": 5.2, "heading": 120 }
        Crée un point JobTracking et met à jour l’ETA.
        """
        booking = self.get_object()
        lat = request.data.get("lat")
        lng = request.data.get("lng")
        speed = request.data.get("speed")
        heading = request.data.get("heading")

        if lat is None or lng is None:
            return Response({"detail": "lat et lng requis."}, status=status.HTTP_400_BAD_REQUEST)

        jt = JobTracking.objects.create(
            booking=booking,
            handyman=booking.handyman,
            loc=Point(float(lng), float(lat), srid=4326),
            speed=float(speed) if speed is not None else None,
            heading=float(heading) if heading is not None else None,
        )
        update_eta_from_last_point(booking)
        return Response({"ok": True, "ts": jt.ts}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def eta(self, request, pk=None):
        """
        Renvoie ETA actuel (minutes) + éventuellement polyline (si tu le renseignes).
        """
        booking = self.get_object()
        route, _ = BookingRoute.objects.get_or_create(booking=booking)
        return Response({
            "eta_minutes": route.eta_minutes,
            "updated_at": route.updated_at,
            # "polyline": route.polyline.geojson if route.polyline else None,  # si besoin
        })

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        """
        POST { "status": "confirmed|in_progress|completed|cancelled" }
        Change le statut via la machine à états (transition validée + timeline).
        Le queryset est déjà cloisonné par propriétaire (anti-IDOR).
        """
        booking = self.get_object()
        new_status = request.data.get("status")
        if not new_status:
            return Response({"detail": "status requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            booking.transition_to(new_status, actor=request.user)
        except DjangoValidationError as e:
            msg = e.messages[0] if getattr(e, "messages", None) else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BookingSerializer(booking).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def replacements(self, request, pk=None):
        """Suggestions de remplacement (générées à la volée si aucune)."""
        booking = self.get_object()
        related = ("suggested_service", "suggested_service__category",
                   "suggested_service__handyman__handyman_profile")
        sugg = booking.replacement_suggestions.select_related(*related)
        if not sugg.exists():
            booking.generate_replacement_suggestions()
            sugg = booking.replacement_suggestions.select_related(*related)
        return Response(ReplacementSuggestionSerializer(
            sugg, many=True, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="accept-replacement")
    def accept_replacement(self, request, pk=None):
        """POST { "suggestion_id": N } -> réassigne la mission à l'artisan suggéré."""
        booking = self.get_object()
        sugg = booking.replacement_suggestions.filter(pk=request.data.get("suggestion_id")).first()
        if not sugg:
            return Response({"detail": "Suggestion introuvable."}, status=status.HTTP_404_NOT_FOUND)
        sugg.accept()
        booking.refresh_from_db()
        return Response(BookingSerializer(booking).data)


# ---- Paiements ----
class PaymentViewSet(OwnerScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Payment.objects.select_related(
        "booking", "booking__client", "booking__handyman",
        "booking__service__category", "booking__service__handyman__handyman_profile",
    ).all()
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("booking__client", "booking__handyman")
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["status", "method"]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination


class PaymentLogViewSet(OwnerScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = PaymentLog.objects.select_related("payment", "payment__booking").all()
    serializer_class = PaymentLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("payment__booking__client", "payment__booking__handyman")
    ordering = ["-changed_at"]
    pagination_class = DefaultPageNumberPagination


# ---- Retraits artisan (payout) ----
class PayoutViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    """L'artisan consulte ses retraits et en demande de nouveaux.
    Le montant est contrôlé contre les gains disponibles, SOUS VERROU."""
    queryset = Payout.objects.select_related("handyman").order_by("-requested_at")
    serializer_class = PayoutSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("handyman",)
    http_method_names = ["get", "post", "head", "options"]
    ordering = ["-requested_at"]
    pagination_class = DefaultPageNumberPagination

    def create(self, request, *args, **kwargs):
        amount = Decimal(str(request.data.get("amount") or "0"))
        if amount <= 0:
            return Response({"detail": "Montant invalide."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            # verrou sur le compte artisan -> sérialise les demandes concurrentes
            User.objects.select_for_update().get(pk=request.user.pk)
            available = artisan_available_earnings(request.user)
            if amount > available:
                return Response(
                    {"detail": f"Gains insuffisants. Disponible: {available}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            payout = Payout.objects.create(handyman=request.user, amount=amount, status="pending")
        return Response(PayoutSerializer(payout).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def available(self, request):
        """GET /payouts/available/ -> gains disponibles au retrait."""
        return Response({"available": str(artisan_available_earnings(request.user))})


# ---- Litiges ----
class DisputeViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    """Ouverture/consultation de litiges par les parties d'une réservation ;
    résolution réservée au staff (déclenche refund/release de l'escrow)."""
    queryset = Dispute.objects.select_related(
        "booking", "booking__client", "booking__handyman", "reporter"
    ).all()
    serializer_class = DisputeSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("reporter", "booking__client", "booking__handyman")
    http_method_names = ["get", "post", "head", "options"]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination

    def perform_create(self, serializer):
        booking = serializer.validated_data.get("booking")
        user = self.request.user
        if not user.is_staff and booking.client_id != user.id and booking.handyman_id != user.id:
            raise PermissionDenied("Vous n'êtes pas partie à cette réservation.")
        serializer.save(reporter=user, status="open")

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def resolve(self, request, pk=None):
        """POST { "action": "refund_client|release_artisan|none|reject", "resolution": "..." }"""
        dispute = self.get_object()
        action_type = request.data.get("action")
        resolution = request.data.get("resolution", "")
        try:
            if action_type == "reject":
                dispute.reject(by=request.user, resolution=resolution)
            else:
                dispute.resolve(action_type, by=request.user, resolution=resolution)
        except DjangoValidationError as e:
            msg = e.messages[0] if getattr(e, "messages", None) else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
        return Response(DisputeSerializer(dispute).data)


# ---- Absences artisan (TimeOff) ----
class TimeOffViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    """Déclaration d'absences par l'artisan. À la création, génère des
    suggestions de remplacement pour les missions impactées."""
    queryset = TimeOff.objects.select_related("handyman", "handyman__user").order_by("-start")
    serializer_class = TimeOffSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("handyman__user",)
    pagination_class = DefaultPageNumberPagination

    def perform_create(self, serializer):
        profile = HandymanProfile.objects.filter(user=self.request.user).first()
        if profile is None:
            raise PermissionDenied("Profil artisan requis pour déclarer une absence.")
        timeoff = serializer.save(handyman=profile)
        impacted = Booking.objects.filter(
            handyman=profile.user, status__in=['pending', 'confirmed'],
            booking_date__gte=timeoff.start, booking_date__lte=timeoff.end,
        )
        for b in impacted:
            b.generate_replacement_suggestions()


# ---- Avis / Chat / Notifications / Docs / Reports / Devices ----
class ReviewViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Review.objects.select_related(
        "booking", "booking__client", "booking__handyman",
        "booking__service__category", "booking__service__handyman__handyman_profile",
    ).all()
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("booking__client", "booking__handyman")
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination

    def get_object(self):
        # L'artisan noté peut LIRE l'avis (queryset cloisonné), jamais le réécrire
        # ni le supprimer : seul l'auteur (client de la réservation) ou le staff.
        review = super().get_object()
        user = self.request.user
        if (self.action in ("update", "partial_update", "destroy")
                and not user.is_staff and review.booking.client_id != user.id):
            raise PermissionDenied("Seul l'auteur de l'avis peut le modifier ou le supprimer.")
        return review

    def perform_create(self, serializer):
        booking = serializer.validated_data["booking"]
        user = self.request.user
        if not user.is_staff:
            if booking.client_id != user.id:
                raise PermissionDenied("Vous ne pouvez noter que vos propres réservations.")
            # Auto-évaluation impossible : client != artisan (contrainte bk_client_not_handyman).
            if booking.status != "completed":
                raise drf_serializers.ValidationError(
                    {"booking": "Seule une mission terminée peut être notée."})
        if Review.objects.filter(booking=booking).exists():
            # Un avis par mission (OneToOne) : 400 explicite plutôt qu'une IntegrityError (500).
            raise drf_serializers.ValidationError({"booking": "Cette mission a déjà été notée."})
        serializer.save()

    @extend_schema(
        tags=["Public"],
        summary="Derniers avis clients publiés (public)",
        description=(
            "Uniquement les avis de missions terminées. count/average "
            "portent sur tous ces avis ; results = les derniers avec commentaire, du plus "
            "récent au plus ancien. Auteur et artisan affichés « Prénom N. », jamais d'email."
        ),
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, description="Nombre d'avis (1-20, défaut 6)."),
        ],
        responses=inline_serializer(
            name="PublicReviewsResponse",
            fields={
                "count": drf_serializers.IntegerField(),
                "average": drf_serializers.FloatField(allow_null=True),
                "results": PublicReviewSerializer(many=True),
            },
        ),
    )
    @action(detail=False, methods=["get"], url_path="public",
            permission_classes=[AllowAny], authentication_classes=[],
            filter_backends=[], pagination_class=None)
    def public(self, request):
        """GET /reviews/public/?limit=6 — n'utilise PAS le queryset cloisonné du viewset."""
        limit = _bounded_int(request.query_params.get("limit"), default=6, lo=1, hi=20)
        published = published_reviews()
        agg = published.aggregate(count=Count("id"), average=Avg("rating"))
        latest = (published
                  .select_related("booking__client", "booking__handyman", "booking__service__category")
                  .exclude(comment__isnull=True)
                  .annotate(comment_trimmed=Trim("comment"))
                  .exclude(comment_trimmed="")
                  .order_by("-created_at", "-id")[:limit])
        return Response({
            "count": agg["count"] or 0,
            "average": _round2(agg["average"]),
            "results": PublicReviewSerializer(latest, many=True, context={"request": request}).data,
        })


class ConversationViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Conversation.objects.select_related("booking").prefetch_related("participants").all()
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("participants",)
    ordering = ["-updated_at"]
    pagination_class = DefaultPageNumberPagination

    def perform_create(self, serializer):
        obj = serializer.save()
        # le créateur est toujours participant de sa conversation
        obj.participants.add(self.request.user)


class MessageViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Message.objects.select_related("conversation", "sender").all()
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("conversation__participants",)
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination

    def perform_create(self, serializer):
        conv = serializer.validated_data.get("conversation")
        if (conv and not self.request.user.is_staff
                and not conv.participants.filter(pk=self.request.user.pk).exists()):
            raise PermissionDenied("Vous ne participez pas à cette conversation.")
        serializer.save(sender=self.request.user)


class NotificationViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Notification.objects.select_related("user").all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("user",)
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class HandymanDocumentViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = HandymanDocument.objects.select_related("handyman", "handyman__user").all()
    serializer_class = HandymanDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("handyman__user",)
    ordering = ["-uploaded_at"]
    pagination_class = DefaultPageNumberPagination
    http_method_names = ["get", "post", "delete", "head", "options"]
    # The API normally uses JWT.  Session auth keeps the Django admin's
    # guarded download link usable without making KYC files public.
    authentication_classes = [JWTAuthentication, SessionAuthentication]

    def perform_create(self, serializer):
        # L'artisan ne peut téléverser que sur SON propre profil (KYC).
        profile = HandymanProfile.objects.filter(user=self.request.user).first()
        if profile is None:
            raise PermissionDenied("Seul un artisan disposant d'un profil peut téléverser des documents.")
        serializer.save(handyman=profile, status="pending")

    def perform_destroy(self, instance):
        if instance.status != "pending" and not self.request.user.is_staff:
            raise PermissionDenied("Un document déjà traité ne peut pas être supprimé.")
        instance.delete()

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Authorize the requester, then stream a private KYC document.

        Streaming keeps the object-store URL out of the browser.  The backing
        storage remains private and can still use signed S3 access internally.
        """
        document = self.get_object()
        if not document.file:
            return Response({"detail": "Fichier introuvable."}, status=status.HTTP_404_NOT_FOUND)

        try:
            opened_file = document.file.open("rb")
        except (FileNotFoundError, ValueError):
            return Response({"detail": "Fichier introuvable."}, status=status.HTTP_404_NOT_FOUND)

        response = FileResponse(
            opened_file,
            as_attachment=True,
            filename=Path(document.file.name).name,
        )

        response["Cache-Control"] = "private, no-store, max-age=0"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def review(self, request, pk=None):
        """POST { "action": "approve|reject", "reason": "..." } — revue KYC (admin)."""
        doc = self.get_object()
        action_type = request.data.get("action")
        if action_type == "approve":
            doc.approve(by=request.user)
        elif action_type == "reject":
            doc.reject(by=request.user, reason=request.data.get("reason", ""))
        else:
            return Response({"detail": "action invalide (approve|reject)."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(HandymanDocumentSerializer(doc).data)


class ReportViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Report.objects.select_related("reporter", "review", "message").all()
    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("reporter",)
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)


class DeviceViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Device.objects.select_related("user").all()
    serializer_class = DeviceSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("user",)
    ordering = ["-last_active"]
    pagination_class = DefaultPageNumberPagination

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


# ---- Endpoints “métier” complémentaires ----

@extend_schema(request=PriceEstimateSerializer, responses=PriceEstimateSerializer,
               tags=["Tarification"], summary="Estimer le prix d'une prestation")
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def price_estimate(request):
    """
    Body: { "category_slug": "plomberie", "minutes": 90 }
    """
    ser = PriceEstimateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    return Response(ser.data, status=status.HTTP_200_OK)


@extend_schema(request=PaymentInitSerializer, responses=OpenApiTypes.OBJECT,
               tags=["Paiements"], summary="Initier un paiement (escrow)")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def payment_initiate(request):
    """
    Body: { "booking_id": 1, "method": "om"|"mtn"|"card"|"cash", "category_id": 3, "minutes": 60 }
    Return: { payment_id, provider, provider_ref, redirect_url|client_secret }

    A method without a configured live provider returns 503; no placeholder
    transaction or predictable provider reference is created.
    """
    from handy.services.gateway import PaymentProviderUnavailable

    ser = PaymentInitSerializer(data=request.data, context={"request": request})
    ser.is_valid(raise_exception=True)
    try:
        payload = ser.save()
    except PaymentProviderUnavailable as exc:
        return Response(
            {"code": exc.code, "detail": str(exc), "method": exc.method},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(payload, status=status.HTTP_201_CREATED)


@extend_schema(request=MatchRequestSerializer, responses=MatchResponseSerializer(many=True),
               tags=["Matching"], summary="Trouver des artisans proches par catégorie")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def match(request):
    """
    Body: { "category_id": 3, "lat": 5.34, "lng": -4.02 }
    Return: artisans classés par distance/rating
    """
    req = MatchRequestSerializer(data=request.data)
    req.is_valid(raise_exception=True)

    lat = req.validated_data["lat"]
    lng = req.validated_data["lng"]
    category_id = req.validated_data["category_id"]

    # Ta fonction domaine
    from handy.services.matching import match_artisans
    qs = match_artisans(lat, lng, category_id)

    origin = Point(lng, lat, srid=4326)
    qs = qs.annotate(distance_m=Distance("location", origin))
    data = MatchResponseSerializer(qs, many=True).data
    return Response(data, status=status.HTTP_200_OK)


# ---- OTP (vérification de compte) ----
OTP_TTL_MINUTES = 10            # durée de validité d'un code
OTP_RESEND_COOLDOWN_S = 60      # délai minimal entre deux codes
OTP_MAX_PER_HOUR = 5            # codes émis par compte et par heure
OTP_MAX_FAILURES = 5            # essais invalides avant invalidation du code


def _otp_error(detail, http_status):
    # Corps {"detail"} seul : les clients affichent le message tel quel (aucun champ technique).
    return Response({"detail": detail}, status=http_status)


@extend_schema(request=None, responses=OpenApiTypes.OBJECT,
               tags=["OTP"], summary="Envoyer un code OTP de vérification par SMS")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def otp_request(request):
    """Génère un code OTP et l'envoie par SMS via le fournisseur configuré (handy/sms.py).

    Jamais de faux succès : sans numéro, sans fournisseur ou si l'envoi échoue, une erreur est
    renvoyée et le code créé est invalidé. Un seul code valide à la fois ; délai et quota
    d'émission par compte (calculés en base : valables quel que soit le nombre de processus).
    """
    from handy import sms

    user = request.user
    if not (user.phone or "").strip():
        return _otp_error("Ajoutez un numéro de téléphone à votre compte pour recevoir un code.", status.HTTP_400_BAD_REQUEST)
    now = timezone.now()
    recent = OTPCode.objects.filter(user=user, created_at__gte=now - timedelta(hours=1))
    last = recent.order_by("-created_at").first()
    if last and (now - last.created_at).total_seconds() < OTP_RESEND_COOLDOWN_S:
        wait = OTP_RESEND_COOLDOWN_S - int((now - last.created_at).total_seconds())
        resp = _otp_error(f"Patientez {wait} s avant de demander un nouveau code.", status.HTTP_429_TOO_MANY_REQUESTS)
        resp["Retry-After"] = str(wait)
        return resp
    if recent.count() >= OTP_MAX_PER_HOUR:
        return _otp_error("Trop de codes demandés. Réessayez dans une heure.", status.HTTP_429_TOO_MANY_REQUESTS)

    OTPCode.objects.filter(user=user, used=False).update(used=True)  # un seul code valide
    otp = OTPCode.issue(user, purpose="signup", ttl_minutes=OTP_TTL_MINUTES)
    try:
        backend = sms.send_sms(user.phone, f"Votre code de vérification Tratra : {otp.code}")
    except sms.SMSError as exc:
        otp.used = True
        otp.save(update_fields=["used"])
        if isinstance(exc, sms.SMSNotConfigured):
            logger.error("OTP non envoyé (user=%s) : fournisseur SMS indisponible ou mal configuré — %s", user.pk, exc)
        else:
            logger.warning("OTP non envoyé (user=%s) : %s", user.pk, exc)
        if isinstance(exc, sms.SMSNotConfigured):
            return _otp_error("L'envoi de SMS n'est pas disponible pour le moment.", status.HTTP_503_SERVICE_UNAVAILABLE)
        return _otp_error("Le SMS n'a pas pu être envoyé. Vérifiez votre numéro puis réessayez.", status.HTTP_502_BAD_GATEWAY)
    payload = {"sent": True, "phone": sms.mask(sms.normalize_msisdn(user.phone)),
               "expires_in": OTP_TTL_MINUTES * 60, "resend_in": OTP_RESEND_COOLDOWN_S}
    if settings.DEBUG and getattr(backend, "exposes_code", False):
        payload["code"] = otp.code  # développement avec le backend « console » uniquement
    return Response(payload, status=status.HTTP_201_CREATED)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT,
               tags=["OTP"], summary="Vérifier un code OTP")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def otp_verify(request):
    """Vérifie le code OTP -> marque le compte comme vérifié.

    Après OTP_MAX_FAILURES essais invalides, les codes en cours sont invalidés : il faut en
    redemander un (soumis au délai et au quota d'émission) — pas de force brute des 10^6 codes.
    """
    user = request.user
    fail_key = f"otp:fail:{user.pk}"
    if (cache.get(fail_key) or 0) >= OTP_MAX_FAILURES:
        return _otp_error("Trop d'essais. Demandez un nouveau code.", status.HTTP_429_TOO_MANY_REQUESTS)
    code = str(request.data.get("code") or "").strip()
    otp = (OTPCode.objects.filter(user=user, used=False).order_by("-created_at").first())
    if not otp or not otp.is_valid() or not secrets.compare_digest(otp.code, code):
        failures = (cache.get(fail_key) or 0) + 1
        cache.set(fail_key, failures, timeout=600)
        if failures >= OTP_MAX_FAILURES:
            OTPCode.objects.filter(user=user, used=False).update(used=True)
            return _otp_error("Code invalide. Trop d'essais : demandez un nouveau code.",
                              status.HTTP_400_BAD_REQUEST)
        left = OTP_MAX_FAILURES - failures
        return Response({"detail": f"Code invalide ou expiré. Il vous reste {left} essai{'s' if left > 1 else ''}."},
                        status=status.HTTP_400_BAD_REQUEST)
    cache.delete(fail_key)
    otp.used = True
    otp.save(update_fields=["used"])
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return Response({"verified": True})


# ---- Coupons ----
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT,
               tags=["Coupons"], summary="Valider un coupon et calculer la réduction")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def coupon_validate(request):
    """POST { "code": "...", "amount": 10000 } -> validité + réduction/net."""
    code = str(request.data.get("code") or "").strip()
    amount = Decimal(str(request.data.get("amount") or "0"))
    coupon = Coupon.objects.filter(code=code).first()
    if not coupon or not coupon.is_valid():
        return Response({"valid": False}, status=status.HTTP_200_OK)
    return Response({
        "valid": True,
        "discount": str(coupon.discount_for(amount)),
        "net": str(coupon.apply(amount)),
    }, status=status.HTTP_200_OK)


# ---- Compte de versement artisan ----
@extend_schema(request=PayoutAccountSerializer,
               responses=OpenApiResponse(PayoutAccountSerializer),
               tags=["Versements"], summary="Compte de versement de l'artisan (GET/upsert)")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
def payout_account(request):
    """GET: compte de versement courant. POST: créer/mettre à jour (repasse non vérifié)."""
    acc = PayoutAccount.objects.filter(handyman=request.user).first()
    if request.method == "GET":
        return Response(PayoutAccountSerializer(acc).data if acc else {})
    ser = PayoutAccountSerializer(acc, data=request.data, partial=bool(acc))
    ser.is_valid(raise_exception=True)
    ser.save(handyman=request.user, verified=False)
    return Response(ser.data, status=status.HTTP_200_OK if acc else status.HTTP_201_CREATED)


# ---- Profil Entreprise (B2B) ----
@extend_schema(request=CompanyProfileSerializer,
               responses=OpenApiResponse(CompanyProfileSerializer),
               tags=["Entreprise (B2B)"], summary="Profil entreprise courant (GET/upsert)")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
def company_profile(request):
    """GET: profil entreprise courant. POST: créer/mettre à jour (verified posé par l'admin)."""
    acc = CompanyProfile.objects.filter(user=request.user).first()
    if request.method == "GET":
        return Response(CompanyProfileSerializer(acc).data if acc else {})
    ser = CompanyProfileSerializer(acc, data=request.data, partial=bool(acc))
    ser.is_valid(raise_exception=True)
    ser.save(user=request.user)
    return Response(ser.data, status=status.HTTP_200_OK if acc else status.HTTP_201_CREATED)


# ---- Chiffres publics (landing) ----
def compute_public_stats() -> dict:
    """Chiffres RÉELS de la plateforme (aucune valeur inventée ni arrondie « marketing »)."""
    approved = publishable()
    reviews = published_reviews().aggregate(count=Count("id"), average=Avg("rating"))
    return {
        "categories": ServiceCategory.objects.filter(is_active=True).count(),
        "services": restrict_public_services(Service.objects.all()).count(),
        "artisans_verified": approved.count(),
        "artisans_online": approved.filter(online=True).count(),
        "missions_completed": Booking.objects.filter(status="completed").count(),
        "reviews_count": reviews["count"] or 0,
        "rating_average": _round2(reviews["average"]),
    }


@extend_schema(
    tags=["Public"],
    summary="Chiffres publics de la plateforme",
    description="Compteurs réels (catégories actives, services actifs, artisans vérifiés / en ligne, "
                "missions terminées, avis de missions terminées et leur note moyenne). "
                "Mis en cache 60 s.",
    responses=inline_serializer(
        name="PublicStats",
        fields={
            "categories": drf_serializers.IntegerField(),
            "services": drf_serializers.IntegerField(),
            "artisans_verified": drf_serializers.IntegerField(),
            "artisans_online": drf_serializers.IntegerField(),
            "missions_completed": drf_serializers.IntegerField(),
            "reviews_count": drf_serializers.IntegerField(),
            "rating_average": drf_serializers.FloatField(allow_null=True),
        },
    ),
)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def public_stats(request):
    """GET /public/stats/ — sans authentification (un jeton invalide est ignoré)."""
    try:
        data = cache.get(PUBLIC_STATS_CACHE_KEY)
    except Exception:  # cache indisponible : on sert des chiffres frais
        logger.warning("Cache indisponible pour %s", PUBLIC_STATS_CACHE_KEY, exc_info=True)
        data = None
    if data is None:
        data = compute_public_stats()
        try:
            cache.set(PUBLIC_STATS_CACHE_KEY, data, PUBLIC_STATS_TTL)
        except Exception:
            logger.warning("Écriture cache impossible pour %s", PUBLIC_STATS_CACHE_KEY, exc_info=True)
    return Response(data)


# ---- Abonnements / B2B ----
class SubscriptionPlanViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = DefaultPageNumberPagination

    def get_queryset(self):
        qs = SubscriptionPlan.objects.filter(active=True).order_by('price')
        audience = self.request.query_params.get('audience')
        return qs.filter(audience=audience) if audience else qs


class SubscriptionViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Subscription.objects.select_related('plan', 'user').order_by('-started_at')
    serializer_class = SubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("user",)
    http_method_names = ["get", "post", "head", "options"]
    pagination_class = DefaultPageNumberPagination

    def create(self, request, *args, **kwargs):
        plan = SubscriptionPlan.objects.filter(pk=request.data.get("plan"), active=True).first()
        if not plan:
            return Response({"detail": "Plan introuvable ou inactif."}, status=status.HTTP_400_BAD_REQUEST)
        sub = Subscription.subscribe(request.user, plan)
        return Response(SubscriptionSerializer(sub).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def current(self, request):
        sub = (Subscription.objects.filter(user=request.user, status="active")
               .order_by("-started_at").first())
        if not sub or not sub.is_active():
            return Response({"active": False})
        return Response(SubscriptionSerializer(sub).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        sub = self.get_object()
        sub.cancel()
        return Response(SubscriptionSerializer(sub).data)


# ---- Webhook Paiement (idempotent + signé) ----
class PaymentWebhook(APIView):
    authentication_classes = []
    permission_classes = []  # pas d'auth utilisateur : on authentifie via signature HMAC
    throttle_scope = "webhook"

    # En-tête portant la signature HMAC-SHA256 hex du corps brut.
    SIGNATURE_HEADER = "HTTP_X_WEBHOOK_SIGNATURE"

    PROVIDER_METHODS = {"om", "mtn", "card"}
    PROVIDER_STATUSES = {"completed", "failed", "refunded"}

    def _signature_ok(self, request, provider) -> bool:
        # Production requires separate secrets: a compromise at one provider
        # must not permit callbacks for another.  The old shared secret is
        # retained only for local development/test compatibility.
        secret = getattr(settings, f"PAYMENT_{provider.upper()}_WEBHOOK_SECRET", "") or ""
        if not secret and settings.DEBUG:
            secret = getattr(settings, "PAYMENT_WEBHOOK_SECRET", "") or ""
        if not secret:
            # fail-closed : pas de secret configuré => on refuse tout.
            return False
        provided = request.META.get(self.SIGNATURE_HEADER, "")
        if not provided:
            return False
        expected = hmac.new(
            secret.encode("utf-8"), request.body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, provided)

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT,
                   tags=["Paiements"], summary="Webhook de paiement (signé HMAC)")
    def post(self, request, provider):
        """
        Provider path: 'om' | 'mtn' | 'card'
        Header: X-Webhook-Signature: <hex HMAC-SHA256(raw_body, PAYMENT_WEBHOOK_SECRET)>
        Body: { "provider_ref": "...", "status": "completed|failed|refunded" }
        """
        provider = provider.lower()
        if provider not in self.PROVIDER_METHODS:
            return Response({"detail": "prestataire invalide."}, status=status.HTTP_400_BAD_REQUEST)

        if not self._signature_ok(request, provider):
            return Response({"detail": "Signature invalide."},
                            status=status.HTTP_401_UNAUTHORIZED)

        data = request.data
        provider_ref = data.get("provider_ref")
        new_status = data.get("status")

        if not provider_ref or not new_status:
            return Response({"detail": "provider_ref et status requis."},
                            status=status.HTTP_400_BAD_REQUEST)

        if new_status not in self.PROVIDER_STATUSES:
            return Response({"detail": "status invalide."},
                            status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            p = get_object_or_404(
                Payment.objects.select_for_update(), transaction_id=provider_ref
            )
            if p.method != provider:
                return Response({"detail": "Référence de paiement incompatible avec ce prestataire."},
                                status=status.HTTP_400_BAD_REQUEST)
            try:
                # Le fournisseur ne fait que confirmer l'encaissement ou un remboursement.
                # La LIBÉRATION (held -> released) est interne (à la complétion de la mission).
                if new_status == 'completed':
                    if p.status == 'pending':
                        p.mark_held(note=f"prov={provider}")
                elif new_status == 'refunded':
                    if p.status in ('pending', 'held', 'completed'):
                        p.refund(note=f"prov={provider}")
                elif new_status == 'failed':
                    if p.status == 'pending':
                        p._set_status('failed', note=f"prov={provider}")
            except DjangoValidationError as e:
                msg = e.messages[0] if getattr(e, "messages", None) else str(e)
                return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"ok": True, "status": p.status}, status=status.HTTP_200_OK)

class HeroSlideViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/slides/ -> slides actifs "now" si dispo,
    sinon fallback auto basé sur catégories/services.
    """
    serializer_class = HeroSlideSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        # Permet de lister tous les slides (ex: /api/slides/?all=true) si staff
        all_param = self.request.query_params.get('all')
        if all_param and self.request.user and self.request.user.is_staff:
            return HeroSlide.objects.all()
        return HeroSlide.objects.active_now()

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        if qs.exists():
            data = HeroSlideSerializer(qs, many=True, context={'request': request}).data
            return Response(data)

        # ------- FALLBACK AUTO -------
        auto = self._auto_generate_slides()
        return Response(auto)

    # Images de repli (Unsplash) : chaque URL a été vérifiée (HTTP 200, image/jpeg).
    FALLBACK_IMAGES = {
        "trust": "https://images.unsplash.com/photo-1581578731548-c64695cc6952?w=1200&q=70&auto=format&fit=crop",
        "category": "https://images.unsplash.com/photo-1504148455328-c376907d081c?w=1200&q=70&auto=format&fit=crop",
        "verified": "https://images.unsplash.com/photo-1621905251189-08b45d6a269e?w=1200&q=70&auto=format&fit=crop",
    }

    def _auto_generate_slides(self):
        """
        Construit 2-3 slides quand aucun slide n'est configuré (consommé par l'app mobile).
        Contenu HONNÊTE uniquement : aucune promo, remise ou chiffre inventé.
        - Proposition de valeur (artisans de confiance)
        - Catégorie la plus fournie (nombre RÉEL de services actifs, seulement si > 0)
        - Artisans vérifiés (KYC : identité et documents contrôlés)
        """
        top_cat = (ServiceCategory.objects
                   .filter(is_active=True)
                   .annotate(svc_count=Count('services', filter=models.Q(services__is_active=True)))
                   .filter(svc_count__gt=0)
                   .order_by('-svc_count', 'name')
                   .first())

        slides = [{
            "title": "Des artisans de confiance",
            "subtitle": "Réservez en quelques minutes, en toute sérénité",
            "image": self.FALLBACK_IMAGES["trust"],
            "gradient": ["#2e8b57", "#1f6a41"],
            "cta_label": "Je réserve",
            "cta_action": "open_services",
            "ctaParams": {},
            "ordering": 1,
        }]

        if top_cat:
            n = top_cat.svc_count
            slides.append({
                "title": top_cat.name,
                "subtitle": f"{n} service{'s' if n > 1 else ''} proposé{'s' if n > 1 else ''} sur Tratra",
                "image": self.FALLBACK_IMAGES["category"],
                "gradient": ["#F6C90E", "#d4aa00"],
                "cta_label": "Voir +",
                "cta_action": "open_category",
                "ctaParams": {"category_id": top_cat.id},
                "ordering": 2,
            })

        slides.append({
            "title": "Artisans vérifiés",
            "subtitle": "Identité et documents contrôlés",
            "image": self.FALLBACK_IMAGES["verified"],
            "gradient": ["#15201b", "#2e8b57"],
            "cta_label": "Découvrir",
            "cta_action": "open_artisans",
            "ctaParams": {},
            "ordering": 3,
        })

        return slides

    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAdminUser])
    def preview_all(self, request):
        """
        Admin helper: voir actifs + inactifs (pour debug).
        """
        qs = HeroSlide.objects.all().order_by('ordering', '-id')
        data = HeroSlideSerializer(qs, many=True, context={'request': request}).data
        return Response(data)
