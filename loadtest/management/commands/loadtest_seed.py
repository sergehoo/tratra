"""Données SYNTHÉTIQUES de mesure (base jetable « tratra_loadtest… » uniquement) : comptes, professionnels éligibles, offres, réservations,
avis, notifications, appareils, conversations, historique Tratra Flash. Déterministe (--seed), insertions en lot, sans signaux.

  DJANGO_ENV=loadtest python manage.py loadtest_seed --users 100000 --pros 10000 [--reset]

Répartition : 70 % des comptes à Abidjan (10 communes), le reste dans 4 villes ; popularité des métiers en loi de Zipf (le premier
métier concentre les professionnels : cas le plus dur pour Tratra Flash). Aucun numéro réel n'est visé : +225 07 9x xx xx xx fictifs,
et l'environnement de mesure refuse tout envoi SMS ou push (loadtest/guard.py)."""
import random
import time
import uuid
from datetime import time as dtime, timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from loadtest import guard

CITIES = [  # (ville, lat, lng, étendue en degrés, communes, part des comptes)
    ("Abidjan", 5.345, -4.00, 0.09, ["Cocody", "Yopougon", "Abobo", "Marcory", "Treichville", "Koumassi", "Plateau", "Adjamé",
                                      "Port-Bouët", "Attécoubé"], 0.70),
    ("Bouaké", 7.69, -5.03, 0.04, ["Bouaké"], 0.09),
    ("Yamoussoukro", 6.82, -5.28, 0.04, ["Yamoussoukro"], 0.07),
    ("San-Pédro", 4.75, -6.64, 0.03, ["San-Pédro"], 0.07),
    ("Korhogo", 9.45, -5.63, 0.03, ["Korhogo"], 0.07),
]
TRADES = ["Plomberie", "Électricité", "Ménage", "Peinture", "Menuiserie", "Maçonnerie", "Climatisation", "Coiffure", "Mécanique",
          "Jardinage", "Serrurerie", "Couture", "Informatique", "Déménagement", "Carrelage", "Soudure", "Vitrerie", "Nounou",
          "Cuisine", "Livraison"]
NOTIF_TYPES = [("booking_confirmed", "booking"), ("message_received", "message"), ("review_received", "review"),
               ("announcement", "announcement"), ("booking_completed", "booking"), ("payment_received", "payment")]
BATCH = 5000


