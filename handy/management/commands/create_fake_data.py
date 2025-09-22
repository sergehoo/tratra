# handy/management/commands/create_fake_data.py
from __future__ import annotations

import math
import random
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Tuple

from django.contrib.gis.geos import Point, GEOSGeometry
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.db.models.signals import post_save
from django.utils import timezone
from django.utils.crypto import get_random_string

from faker import Faker

from handy.models import (
    AvailabilitySlot,
    Booking,
    HandymanDocument,
    HandymanProfile,
    Payment,
    Review,
    Service,
    ServiceArea,
    ServiceCategory,
    ServiceImage,
    User,
)

# Import “best-effort” du signal pour le débrancher pendant le seed
try:
    from handy.signal import on_booking_status_change
except Exception:
    on_booking_status_change = None

fake = Faker("fr_FR")

ABJ_LAT, ABJ_LNG = 5.3600, -4.0083  # centre Abidjan


def seed_all(seed: int | None):
    if seed is None:
        return
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except Exception:
        pass
    Faker.seed(seed)


def _pt(lng: float, lat: float) -> GEOSGeometry:
    """
    Construit un point GEOS **avec SRID=4326** de manière explicite.
    (Évite les surprises côté PostGIS.)
    """
    g = GEOSGeometry(f"POINT({lng} {lat})", srid=4326)
    return g


def random_point_around(lat0: float, lng0: float, max_km: float = 12.0) -> Tuple[float, float]:
    """Retourne (lat, lng) à <= max_km du centre (lat0,lng0)."""
    r_km = random.random() * max_km
    theta_deg = random.random() * 360.0
    dlat = r_km / 111.0
    dlng = r_km / (111.0 * max(0.1, abs(math.cos(math.radians(lat0)))))
    lat = lat0 + (dlat * math.sin(math.radians(theta_deg)))
    lng = lng0 + (dlng * math.cos(math.radians(theta_deg)))
    return lat, lng


