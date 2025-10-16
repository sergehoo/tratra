# handy/api/views.py
from decimal import Decimal
from math import radians, cos, sqrt, sin, asin

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db import transaction, models
from django.db.models import Count
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, status, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework.pagination import PageNumberPagination

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView

from handy.models import (
    User, HandymanProfile, ServiceCategory, Service, ServiceImage, Booking,
    Payment, PaymentLog, Review, Conversation, Message, Notification,
    HandymanDocument, Report, Device,
    # ↓ suivants : assure-toi de les avoir dans tes models (cf. reco précédentes)
    BookingRoute, JobTracking, HeroSlide,  # tracking & ETA
    # Optionnel si tu as ajouté ces modèles :
    # ServiceArea, AvailabilitySlot, TimeOff, ReplacementSuggestion, SearchLog
)


# ---- Permissions simples ----
class IsAuthenticatedOrReadOnly(permissions.IsAuthenticatedOrReadOnly):
    pass


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
    EmailOrUsernameTokenObtainPairSerializer, HeroSlideSerializer
)

class EmailOrUsernameTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenObtainPairSerializer
# ---- Users ----
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().only("id", "email", "first_name", "last_name", "user_type", "is_verified")
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["-id"]
    pagination_class = DefaultPageNumberPagination

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
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["is_approved", "online", "commune"]
    search_fields = ["user__first_name", "user__last_name", "commune", "quartier"]
    ordering = ["-rating", "-completed_jobs"]
    pagination_class = DefaultPageNumberPagination


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
    permission_classes = [IsAuthenticatedOrReadOnly]
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
class BookingViewSet(viewsets.ModelViewSet):
    queryset = (
        Booking.objects.select_related("client", "handyman", "service", "service__category")
        .all()
    )
    permission_classes = [permissions.IsAuthenticated]
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


# ---- Paiements ----
class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.select_related("booking", "booking__client", "booking__handyman").all()
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["status", "method"]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination


class PaymentLogViewSet(viewsets.ModelViewSet):
    queryset = PaymentLog.objects.select_related("payment", "payment__booking").all()
    serializer_class = PaymentLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ["-changed_at"]
    pagination_class = DefaultPageNumberPagination


# ---- Avis / Chat / Notifications / Docs / Reports / Devices ----
class ReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.select_related("booking", "booking__client", "booking__handyman").all()
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination


class ConversationViewSet(viewsets.ModelViewSet):
    queryset = Conversation.objects.select_related("booking").prefetch_related("participants").all()
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ["-updated_at"]
    pagination_class = DefaultPageNumberPagination


class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.select_related("conversation", "sender").all()
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination


class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.select_related("user").all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination


class HandymanDocumentViewSet(viewsets.ModelViewSet):
    queryset = HandymanDocument.objects.select_related("handyman", "handyman__user").all()
    serializer_class = HandymanDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ["-uploaded_at"]
    pagination_class = DefaultPageNumberPagination


class ReportViewSet(viewsets.ModelViewSet):
    queryset = Report.objects.select_related("reporter", "review", "message").all()
    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ["-created_at"]
    pagination_class = DefaultPageNumberPagination


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.select_related("user").all()
    serializer_class = DeviceSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ["-last_active"]
    pagination_class = DefaultPageNumberPagination


# ---- Endpoints “métier” complémentaires ----

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def price_estimate(request):
    """
    Body: { "category_slug": "plomberie", "minutes": 90 }
    """
    ser = PriceEstimateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    return Response(ser.data, status=status.HTTP_200_OK)


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


# ---- Webhook Paiement (idempotent) ----
class PaymentWebhook(APIView):
    authentication_classes = []  # à remplacer par une vérif HMAC (headers/signature)
    permission_classes = []

    def post(self, request, provider):
        """
        Provider path: 'om' | 'mtn' | 'card' | 'moov'...
        Body: { "provider_ref": "...", "status": "completed|failed|refunded" }
        """
        data = request.data
        provider_ref = data.get("provider_ref")
        new_status = data.get("status")

        if not provider_ref or not new_status:
            return Response({"detail": "provider_ref et status requis."},
                            status=status.HTTP_400_BAD_REQUEST)

        # TODO: vérifier signature HMAC (sécurité)
        with transaction.atomic():
            p = Payment.objects.select_for_update().get(transaction_id=provider_ref)
            old = p.status
            if old != new_status:
                p.status = new_status
                p.save(update_fields=["status", "updated_at"])
                PaymentLog.objects.create(
                    payment=p, previous_status=old, new_status=new_status, notes=f"prov={provider}"
                )

        return Response({"ok": True}, status=status.HTTP_200_OK)

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