class Command(BaseCommand):
    help = "Données synthétiques de mesure (base jetable tratra_loadtest uniquement)."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=20000, help="Comptes au total (clients + professionnels).")
        parser.add_argument("--pros", type=int, default=2000, help="Professionnels parmi ces comptes.")
        parser.add_argument("--bookings-per-client", type=float, default=1.0)
        parser.add_argument("--notifications-per-user", type=int, default=5)
        parser.add_argument("--conversations", type=int, default=0, help="Défaut : un dixième des comptes.")
        parser.add_argument("--messages-per-conversation", type=int, default=15)
        parser.add_argument("--flash-history-per-pro", type=int, default=4, help="Propositions Tratra Flash passées par professionnel.")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--reset", action="store_true", help="Vide d'abord les tables de la base de mesure (jamais une autre base).")

    def handle(self, *args, **o):
        guard.assert_safe()
        self.rng = random.Random(o["seed"])
        self.t0 = time.monotonic()
        if o["reset"]:
            self._reset()
        n_users, n_pros = o["users"], min(o["pros"], o["users"] - 1)
        cats = self._categories()
        users = self._users(n_users, n_pros)
        pros, clients = users[:n_pros], users[n_pros:]
        profiles = self._profiles(pros, cats)
        services = self._services(profiles, cats)
        bookings = self._bookings(clients, profiles, services, o["bookings_per_client"])
        self._reviews(bookings)
        self._notifications(users, o["notifications_per_user"])
        self._devices(users)
        self._conversations(bookings, o["conversations"] or max(1, n_users // 10), o["messages_per_conversation"])
        self._flash_history(clients, profiles, cats, o["flash_history_per_pro"])
        with connection.cursor() as c:
            c.execute("ANALYZE")
        self._log(f"Terminé : {n_users} comptes dont {len(profiles)} professionnels.")

    # ------------------------------------------------------------------------------------------------------------- outils

    def _log(self, msg):
        self.stdout.write(f"[{time.monotonic() - self.t0:7.1f} s] {msg}")

    def _bulk(self, model, objs):
        out = []
        for i in range(0, len(objs), BATCH):
            with transaction.atomic():
                out += model.objects.bulk_create(objs[i:i + BATCH], batch_size=BATCH)
        return out

    def _place(self):
        r = self.rng.random()
        acc = 0.0
        for city, lat, lng, span, communes, share in CITIES:
            acc += share
            if r <= acc:
                break
        return (city, self.rng.choice(communes), Point(lng + self.rng.uniform(-span, span), lat + self.rng.uniform(-span, span), srid=4326))

    def _reset(self):
        guard.assert_safe()
        with connection.cursor() as c:
            c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN "
                      "('django_migrations','spatial_ref_sys','django_content_type','auth_permission','django_site')")
            tables = [r[0] for r in c.fetchall()]
            if tables:
                c.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE")
        self._log(f"Base de mesure vidée ({len(tables)} tables).")

    # ------------------------------------------------------------------------------------------------------------ données

    def _categories(self):
        from handy.models import ServiceCategory

        parents = []
        for i, name in enumerate(TRADES):
            parents.append(ServiceCategory.objects.get_or_create(slug=f"lt-{i}", defaults={"name": name, "position": i})[0])
        children = []
        for p in parents:
            for j in range(3):
                children.append(ServiceCategory.objects.get_or_create(
                    slug=f"lt-{p.pk}-{j}", defaults={"name": f"{p.name} — prestation {j + 1}", "parent": p, "position": j})[0])
        self.weights = [1 / (r + 1) ** 0.9 for r in range(len(parents))]  # loi de Zipf : le 1er métier concentre l'offre
        self._log(f"Catalogue : {len(parents)} métiers, {len(children)} prestations.")
        return {"parents": parents, "children": children}

    def _users(self, n_users, n_pros):
        from handy.models import User

        password = make_password(uuid.uuid4().hex)  # un seul hachage (les comptes de mesure se connectent par jetons émis localement)
        now = timezone.now()
        base = User.objects.count()
        objs = []
        for i in range(n_users):
            city, commune, pt = self._place()
            k = base + i
            objs.append(User(username=f"lt{k}", phone=f"+225079{k:07d}", first_name=f"Prénom{k}", last_name=f"Nom{k % 997}",
                             password=password, user_type="handyman" if i < n_pros else "client", city=city, is_verified=True,
                             terms_accepted_at=now, last_location=pt, date_joined=now - timedelta(days=self.rng.randint(0, 700))))
        users = self._bulk(User, objs)
        self._log(f"Comptes : {len(users)}.")
        return users

    def _profiles(self, pros, cats):
        from handy.models import AvailabilitySlot, HandymanDocument, HandymanProfile, ServiceArea

        objs, places = [], []
        for u in pros:
            city, commune, pt = self._place()
            places.append(pt)
            objs.append(HandymanProfile(
                user_id=u.pk, bio="Professionnel de mesure.", experience_years=self.rng.randint(1, 15), commune=commune, quartier=commune,
                photo="profile_pics/loadtest.jpg", is_approved=self.rng.random() < 0.9, location=pt, online=self.rng.random() < 0.35,
                trust_score=self.rng.choice([None, *range(40, 96)]), rating=round(self.rng.uniform(3, 5), 2),
                completed_jobs=self.rng.randint(0, 200)))
        profiles = self._bulk(HandymanProfile, objs)
        through = HandymanProfile.skills.through
        skills, areas, docs, slots = [], [], [], []
        for p, pt in zip(profiles, places):
            parent = self.rng.choices(cats["parents"], weights=self.weights)[0]
            chosen = {parent.pk}
            if self.rng.random() < 0.3:
                chosen.add(self.rng.choices(cats["parents"], weights=self.weights)[0].pk)
            skills += [through(handymanprofile_id=p.pk, servicecategory_id=c) for c in chosen]
            p._trades = sorted(chosen)
            if self.rng.random() < 0.5:
                areas.append(ServiceArea(handyman_id=p.pk, center=pt, radius_km=self.rng.choice([5, 10, 15, 20])))
            docs.append(HandymanDocument(handyman_id=p.pk, document_type="id_card", status="approved", file="kyc/loadtest.jpg"))
            if self.rng.random() < 0.5:
                slots += [AvailabilitySlot(handyman_id=p.pk, weekday=d, start_time=dtime(7), end_time=dtime(20)) for d in range(6)]
        self._bulk(through, skills)
        self._bulk(ServiceArea, areas)
        self._bulk(HandymanDocument, docs)
        self._bulk(AvailabilitySlot, slots)
        self._log(f"Professionnels : {len(profiles)} (spécialités {len(skills)}, zones {len(areas)}, horaires {len(slots)}).")
        return profiles

    def _services(self, profiles, cats):
        from handy.models import Service

        by_parent = {}
        for c in cats["children"]:
            by_parent.setdefault(c.parent_id, []).append(c.pk)
        objs = []
        for p in profiles:
            for trade in p._trades:
                for cat in [trade] + self.rng.sample(by_parent[trade], self.rng.randint(0, 2)):
                    kind = self.rng.choice(["fixed", "hourly", "quote"])
                    objs.append(Service(handyman_id=p.user_id, category_id=cat, title=f"Prestation {cat}", description="Mesure.",
                                        price_type=kind, price=None if kind == "quote" else Decimal(self.rng.randint(20, 400) * 100)))
        services = self._bulk(Service, objs)
        self._log(f"Offres : {len(services)}.")
        by_user = {}
        for s in services:
            by_user.setdefault(s.handyman_id, []).append(s)
        return by_user

    def _bookings(self, clients, profiles, services, per_client):
        from handy.models import Booking

        now = timezone.now()
        statuses = ["completed"] * 60 + ["cancelled"] * 15 + ["confirmed"] * 10 + ["pending"] * 10 + ["in_progress"] * 5
        objs = []
        n = int(len(clients) * per_client)
        for _ in range(n):
            client = self.rng.choice(clients)
            pro = self.rng.choice(profiles)
            status = self.rng.choice(statuses)
            when = now + timedelta(days=self.rng.uniform(1, 30)) if status in ("confirmed", "pending") else \
                now - timedelta(days=self.rng.uniform(0, 365))
            svc = self.rng.choice(services.get(pro.user_id) or [None])
            price = Decimal(self.rng.randint(50, 500) * 100)
            objs.append(Booking(client_id=client.pk, handyman_id=pro.user_id, service=svc, booking_date=when, address="Adresse de mesure",
                                city="Abidjan", postal_code="00225", status=status, proposed_price=price, total_price=price,
                                job_location=pro.location, booking_type="scheduled"))
        bookings = self._bulk(Booking, objs)
        with connection.cursor() as c:  # dates de création étalées (auto_now_add les aurait toutes mises à maintenant)
            c.execute("UPDATE handy_booking SET created_at = booking_date - interval '2 days' WHERE created_at > booking_date")
        self._log(f"Réservations : {len(bookings)}.")
        return bookings

    def _reviews(self, bookings):
        from handy.models import Review

        now = timezone.now()
        objs = [Review(booking_id=b.pk, rating=self.rng.choice([3, 4, 4, 5, 5, 5]), comment="Avis de mesure.", revealed_at=now,
                       quality=self.rng.randint(3, 5), punctuality=self.rng.randint(3, 5))
                for b in bookings if b.status == "completed" and self.rng.random() < 0.4]
        self._bulk(Review, objs)
        self._log(f"Avis : {len(objs)}.")

    def _notifications(self, users, per_user):
        from handy.models import Notification

        objs = []
        total = 0
        for u in users:
            for _ in range(per_user):
                ntype, cat = self.rng.choice(NOTIF_TYPES)
                objs.append(Notification(user_id=u.pk, notification_type=ntype, category=cat, title="Mesure", message="Notification de mesure.",
                                         is_read=self.rng.random() < 0.7, data={"kind": "booking", "id": 1}))
            if len(objs) >= BATCH * 4:
                total += len(self._bulk(Notification, objs))
                objs = []
        total += len(self._bulk(Notification, objs))
        with connection.cursor() as c:
            c.execute("UPDATE handy_notification SET created_at = now() - random() * interval '180 days'")
        self._log(f"Notifications : {total}.")

    def _devices(self, users):
        from handy.models import Device

        objs = [Device(user_id=u.pk, device_token=uuid.UUID(int=self.rng.getrandbits(128)).hex * 3, device_type="android")
                for u in users if self.rng.random() < 0.8]
        self._bulk(Device, objs)
        self._log(f"Appareils : {len(objs)}.")

    def _conversations(self, bookings, n_conv, per_conv):
        from handy.models import Conversation, Message

        picks = self.rng.sample(bookings, min(n_conv, len(bookings)))
        now = timezone.now()
        convs = self._bulk(Conversation, [Conversation(booking_id=b.pk, last_message_at=now, last_message_preview="Message de mesure")
                                          for b in picks])
        through = Conversation.participants.through
        self._bulk(through, [through(conversation_id=c.pk, user_id=uid) for c, b in zip(convs, picks)
                             for uid in (b.client_id, b.handyman_id)])
        msgs = []
        total = 0
        for c, b in zip(convs, picks):
            for k in range(per_conv):
                msgs.append(Message(conversation_id=c.pk, sender_id=b.client_id if k % 2 else b.handyman_id,
                                    content="Bonjour, message de mesure.", is_read=k < per_conv - 2))
            if len(msgs) >= BATCH * 4:
                total += len(self._bulk(Message, msgs))
                msgs = []
        total += len(self._bulk(Message, msgs))
        self._log(f"Conversations : {len(convs)}, messages : {total}.")

    def _flash_history(self, clients, profiles, cats, per_pro):
        from flash.models import MissionOffer, MissionRequest

        if per_pro <= 0:
            return
        now = timezone.now()
        reqs = self._bulk(MissionRequest, [
            MissionRequest(client_id=self.rng.choice(clients).pk, category=self.rng.choice(cats["parents"]), address="Adresse de mesure",
                           commune="Cocody", scheduled_for=now - timedelta(days=self.rng.uniform(0, 30)), mode="firm", amount=5000,
                           status="unfulfilled", wave=1)
            for _ in range(max(1, len(profiles) * per_pro // 3))])
        offers, seen = [], set()
        for p in profiles:
            for _ in range(per_pro):
                r = self.rng.choice(reqs)
                if (r.pk, p.user_id) in seen:
                    continue
                seen.add((r.pk, p.user_id))
                st = self.rng.choice(["declined", "expired", "expired", "declined", "quoted"])
                offers.append(MissionOffer(request_id=r.pk, handyman_id=p.user_id, wave=1, rank=1, score=50.0, expires_at=now,
                                           status=st if st != "quoted" else "declined", response_seconds=self.rng.randint(5, 80)))
        self._bulk(MissionOffer, offers)
        with connection.cursor() as c:
            c.execute("UPDATE flash_missionoffer SET sent_at = now() - random() * interval '30 days'")
        self._log(f"Tratra Flash (historique) : {len(reqs)} demandes, {len(offers)} propositions.")
