"""Comptes et données de recette de bout en bout (DÉVELOPPEMENT LOCAL UNIQUEMENT).

    python manage.py seed_e2e            # crée / met à jour les comptes e2e_*
    python manage.py seed_e2e --purge    # supprime TOUS les comptes et données e2e_*

Les comptes e2e_* partagent le mot de passe de test ci-dessous (valeur sans aucun usage hors poste de développement).
Aucune vérification de téléphone n'est simulée : `is_verified` reste faux, l'OTP n'est jamais contourné ni modifié.
La commande refuse de s'exécuter hors DEBUG."""
import io
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw

E2E_PASSWORD = "E2e-Tratra-Local-1!"   # mot de passe de test des comptes e2e_* (local uniquement)
PREFIX = "e2e_"

ACCOUNTS = {
    # username: (prénom, nom, téléphone, profil artisan ?)
    "e2e_client": ("Awa", "Client", "+2250700099901", False),
    "e2e_artisan": ("Moussa", "Artisan", "+2250700099902", True),
    "e2e_veteran": ("Karim", "Expert", "+2250700099903", True),
    "e2e_new": ("Nina", "Nouvelle", "+2250700099904", True),
    "e2e_boss_a": ("Alice", "Directrice A", "+2250700099905", False),
    "e2e_boss_b": ("Bruno", "Directeur B", "+2250700099906", False),
}


def _portrait(color):
    img = Image.new("RGB", (320, 320), color)
    d = ImageDraw.Draw(img)
    d.ellipse((110, 60, 210, 160), fill=(245, 245, 245))
    d.ellipse((60, 170, 260, 380), fill=(245, 245, 245))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return ContentFile(buf.getvalue())


