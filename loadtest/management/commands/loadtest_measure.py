"""Mesures DANS LE PROCESSUS sur la base de mesure (aucun réseau, aucun SMS, aucun push) : ce que coûte réellement chaque écran.

  DJANGO_ENV=loadtest python manage.py loadtest_measure [--only endpoints,flash,announce,storage,hash,presign,explain] [--out f.json]

  endpoints  requêtes SQL et temps serveur (médiane, p95) des écrans les plus appelés, avec le client de test Django ;
  flash      Smart Dispatch : professionnels examinés, retenus, requêtes et temps par vague selon le métier ;
  announce   diffusion d'une annonce : comptes par seconde et requêtes par compte (sur un sous-ensemble) ;
  storage    octets par ligne (données + index) des tables principales → projection du stockage ;
  hash       coût CPU d'une vérification de mot de passe (connexion) ;
  presign    coût d'une URL signée S3/MinIO (calcul local, sans réseau) ;
  explain    plans PostgreSQL des requêtes clés (parcours séquentiel ou index).
Les chiffres valent pour la machine qui exécute la mesure : ils servent à comparer et à repérer ce qui croît avec le volume."""
import json
import statistics
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone

from loadtest import guard

PARTS = ("endpoints", "flash", "announce", "storage", "hash", "presign", "explain")
ABIDJAN = (5.345, -4.00)


def _ms(seconds):
    return round(seconds * 1000, 2)


def _pctl(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


class Rollback(Exception):
    pass


class QueryCounter:
    """Compte TOUTES les requêtes SQL et leur durée (CaptureQueriesContext plafonne à 9 000)."""

    def __init__(self):
        self.n, self.seconds = 0, 0.0

    def __call__(self, execute, sql, params, many, context):
        t = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.n += 1
            self.seconds += time.perf_counter() - t

    def __enter__(self):
        self._cm = connection.execute_wrapper(self)
        self._cm.__enter__()
        return self

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)


