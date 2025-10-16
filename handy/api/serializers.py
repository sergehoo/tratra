# handy/api/serializers.py
from decimal import Decimal
from typing import Optional

from django.contrib.auth import authenticate
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from handy.models import (
    User, HandymanProfile, ServiceCategory, ServiceImage, Service, Booking,
    Payment, PaymentLog, Review, Conversation, Message, Notification,
    HandymanDocument, Report, Device, HeroSlide
)
from handy.services.pricing import estimate_price
from handy.services.fees import compute_platform_fee


# ========= UTIL READ-ONLY MINI SERIALIZERS =========

class UserMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "user_type", "is_verified"]


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ["id", "name", "slug", "description", "icon", "is_active", "parent"]


# ========= USER =========

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        # clair et safe (pas de password hash)
        fields = [
            "id", "username", "email", "first_name", "last_name", "user_type",
            "phone", "profile_picture", "address", "city", "postal_code", "country",
            "latitude", "longitude", "is_verified", "date_joined", "last_login",'password',
        ]
        read_only_fields = ['id',"date_joined", "last_login", "is_verified"]

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

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
    # Écriture: user (id), skills (ids), latitude/longitude
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    skills = serializers.PrimaryKeyRelatedField(queryset=ServiceCategory.objects.all(), many=True, required=False)
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
    class Meta:
        model = ServiceImage
        fields = ["id", "service", "image", "alt_text", "uploaded_at"]
        read_only_fields = ["uploaded_at"]


class ServiceSerializer(serializers.ModelSerializer):
    # écriture
    handyman = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    category = serializers.PrimaryKeyRelatedField(queryset=ServiceCategory.objects.all())
    # lecture
    handyman_detail = UserMiniSerializer(source="handyman", read_only=True)
    category_detail = ServiceCategorySerializer(source="category", read_only=True)
    images = ServiceImageSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = [
            "id", "handyman", "handyman_detail",
            "category", "category_detail",
            "title", "description",
            "price_type", "price", "duration",
            "is_active", "created_at", "updated_at",
            "images",
        ]
        read_only_fields = ["created_at", "updated_at"]


# ========= BOOKING =========

class BookingCreateSerializer(serializers.ModelSerializer):
    # écriture: IDs + infos pratiques
    service = serializers.PrimaryKeyRelatedField(queryset=Service.objects.all(), required=False, allow_null=True)
    handyman = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    type = serializers.ChoiceField(choices=[('instant', 'Instantané'), ('scheduled', 'Planifié')], default='scheduled')
    is_immediate = serializers.BooleanField(read_only=True)

    # champs annexes côté pricing/matching (non stockés)
    category_id = serializers.IntegerField(write_only=True, required=False)
    minutes = serializers.IntegerField(write_only=True, required=False, default=60)

    class Meta:
        model = Booking
        fields = [
            "id", "client", "handyman", "service",
            "booking_date", "end_date",
            "address", "city", "postal_code",
            "description", "proposed_price", "handyman_comment",
            "response_date", "status",
            "type", "is_immediate",
            # auxiliaires
            "category_id", "minutes",
        ]
        read_only_fields = ["client", "status", "is_immediate", "response_date"]

    def validate(self, attrs):
        start = attrs.get("booking_date")
        end = attrs.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError("end_date doit être >= booking_date.")
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        validated_data["client"] = request.user
        validated_data["is_immediate"] = validated_data.get("type") == "instant"
        # on ne touche pas à la tarification ici; c’est géré par /payments/initiate/
        return super().create(validated_data)


class BookingSerializer(serializers.ModelSerializer):
    client_detail = UserMiniSerializer(source="client", read_only=True)
    handyman_detail = UserMiniSerializer(source="handyman", read_only=True)
    service_detail = ServiceSerializer(source="service", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id", "client", "client_detail",
            "handyman", "handyman_detail",
            "service", "service_detail",
            "booking_date", "end_date",
            "address", "city", "postal_code",
            "description", "proposed_price", "handyman_comment",
            "response_date", "status",
            "created_at", "updated_at",
            "type", "is_immediate",
        ]
        read_only_fields = ["created_at", "updated_at"]


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
    # écriture
    handyman = serializers.PrimaryKeyRelatedField(queryset=HandymanProfile.objects.all())
    # lecture
    handyman_detail = HandymanProfileSerializer(source="handyman", read_only=True)

    class Meta:
        model = HandymanDocument
        fields = ["id", "handyman", "handyman_detail", "document_type", "file", "description", "uploaded_at"]
        read_only_fields = ["uploaded_at"]


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
    distance_m = serializers.FloatField()

    class Meta:
        model = HandymanProfile
        fields = ["id", "full_name", "rating", "completed_jobs", "distance_m"]


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

    def create(self, validated):
        """
        Crée/complète un Payment en 'pending' et retourne les infos provider.
        """
        from handy.services.gateway import OrangeMoney, MTNMoney, StripeCard

        booking = Booking.objects.select_related("service", "service__category").get(pk=validated["booking_id"])
        svc = booking.service
        category_id = validated.get("category_id") or (svc.category_id if svc else None)
        category_slug = svc.category.slug if svc and svc.category else "menage"
        minutes = validated["minutes"]

        # pricing + frais
        amount = estimate_price(category_slug, minutes)
        fee = compute_platform_fee(Decimal(amount), category_id=category_id)

        payment, _ = Payment.objects.get_or_create(
            booking=booking,
            defaults=dict(
                amount=amount, platform_fee=fee, method=validated["method"], status="pending", currency="XOF"
            ),
        )

        # Initialisation provider
        if validated["method"] == "om":
            res = OrangeMoney().create(booking, int(amount))
        elif validated["method"] == "mtn":
            res = MTNMoney().create(booking, int(amount))
        elif validated["method"] == "card":
            res = StripeCard().create(booking, int(amount))
        else:
            # cash / fallback
            res = {"provider": "cash", "provider_ref": f"CASH{booking.id}"}

        payment.transaction_id = res.get("provider_ref")
        payment.save(update_fields=["transaction_id"])
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

    def get_gradient(self, obj: HeroSlide):
        return [obj.gradient_start, obj.gradient_end]

    def get_ctaParams(self, obj: HeroSlide):
        if obj.cta_action == 'open_category' and obj.category_id:
            return {'category_id': obj.category_id}
        if obj.cta_action == 'open_url' and obj.target_url:
            return {'url': obj.target_url}
        return {}