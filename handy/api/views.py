# handy/api/views.py
import hashlib
import hmac
from decimal import Decimal
from math import radians, cos, sqrt, sin, asin

from django.conf import settings

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, models
from django.db.models import Count, Q
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, status, mixins
from rest_framework.decorators import action, api_view, permission_classes
from drf_spectacular.utils import extend_schema, OpenApiResponse
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
    return qs.order_by('distance', '-handyman__handyman_profile__rating', 'price')


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

    return (base.select_related('handyman__handyman_profile')
            .annotate(distance=Distance('handyman__handyman_profile__location', booking.job_location))
            .filter(distance__lte=km * 1000)
            .order_by('distance', '-handyman__handyman_profile__rating', 'price'))[:10]


# ---- Pagination (cohérente partout) ----
class DefaultPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


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
    PayoutAccountSerializer, SubscriptionPlanSerializer, SubscriptionSerializer, CompanyProfileSerializer
)

class EmailOrUsernameTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenObtainPairSerializer
    throttle_scope = "login"  # limite anti-bruteforce (cf. DEFAULT_THROTTLE_RATES)
# ---- Users ----
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().only("id", "email", "first_name", "last_name", "user_type", "is_verified")
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
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
class HandymanProfileViewSet(viewsets.ModelViewSet):
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


# ---- Catégories ----
class ServiceCategoryViewSet(viewsets.ModelViewSet):
    queryset = ServiceCategory.objects.all()
    serializer_class = ServiceCategorySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "slug", "description"]
    ordering = ["name"]
    pagination_class = DefaultPageNumberPagination


# ---- Services ----
class ServiceViewSet(viewsets.ModelViewSet):
    queryset = (
        Service.objects.select_related("handyman", "category", "handyman__handyman_profile")
        .prefetch_related("images")
        .all()
    )
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrAdmin]
    owner_lookup = "handyman"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["category", "is_active", "price_type"]
    search_fields = ["title", "description", "handyman__first_name", "handyman__last_name"]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination

    @action(detail=False, methods=["get"],
            permission_classes=[permissions.AllowAny],
            authentication_classes=[])
    def nearby(self, request):
        """
        GET /services/nearby/?lat=..&lng=..&radius_km=15&category_id=...
        Renvoie les services triés par distance.
        """
        lat = request.query_params.get("lat")
        lng = request.query_params.get("lng")
        radius_km = float(request.query_params.get("radius_km", 15))
        cat_id = request.query_params.get("category_id")

        if lat is None or lng is None:
            return Response({"detail": "lat et lng requis."}, status=status.HTTP_400_BAD_REQUEST)

        origin = Point(float(lng), float(lat), srid=4326)
        category = None
        if cat_id:
            try:
                category = ServiceCategory.objects.get(pk=cat_id)
            except ServiceCategory.DoesNotExist:
                return Response({"detail": "category_id invalide."}, status=status.HTTP_400_BAD_REQUEST)

        qs = search_services_nearby_qs(origin, category, radius_km)
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page, many=True)
        return self.get_paginated_response(ser.data)


class ServiceImageViewSet(viewsets.ModelViewSet):
    queryset = ServiceImage.objects.select_related("service").all()
    serializer_class = ServiceImageSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = DefaultPageNumberPagination