class Command(BaseCommand):
    help = "Comptes de recette e2e_* (dev local uniquement) ; --purge pour tout supprimer."

    def add_arguments(self, parser):
        parser.add_argument("--purge", action="store_true")

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("seed_e2e est réservé au développement local (DEBUG=True).")
        if opts["purge"]:
            return self.purge()
        self.seed()

    # ------------------------------------------------------------------ création
    @transaction.atomic
    def seed(self):
        from handy.models import Booking, BookingTimeline, HandymanDocument, Review, Service, ServiceCategory, User
        from handy.testing import make_eligible

        cat, _ = ServiceCategory.objects.get_or_create(slug="plomberie", defaults={"name": "Plomberie"})
        users = {}
        for username, (first, last, phone, artisan) in ACCOUNTS.items():
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "phone": phone, "email": f"{username}@e2e.test",
                          "user_type": "handyman" if artisan else "client"})
            user.set_password(E2E_PASSWORD)
            user.is_active = True
            user.save()
            users[username] = user

        # Artisan vérifié « frais » : VERIFIE seulement (aucun historique), prêt à recevoir une réservation.
        for name, color in (("e2e_artisan", (46, 139, 87)), ("e2e_veteran", (31, 106, 65))):
            profile = users[name].handyman_profile
            profile.bio = "Plombier-chauffagiste, interventions à domicile et en entreprise."
            profile.experience_years = 8
            profile.commune = "Cocody"
            profile.quartier = "Riviera"
            profile.hourly_rate = 7500
            if not profile.photo:
                profile.photo.save(f"{name}.jpg", _portrait(color), save=False)
            profile.save()
            make_eligible(profile, category=cat)
            profile.skills.add(cat)
            Service.objects.get_or_create(handyman=users[name], title="Dépannage plomberie",
                                          defaults={"category": cat, "description": "Fuite, robinetterie, chauffe-eau.",
                                                    "price_type": "fixed", "price": 15000, "is_active": True})
        # Artisan NON vérifié : profil créé, KYC absent → badge NOUVEAU.
        new = users["e2e_new"].handyman_profile
        new.bio = ""
        new.save()

        # Artisan chevronné : justificatif approuvé + 16 missions réelles terminées, à l'heure, avec 5+ avis → VERIFIE + EXPERT + SUR.
        vet = users["e2e_veteran"]
        if not Booking.objects.filter(handyman=vet).exists():
            now = timezone.now()
            HandymanDocument.objects.get_or_create(
                handyman=vet.handyman_profile, document_type="certification",
                defaults={"file": "kyc/e2e_cert.pdf", "status": "approved", "title": "CAP Plomberie", "category": cat,
                          "issuer": "Ministère de l'Enseignement technique", "issued_on": now.date() - timedelta(days=900),
                          "reviewed_at": now})
            svc = Service.objects.filter(handyman=vet).first()
            for i in range(16):
                cli, _ = User.objects.get_or_create(
                    username=f"e2e_hist_{i:02d}", defaults={"first_name": "Client", "last_name": f"H{i:02d}", "user_type": "client"})
                planned = now - timedelta(days=3 + i * 5)
                b = Booking.objects.create(client=cli, handyman=vet, service=svc, status="completed", address="Rue des Jardins",
                                           city="Abidjan", booking_date=planned, proposed_price=15000)
                Booking.objects.filter(pk=b.pk).update(created_at=planned - timedelta(hours=3))
                confirmed = BookingTimeline.objects.create(booking=b, status="confirmed")
                BookingTimeline.objects.filter(pk=confirmed.pk).update(at=planned - timedelta(hours=3) + timedelta(minutes=12))
                started = BookingTimeline.objects.create(booking=b, status="in_progress")
                BookingTimeline.objects.filter(pk=started.pk).update(at=planned + timedelta(minutes=6))
                if i < 8:
                    Review.objects.create(booking=b, rating=5 if i % 4 else 4, quality=5, punctuality=5, professionalism=5,
                                          comment="Intervention soignée et ponctuelle." if i % 2 == 0 else "")
        from trust.engine import evaluate_user
        for name in ("e2e_artisan", "e2e_veteran", "e2e_new"):
            evaluate_user(users[name].id, trigger="seed_e2e")

        # Deux organisations distinctes (isolation multi-organisations) avec un site et un équipement chacune.
        from django.contrib.gis.geos import Point
        from business import services as biz
        from business.models import Equipment, Organization, Site
        for key, boss, label, point in (("a", "e2e_boss_a", "Société A (e2e)", (-4.0083, 5.36)), ("b", "e2e_boss_b", "Société B (e2e)", (-3.99, 5.30))):
            org = Organization.objects.filter(owner=users[boss]).first() or biz.create_organization(users[boss], name=label, city="Abidjan")
            site, _ = Site.objects.get_or_create(organization=org, name=f"Siège {key.upper()}", defaults={"address": "Boulevard de la Paix", "city": "Abidjan", "location": Point(*point, srid=4326)})
            Equipment.objects.get_or_create(organization=org, site=site, name=f"Climatiseur {key.upper()}", defaults={"category": cat, "location_detail": "Étage 2"})

        self.stdout.write(self.style.SUCCESS("Comptes e2e_* prêts. Mot de passe de test : voir E2E_PASSWORD dans ce fichier."))

    # ------------------------------------------------------------------ nettoyage
    @transaction.atomic
    def purge(self):
        from business.models import InterventionRequest, Organization
        from handy.models import Booking, HandymanDocument, Notification, Review, User
        from trust.models import AuditEvent

        users = User.objects.filter(username__startswith=PREFIX)
        ids = list(users.values_list("id", flat=True))
        orgs = Organization.objects.filter(owner_id__in=ids)
        org_ids = list(orgs.values_list("id", flat=True))
        InterventionRequest.objects.filter(organization_id__in=org_ids).delete()
        AuditEvent.objects.filter(organization_id__in=org_ids).delete()
        orgs.delete()
        bookings = Booking.objects.filter(client_id__in=ids) | Booking.objects.filter(handyman_id__in=ids)
        Review.objects.filter(booking__in=bookings).delete()
        n_bookings = bookings.count()
        bookings.delete()
        Notification.objects.filter(user_id__in=ids).delete()
        HandymanDocument.objects.filter(handyman__user_id__in=ids).delete()
        AuditEvent.objects.filter(actor_id__in=ids).delete()
        deleted = users.count()
        users.delete()
        self.stdout.write(self.style.SUCCESS(f"Purge : {deleted} compte(s), {n_bookings} réservation(s), {len(org_ids)} organisation(s) supprimés."))
