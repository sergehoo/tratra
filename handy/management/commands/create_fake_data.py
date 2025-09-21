# handy/management/commands/create_fake_data.py
from __future__ import annotations

import math
import random
from decimal import Decimal
from typing import List, Tuple

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
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

fake = Faker("fr_FR")

# Centre approximatif d'Abidjan
ABJ_LAT, ABJ_LNG = 5.3600, -4.0083


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


def random_point_around(lat0: float, lng0: float, max_km: float = 12.0) -> Tuple[float, float]:
    """
    Retourne (lat, lng) à <= max_km du centre (lat0,lng0).
    Approx simple: 1° lat ~ 111km ; 1° lon ~ 111km * cos(lat).
    """
    r_km = random.random() * max_km
    theta_deg = random.random() * 360.0
    dlat = r_km / 111.0
    dlng = r_km / (111.0 * max(0.1, abs(math.cos(math.radians(lat0)))))  # évite /0
    lat = lat0 + (dlat * math.sin(math.radians(theta_deg)))
    lng = lng0 + (dlng * math.cos(math.radians(theta_deg)))
    return lat, lng


class Command(BaseCommand):
    help = "Génère des données de test Handy (artisans, services, réservations) avec coordonnées GPS (Abidjan)."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=40,
                            help="Nombre total d'utilisateurs à créer (≈40% artisans). Default 40")
        parser.add_argument("--categories", type=int, default=30,
                            help="Nombre de catégories à créer. Default 30")
        parser.add_argument("--services", type=int, default=120,
                            help="Nombre de services à créer. Default 120")
        parser.add_argument("--bookings", type=int, default=160,
                            help="Nombre de réservations à créer. Default 160")
        parser.add_argument("--seed", type=int, default=None,
                            help="Graine aléatoire (reproductible). Ex: --seed 42")
        parser.add_argument("--drop", action="store_true",
                            help="Supprime (hard delete) les données existantes non critiques avant insertion")

    @transaction.atomic
    def handle(self, *args, **opt):
        seed_all(opt.get("seed"))
        fake.unique.clear()

        self.stdout.write(self.style.WARNING("=== Création de FAKE DATA Handy (transactionnelle) ==="))

        if opt["drop"]:
            self._drop_soft()

        cats = self._create_categories(opt["categories"])
        users, handymen = self._create_users_and_handymen(opt["users"])
        services = self._create_services(opt["services"], handymen, cats)
        bookings = self._create_bookings(opt["bookings"], users, handymen, services)
        self._create_reviews(bookings)

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
        # NB: on ne supprime pas les Users pour garder les comptes tests

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
        # Met à jour des champs si absents (idempotent mais rafraîchissant)
        dirty = False
        for f, v in defaults.items():
            if getattr(user, f, None) != v and f not in {"password"}:
                setattr(user, f, v)
                dirty = True
        if dirty:
            user.save()
        return user

    def _get_or_create_handyman_profile(self, user: User) -> HandymanProfile:
        """
        Idempotent + résilient aux courses : évite IntegrityError OneToOne.
        """
        existing = HandymanProfile.objects.filter(user=user).first()
        if existing:
            return existing

        # Pos autour d’Abidjan
        lat = 5.3600 + fake.pyfloat(min_value=-0.1, max_value=0.1)
        lng = -4.0083 + fake.pyfloat(min_value=-0.1, max_value=0.1)

        try:
            profile, created = HandymanProfile.objects.get_or_create(
                user=user,
                defaults={
                    "bio": fake.text(max_nb_chars=200),
                    "commune": fake.random_element(
                        elements=["Cocody", "Abobo", "Adjamé", "Plateau", "Yopougon", "Treichville"]),
                    "quartier": fake.word(),
                    "location": Point(lng, lat, srid=4326),
                    "rating": round(fake.pyfloat(min_value=3.0, max_value=5.0), 1),
                    "completed_jobs": fake.random_int(min=0, max=100),
                    "is_approved": fake.pybool(truth_probability=80),
                    "online": fake.pybool(truth_probability=50),
                    "hourly_rate": fake.random_int(min=2000, max=10000),
                },
            )
        except IntegrityError:
            # OneToOne déjà pris (course ou rerun) -> on récupère proprement
            profile = HandymanProfile.objects.get(user=user)
            created = False

        # Zone de service (idempotent)
        ServiceArea.objects.get_or_create(
            handyman=profile,
            defaults={
                "center": profile.location,
                "radius_km": fake.random_int(min=5, max=20),
            },
        )

        # Créneaux : uniquement lors de la première création évaluée “réelle”
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

        # Admin (idempotent)
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

        # Client démo (idempotent)
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
            is_handyman = random.random() > 0.6  # ~40% artisans
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
            else:  # quote
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

            # (Option) Ajouter des images si ton modèle accepte un upload simplifié
            # Laisse vide par défaut pour éviter la gestion de fichiers.

            services.append(svc)

        return services

    # ---------------- BOOKINGS ----------------
    def _create_bookings(self, count: int, users: List[User], handymen: List[HandymanProfile], services: List[Service]) -> List[Booking]:
        self.stdout.write(f"• Création de {count} réservations…")
        if not services or not handymen:
            return []

        bookings: List[Booking] = []
        statuses = ["pending", "confirmed", "in_progress", "completed", "cancelled"]

        clients = [u for u in users if getattr(u, "user_type", "client") == "client"]
        if not clients:
            clients = [users[0]]

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

            total_price = service.price if service.price is not None else Decimal(random.randrange(10000, 120000, 500))

            bk = Booking.objects.create(
                client=client,
                handyman=hm.user,
                service=service,
                status=status,
                booking_date=booking_date,
                address=fake.street_address(),
                city="Abidjan",
                postal_code=fake.postcode(),
                job_location=Point(lng, lat, srid=4326),
                description=fake.text(max_nb_chars=220),
                total_price=total_price,
            )
            amount = service.price if service.price is not None else Decimal(random.randrange(10000, 120000, 500))

            if status in ["confirmed", "in_progress", "completed"]:
                method = random.choice(["cash", "om", "mtn", "card"])
                p_status = random.choice(["pending", "completed", "failed"])
                Payment.objects.create(
                    booking=bk,
                    amount=amount,
                    platform_fee=self._fee(amount),  # <<< OBLIGATOIRE
                    method=random.choice(["cash", "om", "mtn", "card"]),
                    status=random.choice(["pending", "completed", "failed"]),
                    transaction_id=fake.uuid4()[:20],
                    currency="XOF",  # explicite si ton modèle n'a pas de default
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
                    is_approved=random.random() > 0.2,
                )