# ---- Booking ----
class BookingViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = (
        Booking.objects.select_related("client", "handyman", "service", "service__category")
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
        ser = ServiceSerializer(qs, many=True)
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
        sugg = booking.replacement_suggestions.select_related(
            "suggested_service", "suggested_service__handyman")
        if not sugg.exists():
            booking.generate_replacement_suggestions()
            sugg = booking.replacement_suggestions.select_related(
                "suggested_service", "suggested_service__handyman")
        return Response(ReplacementSuggestionSerializer(sugg, many=True).data)

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
class PaymentViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Payment.objects.select_related("booking", "booking__client", "booking__handyman").all()
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("booking__client", "booking__handyman")
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["status", "method"]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination


class PaymentLogViewSet(OwnerScopedQuerysetMixin, viewsets.ModelViewSet):
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
    queryset = Review.objects.select_related("booking", "booking__client", "booking__handyman").all()
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    owner_lookups = ("booking__client", "booking__handyman")
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination

    def perform_create(self, serializer):
        booking = serializer.validated_data.get("booking")
        if booking and booking.client != self.request.user and not self.request.user.is_staff:
            raise PermissionDenied("Vous ne pouvez noter que vos propres réservations.")
        serializer.save()


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

    def perform_create(self, serializer):
        # L'artisan ne peut téléverser que sur SON propre profil (KYC).
        profile = HandymanProfile.objects.filter(user=self.request.user).first()
        if profile is None:
            raise PermissionDenied("Seul un artisan disposant d'un profil peut téléverser des documents.")
        serializer.save(handyman=profile, status="pending")

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
    """
    ser = PaymentInitSerializer(data=request.data, context={"request": request})
    ser.is_valid(raise_exception=True)
    payload = ser.save()
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
@extend_schema(request=None, responses=OpenApiTypes.OBJECT,
               tags=["OTP"], summary="Envoyer un code OTP de vérification")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def otp_request(request):
    """Génère un code OTP pour l'utilisateur courant et l'envoie (SMS best-effort)."""
    otp = OTPCode.issue(request.user, purpose="signup")
    from handy.tasks import _send_sms, _resolve_msisdn
    _send_sms(_resolve_msisdn(request.user.id), f"Votre code de vérification Tratra : {otp.code}")
    payload = {"sent": True}
    if settings.DEBUG:
        payload["code"] = otp.code  # exposé uniquement en dev
    return Response(payload, status=status.HTTP_201_CREATED)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT,
               tags=["OTP"], summary="Vérifier un code OTP")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def otp_verify(request):
    """Vérifie le code OTP -> marque le compte comme vérifié."""
    code = str(request.data.get("code") or "")
    otp = (OTPCode.objects.filter(user=request.user, code=code, used=False)
           .order_by("-created_at").first())
    if not otp or not otp.is_valid():
        return Response({"detail": "Code invalide ou expiré."}, status=status.HTTP_400_BAD_REQUEST)
    otp.used = True
    otp.save(update_fields=["used"])
    request.user.is_verified = True
    request.user.save(update_fields=["is_verified"])
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

    VALID_STATUSES = {s for s, _ in Payment.PAYMENT_STATUS}

    def _signature_ok(self, request) -> bool:
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
        Provider path: 'om' | 'mtn' | 'card' | 'moov'...
        Header: X-Webhook-Signature: <hex HMAC-SHA256(raw_body, PAYMENT_WEBHOOK_SECRET)>
        Body: { "provider_ref": "...", "status": "completed|failed|refunded" }
        """
        if not self._signature_ok(request):
            return Response({"detail": "Signature invalide."},
                            status=status.HTTP_401_UNAUTHORIZED)

        data = request.data
        provider_ref = data.get("provider_ref")
        new_status = data.get("status")

        if not provider_ref or not new_status:
            return Response({"detail": "provider_ref et status requis."},
                            status=status.HTTP_400_BAD_REQUEST)

        if new_status not in self.VALID_STATUSES:
            return Response({"detail": "status invalide."},
                            status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            p = get_object_or_404(
                Payment.objects.select_for_update(), transaction_id=provider_ref
            )
            try:
                # Le fournisseur ne fait que confirmer l'encaissement ou un remboursement.
                # La LIBÉRATION (held -> released) est interne (à la complétion de la mission).
                if new_status in ('completed', 'held'):
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

    def _auto_generate_slides(self):
        """
        Construit 2-3 slides dynamiques quand il n'y a aucun slide configuré :
        - Promo générique
        - Top catégorie (par volume de services)
        - Artisans certifiés (générique)
        """
        # Top category par nombre de services actifs
        top_cat = (ServiceCategory.objects
                   .filter(is_active=True)
                   .annotate(svc_count=Count('services', filter=models.Q(services__is_active=True)))
                   .order_by('-svc_count')
                   .first())

        slides = []

        slides.append({
            "title": "Jusqu'à -20% aujourd'hui",
            "subtitle": "Interventions rapides et garanties",
            "image": "https://images.unsplash.com/photo-1581578731548-c64695cc6952?q=80&w=1200&auto=format&fit=crop",
            "gradient": ["#0BA360", "#3CBA92"],
            "cta_label": "Je réserve",
            "cta_action": "open_services",
            "ctaParams": {},
            "ordering": 1
        })

        if top_cat:
            slides.append({
                "title": top_cat.name,
                "subtitle": "Experts disponibles près de chez vous",
                "image": "https://images.unsplash.com/photo-1581579188871-cfe9b0b2ce6c?q=80&w=1200&auto=format&fit=crop",
                "gradient": ["#FFC107", "#FFD54F"],
                "cta_label": "Voir +",
                "cta_action": "open_category",
                "ctaParams": {"category_id": top_cat.id},
                "ordering": 2
            })

        slides.append({
            "title": "Artisans certifiés",
            "subtitle": "Qualité, ponctualité, garanties",
            "image": "https://images.unsplash.com/photo-1621905251918-3850a8f4257b?q=80&w=1200&auto=format&fit=crop",
            "gradient": ["#00B14F", "#00D25F"],
            "cta_label": "Découvrir",
            "cta_action": "open_artisans",
            "ctaParams": {},
            "ordering": 3
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