class Command(BaseCommand):
    help = "Mesures dans le processus sur la base de mesure (tratra_loadtest)."

    def add_arguments(self, parser):
        parser.add_argument("--only", default=",".join(PARTS))
        parser.add_argument("--repeat", type=int, default=15, help="Appels chronométrés par écran.")
        parser.add_argument("--announce-users", type=int, default=3000, help="Comptes visés par l'annonce de mesure (sous-ensemble).")
        parser.add_argument("--out", default="")

    def handle(self, *args, **o):
        guard.assert_safe()
        self.repeat = max(3, o["repeat"])
        result = {"database": connection.settings_dict["NAME"], "at": timezone.now().isoformat(), "counts": self._counts()}
        for part in [p.strip() for p in o["only"].split(",") if p.strip()]:
            if part not in PARTS:
                self.stderr.write(f"Partie inconnue : {part}")
                continue
            t = time.monotonic()
            result[part] = getattr(self, f"_{part}")(o)
            self.stdout.write(f"— {part} : {time.monotonic() - t:.1f} s")
        text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        if o["out"]:
            with open(o["out"], "w", encoding="utf-8") as fh:
                fh.write(text)
            self.stdout.write(f"Résultats : {o['out']}")
        else:
            self.stdout.write(text)

    # ------------------------------------------------------------------------------------------------------------ outils

    def _counts(self):
        from flash.models import MissionOffer
        from handy.models import Booking, HandymanProfile, Message, Notification, Service, User

        return {m.__name__: m.objects.count() for m in (User, HandymanProfile, Service, Booking, Notification, Message, MissionOffer)}

    def _sample(self):
        """Comptes représentatifs : client avec réservations et conversation, professionnel du métier le plus fourni."""
        from django.db.models import Count

        from handy.models import Conversation, HandymanProfile, ServiceCategory

        conv = Conversation.objects.filter(booking__isnull=False).select_related("booking").order_by("id").first()
        top = (ServiceCategory.objects.filter(parent__isnull=True).annotate(n=Count("handymen")).order_by("-n").first())
        small = (ServiceCategory.objects.filter(parent__isnull=True).annotate(n=Count("handymen")).filter(n__gt=0).order_by("n").first())
        pro = HandymanProfile.objects.filter(is_approved=True, skills=top).select_related("user").order_by("id").first()
        return {"client": conv.booking.client, "conversation": conv.pk, "pro": pro, "top": top, "small": small}

    def _token(self, user):
        from rest_framework_simplejwt.tokens import AccessToken

        return f"Bearer {AccessToken.for_user(user)}"

    def _time(self, fn):
        """(médiane ms, p95 ms, requêtes, temps SQL ms, statut, octets) d'un appel ; les écritures sont annulées après chaque appel."""
        def once():
            try:
                with transaction.atomic():
                    r = fn()
                    raise Rollback(r)
            except Rollback as rb:
                return rb.args[0]
        once()  # préchauffage
        times = []
        for _ in range(self.repeat):
            t = time.perf_counter()
            r = once()
            times.append(time.perf_counter() - t)
        with QueryCounter() as qc:
            r = once()
        return {"median_ms": _ms(statistics.median(times)), "p95_ms": _ms(_pctl(times, 0.95)), "queries": qc.n,
                "sql_ms": round(qc.seconds * 1000, 1), "status": getattr(r, "status_code", None), "bytes": len(getattr(r, "content", b"") or b"")}

    # ------------------------------------------------------------------------------------------------------------ parties

    def _endpoints(self, o):
        s = self._sample()
        c = Client(HTTP_HOST="127.0.0.1")
        client_auth = {"HTTP_AUTHORIZATION": self._token(s["client"])}
        pro_auth = {"HTTP_AUTHORIZATION": self._token(s["pro"].user)}
        lat, lng = ABIDJAN
        top = s["top"].pk
        scenarios = [
            ("catalogue (anonyme)", lambda: c.get("/handy/catalog/")),
            ("services proches 10 km (anonyme)", lambda: c.get(f"/handy/services/nearby/?lat={lat}&lng={lng}&radius_km=10")),
            ("services proches 10 km, métier le plus fourni", lambda: c.get(f"/handy/services/nearby/?lat={lat}&lng={lng}&radius_km=10&category_id={top}")),
            ("liste des services d'un métier (anonyme)", lambda: c.get(f"/handy/services/?categories={top}")),
            ("chiffres publics (anonyme)", lambda: c.get("/handy/public/stats/")),
            ("fiche publique d'un professionnel", lambda: c.get(f"/handy/handymen/{s['pro'].pk}/", **client_auth)),
            ("avis d'un professionnel (anonyme)", lambda: c.get(f"/handy/handymen/{s['pro'].pk}/reviews/")),
            ("passeport Trust (anonyme)", lambda: c.get(f"/handy/handymen/{s['pro'].pk}/trust/")),
            ("réservations du client", lambda: c.get("/handy/bookings/", **client_auth)),
            ("notifications du client", lambda: c.get("/handy/notifications/", **client_auth)),
            ("tableau de bord client", lambda: c.get("/handy/me/dashboard/", **client_auth)),
            ("tableau de bord professionnel", lambda: c.get("/handy/me/dashboard/", **pro_auth)),
            ("conversations du client", lambda: c.get("/handy/me/conversations/", **client_auth)),
            ("messages d'une conversation", lambda: c.get(f"/handy/me/conversations/{s['conversation']}/messages/", **client_auth)),
            ("non-lus (pastille)", lambda: c.get("/handy/me/messages/unread/", **client_auth)),
            ("Flash : mode conseillé (métier le plus fourni)", lambda: c.get(f"/handy/flash/suggest/?category={top}&lat={lat}&lng={lng}", **client_auth)),
            ("Flash : choisir son pro (métier le plus fourni)", lambda: c.get(f"/handy/flash/pros/?category={top}&lat={lat}&lng={lng}", **client_auth)),
            ("Flash : propositions du professionnel", lambda: c.get("/handy/flash/offers/", **pro_auth)),
        ]
        out = {}
        for name, fn in scenarios:
            out[name] = self._time(fn)
            m = out[name]
            self.stdout.write(f"  {name:55} {m['status']} médiane {m['median_ms']:8.1f} ms  p95 {m['p95_ms']:8.1f} ms  "
                              f"{m['queries']:5d} requêtes  SQL {m['sql_ms']:8.1f} ms")
        return out

    def _flash(self, o):
        from django.contrib.gis.geos import Point
        from django.db.models import Count

        from flash import services as S
        from flash.models import DispatchConfig, MissionRequest
        from handy.eligibility import publishable
        from handy.models import HandymanProfile, ServiceCategory

        s = self._sample()
        config = DispatchConfig.get_solo()
        out = {}
        cats = list(ServiceCategory.objects.filter(parent__isnull=True).annotate(n=Count("handymen")).filter(n__gt=0).order_by("-n"))
        for cat in (cats[0], cats[len(cats) // 2], cats[-1]):
            for label, loc in (("position Abidjan", Point(ABIDJAN[1], ABIDJAN[0], srid=4326)), ("commune seule", None)):
                req = MissionRequest(client=s["client"], category=cat, commune="Cocody", scheduled_for=timezone.now() + timedelta(hours=3),
                                     is_immediate=False, location=loc)
                family = S.category_family(cat)
                examined = (publishable(HandymanProfile.objects.all())
                            .filter(user__services__is_active=True, user__services__category_id__in=family).distinct().count())
                with QueryCounter() as qc:
                    t = time.perf_counter()
                    kept, rejected = S.candidates(req, config, explain=True)
                    elapsed = time.perf_counter() - t
                key = f"{cat.name} / {label}"
                out[key] = {"pros_in_trade_nationwide": examined, "evaluated": len(kept) + len(rejected), "kept": len(kept),
                            "queries": qc.n, "sql_ms": _ms(qc.seconds), "ms": _ms(elapsed)}
                self.stdout.write(f"  {key:40} examinés {len(kept) + len(rejected):6d}  retenus {len(kept):6d}  "
                                  f"{qc.n:6d} requêtes  {_ms(elapsed):9.1f} ms")
        return out

    def _announce(self, o):
        from announcements import services as A
        from announcements.models import Announcement
        from handy.models import User

        out = {}
        ids = list(User.objects.filter(is_active=True, is_staff=False, city="Korhogo").values_list("pk", flat=True)[: o["announce_users"]])
        for push in (False, True):
            a = Announcement.objects.create(title="Annonce de mesure", body="Mesure de diffusion.", kind="service", to_clients=True,
                                            to_artisans=True, cities=["Korhogo"], send_push=push, status="published",
                                            published_at=timezone.now())
            audience = A.audience_queryset(a).count()
            with QueryCounter() as qc:
                t = time.perf_counter()
                created = A.deliver(a.pk)
                elapsed = time.perf_counter() - t
            key = "avec push (mise en file)" if push else "sans push"
            out[key] = {"audience": audience, "delivered": created, "seconds": round(elapsed, 2),
                        "users_per_second": round(created / elapsed, 1) if elapsed else None,
                        "queries_per_user": round(qc.n / max(1, created), 2)}
            self.stdout.write(f"  annonce {key:25} {created} comptes en {elapsed:.1f} s → {out[key]['users_per_second']} comptes/s, "
                              f"{out[key]['queries_per_user']} requêtes/compte")
        out["korhogo_accounts"] = len(ids)
        return out

    def _storage(self, o):
        tables = ["handy_user", "handy_handymanprofile", "handy_service", "handy_booking", "handy_notification", "handy_message",
                  "handy_device", "handy_review", "flash_missionoffer", "flash_dispatchevent", "announcements_announcementdelivery",
                  "antifraud_smslog", "antifraud_signuplog"]
        out = {}
        with connection.cursor() as c:
            for t in tables:
                c.execute("SELECT to_regclass(%s)", [t])
                if c.fetchone()[0] is None:
                    continue
                c.execute(f'SELECT count(*), pg_relation_size(%s), pg_indexes_size(%s), pg_total_relation_size(%s) FROM "{t}"', [t, t, t])
                n, heap, idx, total = c.fetchone()
                out[t] = {"rows": n, "heap_bytes": heap, "index_bytes": idx, "total_bytes": total,
                          "bytes_per_row": round(total / n) if n else None}
                self.stdout.write(f"  {t:40} {n:9d} lignes  {total / 1048576:8.1f} Mo  {out[t]['bytes_per_row'] or 0:6d} o/ligne")
        return out

    def _hash(self, o):
        from django.contrib.auth.hashers import check_password, get_hasher, make_password

        hasher = get_hasher()
        encoded = make_password("mot-de-passe-de-mesure")
        times = []
        for _ in range(5):
            t = time.perf_counter()
            check_password("mot-de-passe-de-mesure", encoded)
            times.append(time.perf_counter() - t)
        out = {"algorithm": hasher.algorithm, "iterations": getattr(hasher, "iterations", None), "median_ms": _ms(statistics.median(times))}
        self.stdout.write(f"  {out}")
        return out

    def _presign(self, o):
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            return {"skipped": "boto3 absent"}
        s3 = boto3.client("s3", endpoint_url="https://minio.example.invalid", aws_access_key_id="MESURE", aws_secret_access_key="MESURE",
                          region_name="us-east-1", config=Config(signature_version="s3v4"))
        n = 2000
        t = time.perf_counter()
        for i in range(n):
            s3.generate_presigned_url("get_object", Params={"Bucket": "media", "Key": f"profile_pics/{i}.jpg"}, ExpiresIn=604800)
        per = (time.perf_counter() - t) / n
        out = {"urls": n, "per_url_ms": round(per * 1000, 3)}
        self.stdout.write(f"  URL signée : {out['per_url_ms']} ms par URL (calcul local)")
        return out

    def _explain(self, o):
        """Plans des VRAIES requêtes de l'application (mêmes querysets que les vues)."""
        from django.contrib.gis.geos import Point

        from flash import services as S
        from handy.api import views as V
        from handy.eligibility import publishable
        from handy.models import HandymanProfile, Notification

        s = self._sample()
        origin = Point(ABIDJAN[1], ABIDJAN[0], srid=4326)
        family = S.category_family(s["top"])
        querysets = {
            "services proches 10 km (page 1)": V.apply_public_service_filters(V.search_services_nearby_qs(origin, None, 10), {})[:20],
            "services proches 10 km (comptage de la pagination)": V.apply_public_service_filters(
                V.search_services_nearby_qs(origin, None, 10), {}).order_by().values("pk"),
            "Flash : professionnels examinés (métier le plus fourni)": publishable(HandymanProfile.objects.all()).filter(
                user__services__is_active=True, user__services__category_id__in=family).distinct(),
            "notifications d'un compte (page 1)": Notification.objects.filter(user=s["client"]).order_by("-created_at")[:20],
        }
        out = {}
        for name, qs in querysets.items():
            text = qs.explain(analyze=True)
            lines = text.splitlines()
            scans = [ln.strip().split("  (")[0].lstrip("-> ") for ln in lines if "Scan" in ln]
            ms = next((ln.split(":")[1].strip() for ln in lines if ln.startswith("Execution Time")), "")
            out[name] = {"execution": ms, "scans": scans}
            self.stdout.write(f"  {name:55} {ms:>12}  {' | '.join(scans)[:150]}")
        return out