class Command(BaseCommand):
    help = "Génère des données de test Handy (artisans, services, réservations) autour d’Abidjan."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=40)
        parser.add_argument("--categories", type=int, default=30)
        parser.add_argument("--services", type=int, default=120)
        parser.add_argument("--bookings", type=int, default=160)
        parser.add_argument("--seed", type=int, default=None)
        parser.add_argument("--drop", action="store_true")

    # --- util commission ---
    @staticmethod
    def _fee(amount: Decimal, rate: Decimal = Decimal("0.11")) -> Decimal:
        if amount is None:
            return Decimal("0.00")
        return (Decimal(amount) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @transaction.atomic
    def handle(self, *args, **opt):
        seed_all(opt.get("seed"))
        fake.unique.clear()

        self.stdout.write(self.style.WARNING("=== Création de FAKE DATA Handy (transactionnelle) ==="))

        # déconnecte le signal Booking -> tâche celery
        reconnected = False
        if on_booking_status_change:
            try:
                post_save.disconnect(on_booking_status_change, sender=Booking)
                reconnected = True
                self.stdout.write(self.style.WARNING("Signal on_booking_status_change déconnecté pendant le seed."))
            except Exception:
                pass

        try:
            if opt["drop"]:
                self._drop_soft()

            cats = self._create_categories(opt["categories"])
            users, handymen = self._create_users_and_handymen(opt["users"])
            services = self._create_services(opt["services"], handymen, cats)
            bookings = self._create_bookings(opt["bookings"], users, handymen, services)

            # Backfill spatial pour tout ce qui serait resté NULL
            self._ensure_spatial_fields()

            self._create_reviews(bookings)

            # Petit diagnostic final
            self._spatial_diagnostics()
        finally:
            if on_booking_status_change and reconnected:
                try:
                    post_save.connect(on_booking_status_change, sender=Booking)
                    self.stdout.write(self.style.WARNING("Signal on_booking_status_change reconnecté."))
                except Exception:
                    pass

        self.stdout.write(self.style.SUCCESS("✔ Données de test générées avec succès."))

    # ---------------- DROP (optionnel) ----------------
    def _drop_soft(self):
        self.stdout.write(self.style.WARNING("Purge des données (soft)…"))
        Review.objects.all().delete()
        Payment.objects.all().delete()
        Booking.objects.all().delete()
        ServiceImage.objects.all().delete()
        Service.objects.all().delete()
        AvailabilitySlot.objects.all().delete()
        ServiceArea.objects.all().delete()
        HandymanDocument.objects.all().delete()
        HandymanProfile.objects.all().delete()
        ServiceCategory.objects.all().delete()
        # On garde les Users

    # ---------------- CATEGORIES ----------------
    def _create_categories(self, count: int) -> List[ServiceCategory]:
        self.stdout.write(f"• Création de {count} catégories…")

        base = [
            ("Plomberie", "plomberie", "Réparations et installations plomberie", "fa-solid fa-faucet"),
            ("Électricité", "electricite", "Interventions et dépannages électriques", "fa-solid fa-bolt"),
            ("Peinture", "peinture", "Peinture intérieure et extérieure", "fa-solid fa-paint-roller"),
            ("Menuiserie", "menuiserie", "Fabrication et réparation de boiseries", "fa-solid fa-hammer"),
            ("Nettoyage", "nettoyage", "Ménage et entretien", "fa-solid fa-broom"),
            ("Déménagement", "demenagement", "Transport et manutention", "fa-solid fa-truck"),
            ("Jardinage", "jardinage", "Entretien des espaces verts", "fa-solid fa-tree"),
            ("Bricolage", "bricolage", "Petits travaux", "fa-solid fa-screwdriver-wrench"),
        ]

        cats: List[ServiceCategory] = []
        for name, slug, desc, icon in base[: min(len(base), max(0, count))]:
            c, _ = ServiceCategory.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "description": desc, "icon": icon, "is_active": True, "parent": None},
            )
            cats.append(c)

        icons = [
            "fas fa-road", "fas fa-music", "fas fa-laptop-code", "fas fa-tools", "fas fa-border-style",
            "fas fa-house", "fas fa-bolt", "fas fa-brush", "fas fa-screwdriver-wrench", "fas fa-tree"
        ]
        while len(cats) < count:
            name = fake.unique.bs().capitalize()
            slug = fake.unique.slug()
            icon = random.choice(icons)
            c = ServiceCategory.objects.create(
                name=name,
                slug=slug,
                description=fake.sentence(),
                icon=icon,
                is_active=True,
                parent=None
            )
            cats.append(c)

        return cats

    # ---------------- USERS ----------------
    @staticmethod
    def _unique_username_from_email(email: str) -> str:
        base = (email.split("@")[0] if email else f"user_{get_random_string(6)}").lower()[:30]
        candidate = base
        i = 1
        while User.objects.filter(username=candidate).exists():
            candidate = f"{base}{i}"
            i += 1
        return candidate

    def _get_or_create_user(self, email: str, **defaults) -> User:
        defaults.setdefault("username", self._unique_username_from_email(email))
        user, created = User.objects.get_or_create(email=email, defaults=defaults)
        if created or not user.has_usable_password():
            user.set_password(defaults.get("password", "password123"))
            user.save(update_fields=["password"])
        dirty = False
        for f, v in defaults.items():
            if f == "password":
                continue
            if getattr(user, f, None) != v:
                setattr(user, f, v)
                dirty = True
        if dirty:
            user.save()
        return user

    def _get_or_create_handyman_profile(self, user: User) -> HandymanProfile:
        existing = HandymanProfile.objects.filter(user=user).first()
        if existing:
            # Backfill location si manquante
            if not existing.location:
                lat = 5.3600 + fake.pyfloat(min_value=-0.1, max_value=0.1)
                lng = -4.0083 + fake.pyfloat(min_value=-0.1, max_value=0.1)
                existing.location = _pt(lng, lat)
                existing.save(update_fields=["location"])
            return existing

        lat = 5.3600 + fake.pyfloat(min_value=-0.1, max_value=0.1)
        lng = -4.0083 + fake.pyfloat(min_value=-0.1, max_value=0.1)

        try:
            profile, _ = HandymanProfile.objects.get_or_create(
                user=user,
                defaults={
                    "bio": fake.text(max_nb_chars=200),
                    "commune": fake.random_element(
                        elements=["Cocody", "Abobo", "Adjamé", "Plateau", "Yopougon", "Treichville"]),
                    "quartier": fake.word(),
                    "location": _pt(lng, lat),
                    "rating": round(fake.pyfloat(min_value=3.0, max_value=5.0), 1),
                    "completed_jobs": fake.random_int(min=0, max=100),
                    "is_approved": fake.pybool(truth_probability=80),
                    "online": fake.pybool(truth_probability=50),
                    "hourly_rate": fake.random_int(min=2000, max=10000),
                },
            )
        except IntegrityError:
            profile = HandymanProfile.objects.get(user=user)
            if not profile.location:
                profile.location = _pt(lng, lat)
                profile.save(update_fields=["location"])

        # Zone de service
        ServiceArea.objects.get_or_create(
            handyman=profile,
            defaults={"center": profile.location or _pt(lng, lat), "radius_km": fake.random_int(min=5, max=20)},
        )

        # Créneaux (une seule fois)
        if not AvailabilitySlot.objects.filter(handyman=profile).exists():
            for day in range(7):
                if fake.pybool(truth_probability=70):
                    AvailabilitySlot.objects.create(
                        handyman=profile,
                        weekday=day,
                        start_time=fake.time(pattern="%H:%M:%S"),
                        end_time=fake.time(pattern="%H:%M:%S"),
                    )

        return profile

    def _create_users_and_handymen(self, count: int):
        self.stdout.write(f"• Création de {count} utilisateurs (≈40% artisans)…")

        users: List[User] = []
        handymen_profiles: List[HandymanProfile] = []

        admin = self._get_or_create_user(
            "admin@handy.com",
            first_name="Admin",
            last_name="Handy",
            user_type="admin",
            is_staff=True,
            is_superuser=True,
            is_verified=True,
            password="password123",
        )
        users.append(admin)

        demo_client = self._get_or_create_user(
            "demo.client@handy.com",
            first_name="Demo",
            last_name="Client",
            user_type="client",
            is_verified=True,
            password="password123",
        )
        users.append(demo_client)

        for _ in range(count):
            is_handyman = random.random() > 0.6
            email = fake.unique.email()

            user = self._get_or_create_user(
                email,
                first_name=fake.first_name(),
                last_name=fake.last_name(),
                user_type="handyman" if is_handyman else "client",
                is_verified=fake.pybool(truth_probability=80),
                password="password123",
            )
            users.append(user)

            # Backfill aussi les coordonnées côté User (utile pour suggestions “près de moi”)
            if not getattr(user, "last_location", None):
                lat = 5.3600 + fake.pyfloat(min_value=-0.1, max_value=0.1)
                lng = -4.0083 + fake.pyfloat(min_value=-0.1, max_value=0.1)
                user.last_location = _pt(lng, lat)
                user.last_location_ts = timezone.now()
                user.save(update_fields=["last_location", "last_location_ts"])

            if is_handyman:
                profile = self._get_or_create_handyman_profile(user)
                handymen_profiles.append(profile)

        return users, handymen_profiles

    # ---------------- SERVICES ----------------
    def _create_services(self, count: int, handymen: List[HandymanProfile], categories: List[ServiceCategory]) -> List[Service]:
        self.stdout.write(f"• Création de {count} services…")
        if not handymen or not categories:
            return []

        services: List[Service] = []
        price_types = ["hourly", "fixed", "quote"]

        for _ in range(count):
            hm = random.choice(handymen)
            cat = random.choice(categories)
            price_type = random.choice(price_types)

            if price_type == "hourly":
                price = Decimal(random.randrange(2000, 15000, 500))
                duration = random.choice([30, 60, 90, 120, 180, 240])
            elif price_type == "fixed":
                price = Decimal(random.randrange(5000, 120000, 1000))
                duration = None
            else:
                price = None
                duration = None

            svc = Service.objects.create(
                handyman=hm.user,
                category=cat,
                title=fake.catch_phrase(),
                description=fake.text(max_nb_chars=400),
                price_type=price_type,
                price=price,
                duration=duration,
                is_active=random.random() > 0.08,
            )
            services.append(svc)

        return services

    # ---------------- BOOKINGS ----------------
    def _create_bookings(self, count: int, users: List[User], handymen: List[HandymanProfile], services: List[Service]) -> List[Booking]:
        self.stdout.write(f"• Création de {count} réservations…")
        if not services or not handymen:
            return []

        bookings: List[Booking] = []
        statuses = ["pending", "confirmed", "in_progress", "completed", "cancelled"]

        clients = [u for u in users if getattr(u, "user_type", "client") == "client"] or [users[0]]
        now = timezone.now()

        for _ in range(count):
            client = random.choice(clients)
            hm = random.choice(handymen)
            service = random.choice(services)

            status = random.choice(statuses)
            lat, lng = random_point_around(ABJ_LAT, ABJ_LNG, max_km=16)

            if status == "pending":
                booking_date = now + timezone.timedelta(days=random.randint(1, 30))
            elif status in ["confirmed", "in_progress"]:
                booking_date = now - timezone.timedelta(days=random.randint(0, 5))
            else:
                booking_date = now - timezone.timedelta(days=random.randint(5, 40))

            bk = Booking.objects.create(
                client=client,
                handyman=hm.user,
                service=service,
                status=status,
                booking_date=booking_date,
                address=fake.street_address(),
                city="Abidjan",
                postal_code=fake.postcode(),
                job_location=_pt(lng, lat),
                description=fake.text(max_nb_chars=220),
            )

            # Paiement lié (avec platform_fee obligatoire)
            amount = service.price if service.price is not None else Decimal(random.randrange(10000, 120000, 500))
            if status in ["confirmed", "in_progress", "completed"]:
                Payment.objects.create(
                    booking=bk,
                    amount=amount,
                    platform_fee=self._fee(amount),   # <<< OBLIGATOIRE
                    method=random.choice(["cash", "om", "mtn", "card"]),
                    status=random.choice(["pending", "completed", "failed"]),
                    transaction_id=fake.uuid4()[:20],
                    currency="XOF",
                )

            bookings.append(bk)

        return bookings

    # ---------------- REVIEWS ----------------
    def _create_reviews(self, bookings: List[Booking]):
        self.stdout.write("• Création des avis…")
        for b in bookings:
            if b.status == "completed" and random.random() > 0.35:
                Review.objects.create(
                    booking=b,
                    rating=random.randint(3, 5),
                    comment=fake.text(max_nb_chars=180),
                )

    # ---------------- BACKFILL SPATIAL ----------------
    def _ensure_spatial_fields(self):
        """
        Après seed, forcer des coordonnées si certaines sont restées NULL
        (cas d’objets préexistants récupérés par get_or_create).
        """
        # HandymanProfile.location
        for hp in HandymanProfile.objects.filter(location__isnull=True):
            lat = 5.3600 + fake.pyfloat(min_value=-0.1, max_value=0.1)
            lng = -4.0083 + fake.pyfloat(min_value=-0.1, max_value=0.1)
            hp.location = _pt(lng, lat)
            hp.save(update_fields=["location"])

        # ServiceArea.center
        for sa in ServiceArea.objects.filter(center__isnull=True).select_related("handyman"):
            base = sa.handyman.location
            if base is None:
                lat = 5.3600 + fake.pyfloat(min_value=-0.1, max_value=0.1)
                lng = -4.0083 + fake.pyfloat(min_value=-0.1, max_value=0.1)
                base = _pt(lng, lat)
            sa.center = base
            sa.save(update_fields=["center"])

        # Booking.job_location
        for bk in Booking.objects.filter(job_location__isnull=True):
            lat, lng = random_point_around(ABJ_LAT, ABJ_LNG, max_km=16)
            bk.job_location = _pt(lng, lat)
            bk.save(update_fields=["job_location"])

        # User.last_location
        for u in User.objects.filter(last_location__isnull=True):
            lat = 5.3600 + fake.pyfloat(min_value=-0.1, max_value=0.1)
            lng = -4.0083 + fake.pyfloat(min_value=-0.1, max_value=0.1)
            u.last_location = _pt(lng, lat)
            u.last_location_ts = timezone.now()
            u.save(update_fields=["last_location", "last_location_ts"])

    # ---------------- DIAGNOSTIC ----------------
    def _spatial_diagnostics(self):
        hp_null = HandymanProfile.objects.filter(location__isnull=True).count()
        sa_null = ServiceArea.objects.filter(center__isnull=True).count()
        bk_null = Booking.objects.filter(job_location__isnull=True).count()
        u_null  = User.objects.filter(last_location__isnull=True).count()

        if hp_null or sa_null or bk_null or u_null:
            self.stdout.write(self.style.WARNING(
                f"Diagnostics: HandymanProfile.location NULL={hp_null} | "
                f"ServiceArea.center NULL={sa_null} | Booking.job_location NULL={bk_null} | "
                f"User.last_location NULL={u_null}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("Diagnostics: toutes les positions GPS sont renseignées."))
# # handy/management/commands/create_fake_data.py
# from __future__ import annotations
#
# import math
# import random
# from decimal import Decimal, ROUND_HALF_UP
# from typing import List, Tuple
#
# from django.contrib.gis.geos import Point
# from django.core.management.base import BaseCommand
# from django.db import IntegrityError, transaction
# from django.db.models.signals import post_save
# from django.utils import timezone
# from django.utils.crypto import get_random_string
#
# from faker import Faker
#
# from handy.models import (
#     AvailabilitySlot,
#     Booking,
#     HandymanDocument,
#     HandymanProfile,
#     Payment,
#     Review,
#     Service,
#     ServiceArea,
#     ServiceCategory,
#     ServiceImage,
#     User,
# )
#
# # Import “best-effort” du signal pour le débrancher pendant le seed
# try:
#     from handy.signal import on_booking_status_change
# except Exception:
#     on_booking_status_change = None
#
# fake = Faker("fr_FR")
#
# ABJ_LAT, ABJ_LNG = 5.3600, -4.0083  # centre Abidjan
#
#
# def seed_all(seed: int | None):
#     if seed is None:
#         return
#     random.seed(seed)
#     try:
#         import numpy as np
#         np.random.seed(seed)
#     except Exception:
#         pass
#     Faker.seed(seed)
#
#
# def random_point_around(lat0: float, lng0: float, max_km: float = 12.0) -> Tuple[float, float]:
#     """Retourne (lat, lng) à <= max_km du centre (lat0,lng0)."""
#     r_km = random.random() * max_km
#     theta_deg = random.random() * 360.0
#     dlat = r_km / 111.0
#     dlng = r_km / (111.0 * max(0.1, abs(math.cos(math.radians(lat0)))))
#     lat = lat0 + (dlat * math.sin(math.radians(theta_deg)))
#     lng = lng0 + (dlng * math.cos(math.radians(theta_deg)))
#     return lat, lng
#
#
# class Command(BaseCommand):
#     help = "Génère des données de test Handy (artisans, services, réservations) autour d’Abidjan."
#
#     def add_arguments(self, parser):
#         parser.add_argument("--users", type=int, default=40)
#         parser.add_argument("--categories", type=int, default=30)
#         parser.add_argument("--services", type=int, default=120)
#         parser.add_argument("--bookings", type=int, default=160)
#         parser.add_argument("--seed", type=int, default=None)
#         parser.add_argument("--drop", action="store_true")
#
#     # --- util commission ---
#     @staticmethod
#     def _fee(amount: Decimal, rate: Decimal = Decimal("0.11")) -> Decimal:
#         if amount is None:
#             return Decimal("0.00")
#         return (Decimal(amount) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
#
#     @transaction.atomic
#     def handle(self, *args, **opt):
#         seed_all(opt.get("seed"))
#         fake.unique.clear()
#
#         self.stdout.write(self.style.WARNING("=== Création de FAKE DATA Handy (transactionnelle) ==="))
#
#         # déconnecte le signal Booking -> tâche celery
#         reconnected = False
#         if on_booking_status_change:
#             try:
#                 post_save.disconnect(on_booking_status_change, sender=Booking)
#                 reconnected = True
#                 self.stdout.write(self.style.WARNING("Signal on_booking_status_change déconnecté pendant le seed."))
#             except Exception:
#                 pass
#
#         try:
#             if opt["drop"]:
#                 self._drop_soft()
#
#             cats = self._create_categories(opt["categories"])
#             users, handymen = self._create_users_and_handymen(opt["users"])
#             services = self._create_services(opt["services"], handymen, cats)
#             bookings = self._create_bookings(opt["bookings"], users, handymen, services)
#             self._create_reviews(bookings)
#         finally:
#             if on_booking_status_change and reconnected:
#                 try:
#                     post_save.connect(on_booking_status_change, sender=Booking)
#                     self.stdout.write(self.style.WARNING("Signal on_booking_status_change reconnecté."))
#                 except Exception:
#                     pass
#
#         self.stdout.write(self.style.SUCCESS("✔ Données de test générées avec succès."))
#
#     # ---------------- DROP (optionnel) ----------------
#     def _drop_soft(self):
#         self.stdout.write(self.style.WARNING("Purge des données (soft)…"))
#         Review.objects.all().delete()
#         Payment.objects.all().delete()
#         Booking.objects.all().delete()
#         ServiceImage.objects.all().delete()
#         Service.objects.all().delete()
#         AvailabilitySlot.objects.all().delete()
#         ServiceArea.objects.all().delete()
#         HandymanDocument.objects.all().delete()
#         HandymanProfile.objects.all().delete()
#         ServiceCategory.objects.all().delete()
#         # On garde les Users
#
#     # ---------------- CATEGORIES ----------------
#     def _create_categories(self, count: int) -> List[ServiceCategory]:
#         self.stdout.write(f"• Création de {count} catégories…")
#
#         base = [
#             ("Plomberie", "plomberie", "Réparations et installations plomberie", "fa-solid fa-faucet"),
#             ("Électricité", "electricite", "Interventions et dépannages électriques", "fa-solid fa-bolt"),
#             ("Peinture", "peinture", "Peinture intérieure et extérieure", "fa-solid fa-paint-roller"),
#             ("Menuiserie", "menuiserie", "Fabrication et réparation de boiseries", "fa-solid fa-hammer"),
#             ("Nettoyage", "nettoyage", "Ménage et entretien", "fa-solid fa-broom"),
#             ("Déménagement", "demenagement", "Transport et manutention", "fa-solid fa-truck"),
#             ("Jardinage", "jardinage", "Entretien des espaces verts", "fa-solid fa-tree"),
#             ("Bricolage", "bricolage", "Petits travaux", "fa-solid fa-screwdriver-wrench"),
#         ]
#
#         cats: List[ServiceCategory] = []
#         for name, slug, desc, icon in base[: min(len(base), max(0, count))]:
#             c, _ = ServiceCategory.objects.get_or_create(
#                 slug=slug,
#                 defaults={"name": name, "description": desc, "icon": icon, "is_active": True, "parent": None},
#             )
#             cats.append(c)
#
#         icons = [
#             "fas fa-road", "fas fa-music", "fas fa-laptop-code", "fas fa-tools", "fas fa-border-style",
#             "fas fa-house", "fas fa-bolt", "fas fa-brush", "fas fa-screwdriver-wrench", "fas fa-tree"
#         ]
#         while len(cats) < count:
#             name = fake.unique.bs().capitalize()
#             slug = fake.unique.slug()
#             icon = random.choice(icons)
#             c = ServiceCategory.objects.create(
#                 name=name,
#                 slug=slug,
#                 description=fake.sentence(),
#                 icon=icon,
#                 is_active=True,
#                 parent=None
#             )
#             cats.append(c)
#
#         return cats
#
#     # ---------------- USERS ----------------
#     @staticmethod
#     def _unique_username_from_email(email: str) -> str:
#         base = (email.split("@")[0] if email else f"user_{get_random_string(6)}").lower()[:30]
#         candidate = base
#         i = 1
#         while User.objects.filter(username=candidate).exists():
#             candidate = f"{base}{i}"
#             i += 1
#         return candidate
#
#     def _get_or_create_user(self, email: str, **defaults) -> User:
#         defaults.setdefault("username", self._unique_username_from_email(email))
#         user, created = User.objects.get_or_create(email=email, defaults=defaults)
#         if created or not user.has_usable_password():
#             user.set_password(defaults.get("password", "password123"))
#             user.save(update_fields=["password"])
#         dirty = False
#         for f, v in defaults.items():
#             if f == "password":
#                 continue
#             if getattr(user, f, None) != v:
#                 setattr(user, f, v)
#                 dirty = True
#         if dirty:
#             user.save()
#         return user
#
#     def _get_or_create_handyman_profile(self, user: User) -> HandymanProfile:
#         existing = HandymanProfile.objects.filter(user=user).first()
#         if existing:
#             return existing
#
#         lat = 5.3600 + fake.pyfloat(min_value=-0.1, max_value=0.1)
#         lng = -4.0083 + fake.pyfloat(min_value=-0.1, max_value=0.1)
#
#         try:
#             profile, _ = HandymanProfile.objects.get_or_create(
#                 user=user,
#                 defaults={
#                     "bio": fake.text(max_nb_chars=200),
#                     "commune": fake.random_element(
#                         elements=["Cocody", "Abobo", "Adjamé", "Plateau", "Yopougon", "Treichville"]),
#                     "quartier": fake.word(),
#                     "location": Point(lng, lat, srid=4326),
#                     "rating": round(fake.pyfloat(min_value=3.0, max_value=5.0), 1),
#                     "completed_jobs": fake.random_int(min=0, max=100),
#                     "is_approved": fake.pybool(truth_probability=80),
#                     "online": fake.pybool(truth_probability=50),
#                     "hourly_rate": fake.random_int(min=2000, max=10000),
#                 },
#             )
#         except IntegrityError:
#             profile = HandymanProfile.objects.get(user=user)
#
#         ServiceArea.objects.get_or_create(
#             handyman=profile,
#             defaults={"center": profile.location, "radius_km": fake.random_int(min=5, max=20)},
#         )
#
#         if not AvailabilitySlot.objects.filter(handyman=profile).exists():
#             for day in range(7):
#                 if fake.pybool(truth_probability=70):
#                     AvailabilitySlot.objects.create(
#                         handyman=profile,
#                         weekday=day,
#                         start_time=fake.time(pattern="%H:%M:%S"),
#                         end_time=fake.time(pattern="%H:%M:%S"),
#                     )
#
#         return profile
#
#     def _create_users_and_handymen(self, count: int):
#         self.stdout.write(f"• Création de {count} utilisateurs (≈40% artisans)…")
#
#         users: List[User] = []
#         handymen_profiles: List[HandymanProfile] = []
#
#         admin = self._get_or_create_user(
#             "admin@handy.com",
#             first_name="Admin",
#             last_name="Handy",
#             user_type="admin",
#             is_staff=True,
#             is_superuser=True,
#             is_verified=True,
#             password="password123",
#         )
#         users.append(admin)
#
#         demo_client = self._get_or_create_user(
#             "demo.client@handy.com",
#             first_name="Demo",
#             last_name="Client",
#             user_type="client",
#             is_verified=True,
#             password="password123",
#         )
#         users.append(demo_client)
#
#         for _ in range(count):
#             is_handyman = random.random() > 0.6
#             email = fake.unique.email()
#
#             user = self._get_or_create_user(
#                 email,
#                 first_name=fake.first_name(),
#                 last_name=fake.last_name(),
#                 user_type="handyman" if is_handyman else "client",
#                 is_verified=fake.pybool(truth_probability=80),
#                 password="password123",
#             )
#             users.append(user)
#
#             if is_handyman:
#                 profile = self._get_or_create_handyman_profile(user)
#                 handymen_profiles.append(profile)
#
#         return users, handymen_profiles
#
#     # ---------------- SERVICES ----------------
#     def _create_services(self, count: int, handymen: List[HandymanProfile], categories: List[ServiceCategory]) -> List[Service]:
#         self.stdout.write(f"• Création de {count} services…")
#         if not handymen or not categories:
#             return []
#
#         services: List[Service] = []
#         price_types = ["hourly", "fixed", "quote"]
#
#         for _ in range(count):
#             hm = random.choice(handymen)
#             cat = random.choice(categories)
#             price_type = random.choice(price_types)
#
#             if price_type == "hourly":
#                 price = Decimal(random.randrange(2000, 15000, 500))
#                 duration = random.choice([30, 60, 90, 120, 180, 240])
#             elif price_type == "fixed":
#                 price = Decimal(random.randrange(5000, 120000, 1000))
#                 duration = None
#             else:
#                 price = None
#                 duration = None
#
#             svc = Service.objects.create(
#                 handyman=hm.user,
#                 category=cat,
#                 title=fake.catch_phrase(),
#                 description=fake.text(max_nb_chars=400),
#                 price_type=price_type,
#                 price=price,
#                 duration=duration,
#                 is_active=random.random() > 0.08,
#             )
#             services.append(svc)
#
#         return services
#
#     # ---------------- BOOKINGS ----------------
#     def _create_bookings(self, count: int, users: List[User], handymen: List[HandymanProfile], services: List[Service]) -> List[Booking]:
#         self.stdout.write(f"• Création de {count} réservations…")
#         if not services or not handymen:
#             return []
#
#         bookings: List[Booking] = []
#         statuses = ["pending", "confirmed", "in_progress", "completed", "cancelled"]
#
#         clients = [u for u in users if getattr(u, "user_type", "client") == "client"] or [users[0]]
#         now = timezone.now()
#
#         for _ in range(count):
#             client = random.choice(clients)
#             hm = random.choice(handymen)
#             service = random.choice(services)
#
#             status = random.choice(statuses)
#             lat, lng = random_point_around(ABJ_LAT, ABJ_LNG, max_km=16)
#
#             if status == "pending":
#                 booking_date = now + timezone.timedelta(days=random.randint(1, 30))
#             elif status in ["confirmed", "in_progress"]:
#                 booking_date = now - timezone.timedelta(days=random.randint(0, 5))
#             else:
#                 booking_date = now - timezone.timedelta(days=random.randint(5, 40))
#
#             bk = Booking.objects.create(
#                 client=client,
#                 handyman=hm.user,
#                 service=service,
#                 status=status,
#                 booking_date=booking_date,
#                 address=fake.street_address(),
#                 city="Abidjan",
#                 postal_code=fake.postcode(),
#                 job_location=Point(lng, lat, srid=4326),
#                 description=fake.text(max_nb_chars=220),
#             )
#
#             # Paiement lié (avec platform_fee obligatoire)
#             amount = service.price if service.price is not None else Decimal(random.randrange(10000, 120000, 500))
#             if status in ["confirmed", "in_progress", "completed"]:
#                 Payment.objects.create(
#                     booking=bk,
#                     amount=amount,
#                     platform_fee=self._fee(amount),   # <<< OBLIGATOIRE
#                     method=random.choice(["cash", "om", "mtn", "card"]),
#                     status=random.choice(["pending", "completed", "failed"]),
#                     transaction_id=fake.uuid4()[:20],
#                     currency="XOF",  # explicite si ton modèle n'a pas de default
#                 )
#
#             bookings.append(bk)
#
#         return bookings
#
#     # ---------------- REVIEWS ----------------
#     def _create_reviews(self, bookings: List[Booking]):
#         self.stdout.write("• Création des avis…")
#         for b in bookings:
#             if b.status == "completed" and random.random() > 0.35:
#                 Review.objects.create(
#                     booking=b,
#                     rating=random.randint(3, 5),
#                     comment=fake.text(max_nb_chars=180),
#                     # is_approved=random.random() > 0.2,
#                 )
#