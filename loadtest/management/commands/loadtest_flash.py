"""Tratra Flash sous charge (phase 3, fiabilité et concurrence) — base jetable et Redis dédié, jamais la production, aucun SMS ni push.

  DJANGO_ENV=loadtest python manage.py loadtest_flash [--sizes 100,500,1000] [--procs 6] [--threads 8] [--out f.json]
  (ou : scripts/loadtest/run_local.sh flash — lance aussi le Redis dédié)

Pour chaque taille N : N demandes créées au même instant par N clients (processus × fils : vraie concurrence, pas seulement des fils
Python), paliers suivants, acceptations simultanées de TOUS les professionnels alertés d'une moitié des demandes, expiration de l'autre
moitié (tâche ciblée par demande exécutée ici, puis par un vrai worker Celery, puis passage global), annulations. Sont mesurés :
p50/p95/p99, requêtes SQL par opération, CPU et mémoire (générateur, PostgreSQL, worker), attentes de verrou, interblocages, tâches
Celery produites par file, et les invariants (une attribution par demande, jamais deux alertes en attente chez un professionnel).
L'état de la base est remis d'aplomb après chaque taille (demandes et réservations du test annulées, disponibilité restaurée)."""
import json
import os
import random
import re
import resource
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

ABIDJAN, SPAN = (5.345, -4.00), 0.09
QUEUES = ("flash", "default", "otp", "bulk", "notifications")


def _pctl(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))] if values else None


def _shape(sql):
    """Forme d'une requête (sans ses valeurs) : sert à désigner les requêtes les plus coûteuses d'une phase."""
    return re.sub(r"\s+", " ", re.sub(r"(%s(, )?)+", "%s", str(sql)))[:170]


class _Counter(threading.local):
    """Requêtes SQL du fil courant (nombre, durée) et, pour tout le processus, durée cumulée par forme de requête."""
    n, seconds = 0, 0.0
    shapes, lock = {}, threading.Lock()

    def __call__(self, execute, sql, params, many, context):
        t = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            d = time.perf_counter() - t
            self.n += 1
            self.seconds += d
            with self.lock:
                row = self.shapes.setdefault(_shape(sql), [0, 0.0])
                row[0] += 1
                row[1] += d


def _top(shapes, k=5):
    rows = sorted(shapes.items(), key=lambda kv: -kv[1][1])[:k]
    return [{"sql": sql, "calls": n, "total_s": round(sec, 2), "avg_ms": round(1000 * sec / n, 2)} for sql, (n, sec) in rows]


class Command(BaseCommand):
    help = "Tratra Flash sous charge : créations, acceptations et expirations simultanées (base jetable)."

    def add_arguments(self, parser):
        parser.add_argument("--sizes", default="100,500,1000")
        parser.add_argument("--procs", type=int, default=6)
        parser.add_argument("--threads", type=int, default=8)
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--out", default="")
        parser.add_argument("--no-celery", action="store_true", help="Ne pas lancer de worker Celery (tâches ciblées exécutées ici seulement).")
        parser.add_argument("--worker", default="", help=argparse_hidden)
        parser.add_argument("--start-at", type=float, default=0.0, help=argparse_hidden)

    # ───────────────────────────────────────────────────────────────────────────────────────────── processus de charge
    def _worker(self, path, threads, start_at):
        from flash import services as S
        from flash import tasks
        from handy.models import ServiceCategory, User

        jobs = json.load(open(path, encoding="utf-8"))
        cats = {c.pk: c for c in ServiceCategory.objects.filter(pk__in={j["category"] for j in jobs if "category" in j})}
        counter = _Counter()

        def init():
            connection.ensure_connection()
            connection.execute_wrappers.append(counter)

        def run(job):
            counter.n, counter.seconds = 0, 0.0
            extra, t = {}, time.perf_counter()
            try:
                op = job["op"]
                if op == "create":
                    req = S.create_request(User.objects.get(pk=job["client"]), category=cats[job["category"]], address="Rue de mesure",
                                           commune="Cocody", mode="firm", amount=15000, lat=job["lat"], lng=job["lng"])
                    extra["id"] = req.pk
                elif op == "step":
                    S.launch_wave(job["id"])
                elif op == "accept":
                    S.accept(job["offer"], User.objects.get(pk=job["pro"]))
                elif op == "expire":
                    tasks.wave_timeout(job["id"], 1)
                elif op == "cancel":
                    S.cancel_request(job["id"], User.objects.get(pk=job["client"]))
                out = "ok"
            except S.FlashError as e:
                out = e.code
            except Exception as e:  # noqa: BLE001 — interblocage, intégrité : compté et rapporté tel quel
                out = f"!{type(e).__name__}: {str(e)[:120]}"
            return {"ms": round((time.perf_counter() - t) * 1000, 2), "q": counter.n, "sql_ms": round(counter.seconds * 1000, 2),
                    "out": out, "end": time.time(), **extra}

        connection.close()
        with ThreadPoolExecutor(threads, initializer=init) as pool:
            list(pool.map(lambda _: None, range(threads * 4)))            # connexions ouvertes avant le départ
            time.sleep(max(0.0, start_at - time.time()))
            counter.shapes.clear()
            r0 = resource.getrusage(resource.RUSAGE_SELF)
            results = list(pool.map(run, jobs))
        ru = resource.getrusage(resource.RUSAGE_SELF)
        rss = ru.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
        json.dump({"results": results, "cpu": ru.ru_utime + ru.ru_stime - r0.ru_utime - r0.ru_stime, "rss_mb": rss,
                   "shapes": counter.shapes}, open(path + ".out", "w", encoding="utf-8"))

    # ──────────────────────────────────────────────────────────────────────────────────────────────────── sondes
    def _pg(self):
        with connection.cursor() as c:
            c.execute("SELECT xact_commit, xact_rollback, deadlocks, tup_returned + tup_fetched, tup_inserted + tup_updated + tup_deleted, "
                      "temp_files FROM pg_stat_database WHERE datname = current_database()")
            return dict(zip(("commits", "rollbacks", "deadlocks", "rows_read", "rows_written", "temp_files"), c.fetchone()))

    def _queues(self):
        return {q: self.redis.llen(q) for q in QUEUES}

    def _ps(self, pattern):
        """(CPU %, mémoire Mo) des processus dont la commande contient `pattern` — instantané `ps`."""
        text = subprocess.run(["ps", "-Ao", "%cpu=,rss=,command="], capture_output=True, text=True).stdout
        cpu = rss = 0.0
        for line in text.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3 and pattern in parts[2] and "loadtest_flash" not in parts[2]:
                cpu, rss = cpu + float(parts[0].replace(",", ".")), rss + float(parts[1]) / 1024
        return cpu, rss

    def _sample(self, stop, into, extra_pattern=None):
        from django.db import connections

        conn = connections.create_connection("default")
        try:
            while not stop.is_set():
                with conn.cursor() as c:
                    c.execute("SELECT count(*) FILTER (WHERE state = 'active'), count(*) FILTER (WHERE wait_event_type = 'Lock'), count(*) "
                              "FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()")
                    active, waiting, backends = c.fetchone()
                cpu, rss = self._ps("postgres")
                row = {"active": active, "lock_wait": waiting, "backends": backends, "pg_cpu": cpu, "pg_rss": rss,
                       "queue": sum(self._queues().values())}
                if extra_pattern:
                    row["w_cpu"], row["w_rss"] = self._ps(extra_pattern)
                into.append(row)
                stop.wait(0.5)
        finally:
            conn.close()

    def _summary(self, samples, before, after, queues0, queues1, wall):
        peak = lambda k: max((s[k] for s in samples), default=0)  # noqa: E731
        mean = lambda k: round(sum(s[k] for s in samples) / len(samples), 1) if samples else 0  # noqa: E731
        return {"pg": {k: after[k] - before[k] for k in before}, "pg_cpu_pct_avg": mean("pg_cpu"), "pg_cpu_pct_max": round(peak("pg_cpu"), 1),
                "pg_rss_mb_max": round(peak("pg_rss")), "backends_max": peak("backends"), "active_max": peak("active"),
                "lock_wait_max": peak("lock_wait"), "lock_wait_avg": mean("lock_wait"),
                "tasks_enqueued": {q: queues1[q] - queues0[q] for q in QUEUES if queues1[q] != queues0[q]},
                "tx_per_s": round((after["commits"] - before["commits"]) / wall, 1) if wall else None}

    # ─────────────────────────────────────────────────────────────────────────────────────────────── une phase mesurée
    def _phase(self, name, jobs):
        if not jobs:
            self.stdout.write(f"  {name:22} (rien à faire)")
            return {"count": 0}, []
        procs = min(self.procs, max(1, len(jobs) // 4))
        tmp = tempfile.mkdtemp(prefix="flashload-")
        paths = []
        for i in range(procs):
            paths.append(os.path.join(tmp, f"jobs{i}.json"))
            json.dump(jobs[i::procs], open(paths[-1], "w", encoding="utf-8"))
        before, queues0, samples, stop = self._pg(), self._queues(), [], threading.Event()
        start_at = time.time() + 7.0
        children = [subprocess.Popen([sys.executable, "manage.py", "loadtest_flash", "--worker", p, "--threads", str(self.threads),
                                      "--start-at", str(start_at)], env=os.environ.copy()) for p in paths]
        time.sleep(max(0.0, start_at - time.time()))
        sampler = threading.Thread(target=self._sample, args=(stop, samples))
        sampler.start()
        codes = [c.wait() for c in children]
        stop.set()
        sampler.join()
        if any(codes):
            raise CommandError(f"Phase {name} : un processus de charge a échoué ({codes}).")
        outs = [json.load(open(p + ".out", encoding="utf-8")) for p in paths]
        results = [r for o in outs for r in o["results"]]
        wall = max(r["end"] for r in results) - start_at
        ms, outcomes = [r["ms"] for r in results], Counter(r["out"].split(":")[0] for r in results)
        shapes = {}
        for o in outs:
            for sql, (calls, sec) in o["shapes"].items():
                row = shapes.setdefault(sql, [0, 0.0])
                row[0], row[1] = row[0] + calls, row[1] + sec
        row = {"count": len(results), "concurrency": procs * self.threads, "wall_s": round(wall, 2), "per_s": round(len(results) / wall, 1),
               "p50_ms": _pctl(ms, 0.5), "p95_ms": _pctl(ms, 0.95), "p99_ms": _pctl(ms, 0.99), "max_ms": max(ms),
               "queries_p50": _pctl([r["q"] for r in results], 0.5), "queries_max": max(r["q"] for r in results),
               "sql_ms_p50": _pctl([r["sql_ms"] for r in results], 0.5), "sql_ms_p95": _pctl([r["sql_ms"] for r in results], 0.95),
               "outcomes": dict(outcomes), "errors": sorted({r["out"] for r in results if r["out"].startswith("!")})[:5],
               "loadgen_cpu_cores": round(sum(o["cpu"] for o in outs) / wall, 2), "loadgen_rss_mb": round(sum(o["rss_mb"] for o in outs)),
               "sql_total_s": round(sum(v[1] for v in shapes.values()), 2), "top_sql": _top(shapes),
               **self._summary(samples, before, self._pg(), queues0, self._queues(), wall)}
        self.stdout.write(f"  {name:22} {row['count']:5d} op.  {row['wall_s']:6.2f} s  {row['per_s']:7.1f}/s  p50 {row['p50_ms']:8.1f}  "
                          f"p95 {row['p95_ms']:8.1f}  p99 {row['p99_ms']:8.1f} ms  SQL {row['queries_p50']}/op (max {row['queries_max']})  "
                          f"verrous en attente max {row['lock_wait_max']}  PG {row['pg_cpu_pct_avg']} %  {dict(outcomes)}")
        for q in row["top_sql"][:2]:
            self.stdout.write(f"      SQL {100 * q['total_s'] / max(0.01, row['sql_total_s']):3.0f} % du temps SQL · {q['calls']} appels · "
                              f"{q['avg_ms']} ms · {q['sql'][:120]}")
        return row, results

    # ───────────────────────────────────────────────────────────────────────────────────────────────── état et remise
    def _state(self, ids):
        from django.db.models import Count, Q

        from flash.models import MissionOffer, MissionRequest

        reqs = MissionRequest.objects.filter(pk__in=ids)
        per = Counter(reqs.annotate(n=Count("offers", filter=Q(offers__status="pending"))).values_list("n", flat=True))
        double = (MissionOffer.objects.filter(status="pending", expires_at__gt=timezone.now()).values("handyman_id")
                  .annotate(n=Count("id")).filter(n__gt=1).count())
        radius = Counter(reqs.filter(status="searching").values_list("radius_m", flat=True))
        return {"status": dict(Counter(reqs.values_list("status", flat=True))), "pending_offers_per_request": dict(sorted(per.items())),
                "radius_m_of_open": dict(sorted(radius.items())), "consent_asked": reqs.filter(consent_asked_at__isnull=False).count(),
                "offers": MissionOffer.objects.filter(request_id__in=ids).count(), "pros_with_two_pending_alerts": double}

    def _restore(self, online_ids):
        """Annule ce que le test a laissé ouvert et rend leur disponibilité aux professionnels (base jetable, rien n'est supprimé)."""
        from flash import services as S
        from flash.models import MissionRequest
        from handy.models import Booking, HandymanProfile

        for req in MissionRequest.objects.filter(status__in=MissionRequest.OPEN).select_related("client"):
            try:
                S.cancel_request(req.pk, req.client)
            except S.FlashError:
                pass
        for b in Booking.objects.filter(flash_request__isnull=False, status__in=("pending", "confirmed")).select_related("client"):
            b.transition_to("cancelled", actor=b.client)
        HandymanProfile.objects.filter(user_id__in=online_ids, online=False).update(online=True)
        for q in QUEUES:
            self.redis.delete(q)

    def _celery(self, ids):
        """Tâches ciblées exécutées par un VRAI worker Celery (file « flash », 4 processus) : débit et file d'attente."""
        from flash import tasks
        from flash.models import MissionOffer

        for q in QUEUES:
            self.redis.delete(q)
        env = os.environ.copy()
        if sys.platform == "darwin":     # macOS seulement : sans cela les processus fils du worker (fork) meurent à la 1re connexion
            env.update(OBJC_DISABLE_INITIALIZE_FORK_SAFETY="YES", no_proxy="*", PGGSSENCMODE="disable")
        worker = subprocess.Popen([os.path.join(os.path.dirname(sys.executable), "celery"), "-A", "tratra", "worker", "-Q", "flash,default",
                                   "-c", "4", "-l", "ERROR", "--without-gossip", "--without-mingle", "--without-heartbeat",
                                   "-n", "flashload@%h"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            from tratra.celery import app

            for _ in range(60):
                if app.control.ping(timeout=0.5):
                    break
            else:
                raise CommandError("Worker Celery injoignable.")
            before, samples, stop = self._pg(), [], threading.Event()
            sampler = threading.Thread(target=self._sample, args=(stop, samples, "flashload@"))
            sampler.start()
            t = time.perf_counter()
            for rid in ids:
                tasks.wave_timeout.apply_async(args=(rid, 1), retry=False)
            enqueue_s = time.perf_counter() - t
            due = MissionOffer.objects.filter(request_id__in=ids, status="pending", expires_at__lt=timezone.now())
            while due.exists() and time.perf_counter() - t < 120:
                time.sleep(0.2)
            wall = time.perf_counter() - t
            stop.set()
            sampler.join()
            row = {"count": len(ids), "worker_processes": 4, "enqueue_s": round(enqueue_s, 2), "wall_s": round(wall, 2),
                   "per_s": round(len(ids) / wall, 1), "left_undone": due.count(), "queue_max": max((s["queue"] for s in samples), default=0),
                   "worker_cpu_pct_avg": round(sum(s["w_cpu"] for s in samples) / max(1, len(samples)), 1),
                   "worker_rss_mb_max": round(max((s["w_rss"] for s in samples), default=0)),
                   **self._summary(samples, before, self._pg(), {q: 0 for q in QUEUES}, {q: 0 for q in QUEUES}, wall)}
            self.stdout.write(f"  {'expire (worker Celery)':22} {row['count']:5d} tâches  {row['wall_s']:6.2f} s  {row['per_s']:7.1f}/s  "
                              f"file max {row['queue_max']}  CPU worker {row['worker_cpu_pct_avg']} %  mém. {row['worker_rss_mb_max']} Mo")
            return row
        finally:
            worker.terminate()
            try:
                worker.wait(20)
            except subprocess.TimeoutExpired:
                worker.kill()

    # ───────────────────────────────────────────────────────────────────────────────────────────────────── une taille
    def _size(self, n, rng, online_ids):
        from django.db.models import Count

        from flash import services as S
        from flash.models import DispatchConfig, MissionOffer, MissionRequest
        from handy.models import Booking, ServiceCategory, User

        cats = list(ServiceCategory.objects.filter(parent__isnull=True, is_active=True).annotate(n=Count("handymen")).filter(n__gt=0))
        clients = list(User.objects.filter(handyman_profile__isnull=True, is_active=True, is_staff=False).order_by("id")
                       .values_list("pk", flat=True)[:n])
        picks = rng.choices(cats, weights=[c.n for c in cats], k=n)
        out = {"requests": n}
        jobs = [{"op": "create", "client": c, "category": cat.pk, "lat": ABIDJAN[0] + rng.uniform(-SPAN, SPAN),
                 "lng": ABIDJAN[1] + rng.uniform(-SPAN, SPAN)} for c, cat in zip(clients, picks)]
        out["create"], created = self._phase("création + 1re vague", jobs)
        ids = [r["id"] for r in created if "id" in r]
        owner = dict(MissionRequest.objects.filter(pk__in=ids).values_list("pk", "client_id"))
        out["after_create"] = self._state(ids)
        for round_no in (1, 2):                                            # paliers suivants : le rayon s'élargit, d'autres pros sont alertés
            open_ids = list(MissionRequest.objects.filter(pk__in=ids, status="searching").values_list("pk", flat=True))
            MissionRequest.objects.filter(pk__in=open_ids).update(next_step_at=timezone.now())
            out[f"step{round_no}"], _ = self._phase(f"palier suivant n° {round_no}", [{"op": "step", "id": i} for i in open_ids])
        out["after_steps"] = self._state(ids)
        self.stdout.write(f"  état : {out['after_steps']['status']}  alertes en attente par demande {out['after_steps']['pending_offers_per_request']}"
                          f"  rayons {out['after_steps']['radius_m_of_open']}")

        with_offers = sorted(set(MissionOffer.objects.filter(request_id__in=ids, status="pending").values_list("request_id", flat=True)))
        rng.shuffle(with_offers)
        half = len(with_offers) // 2
        accept_ids, expire_ids = with_offers[:half], with_offers[half:]
        # Les phases précédentes peuvent durer plus que le délai de réponse : sans cela, la phase mesurerait surtout des refus
        # « délai écoulé » au lieu de la concurrence. Les alertes à accepter repartent donc d'un délai entier, juste avant la phase.
        MissionOffer.objects.filter(request_id__in=accept_ids, status="pending").update(
            expires_at=timezone.now() + timedelta(seconds=DispatchConfig.get_solo().offer_timeout_seconds))
        pairs = list(MissionOffer.objects.filter(request_id__in=accept_ids, status="pending").values_list("pk", "handyman_id"))
        rng.shuffle(pairs)
        out["accept"], _ = self._phase("acceptations simultanées", [{"op": "accept", "offer": o, "pro": p} for o, p in pairs])
        accepted = Counter(MissionOffer.objects.filter(request_id__in=accept_ids, status="accepted").values_list("request_id", flat=True))
        bookings = Booking.objects.filter(flash_request__in=accept_ids)
        out["accept_invariants"] = {
            "requests": len(accept_ids), "offers_answered": len(pairs), "assigned": len(accepted),
            "requests_with_two_accepted": sum(1 for v in accepted.values() if v > 1), "bookings": bookings.count(),
            "pros_with_two_bookings": bookings.values("handyman_id").annotate(n=Count("id")).filter(n__gt=1).count(),
            "still_pending": MissionOffer.objects.filter(request_id__in=accept_ids, status="pending").count()}
        self.stdout.write(f"  invariants : {out['accept_invariants']}")

        # Expiration : les alertes de l'autre moitié sont échues. Trois façons de les traiter, sur trois tiers.
        MissionOffer.objects.filter(request_id__in=expire_ids, status="pending").update(expires_at=timezone.now() - timedelta(seconds=60))
        third = max(1, len(expire_ids) // 3)
        scoped, by_celery, by_tick = expire_ids[:third], expire_ids[third:2 * third], expire_ids[2 * third:]
        out["expire_scoped"], _ = self._phase("expiration ciblée", [{"op": "expire", "id": i} for i in scoped])
        if by_celery and not self.no_celery:
            out["expire_celery"] = self._celery(by_celery)
        else:
            by_tick = by_celery + by_tick
        counter = _Counter()
        counter.shapes.clear()
        before, t = self._pg(), time.perf_counter()
        with connection.execute_wrapper(counter):
            done = S.expire_due()
        wall = time.perf_counter() - t
        out["expire_global"] = {"requests": len(by_tick), "result": done, "wall_s": round(wall, 2), "queries": counter.n,
                                "top_sql": _top(counter.shapes, 3),
                                "ms_per_request": round(1000 * wall / max(1, len(by_tick)), 1),
                                "pg": {k: v - before[k] for k, v in self._pg().items()}}
        self.stdout.write(f"  {'passage global (tick)':22} {len(by_tick):5d} demandes  {wall:6.2f} s  {counter.n} requêtes SQL  {done}")
        out["after_expiry"] = self._state(ids)
        open_ids = list(MissionRequest.objects.filter(pk__in=ids, status__in=MissionRequest.OPEN).values_list("pk", flat=True))
        out["cancel"], _ = self._phase("annulations", [{"op": "cancel", "id": i, "client": owner[i]} for i in open_ids])
        out["final"] = self._state(ids)
        self._restore(online_ids)
        return out

    def handle(self, *args, **o):
        if o["worker"]:
            return self._worker(o["worker"], o["threads"], o["start_at"])
        import redis

        from flash.models import DispatchConfig, MissionRequest
        from handy.models import HandymanProfile

        if not settings.DATABASES["default"]["NAME"].startswith("tratra_loadtest") or not getattr(settings, "LOADTEST_REDIS_URL", ""):
            raise CommandError("Base jetable et Redis dédié obligatoires : scripts/loadtest/run_local.sh flash")
        self.procs, self.threads, self.no_celery = o["procs"], o["threads"], o["no_celery"]
        self.redis = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        MissionRequest.OPEN = getattr(MissionRequest, "OPEN", ("searching", "quoting", "awaiting"))
        online_ids = list(HandymanProfile.objects.filter(online=True).values_list("user_id", flat=True))
        self._restore(online_ids)                                           # reliquat d'un passage interrompu
        with connection.cursor() as c:
            c.execute("SHOW max_connections")
            max_conn = c.fetchone()[0]
            c.execute("SELECT version()")
            version = c.fetchone()[0].split(",")[0]
        config = DispatchConfig.get_solo()
        report = {"at": timezone.now().isoformat(), "machine": {"cpus": os.cpu_count(), "ram_gb": round(os.sysconf("SC_PAGE_SIZE") *
                  os.sysconf("SC_PHYS_PAGES") / 2 ** 30)}, "postgres": version, "max_connections": int(max_conn),
                  "load": {"processes": self.procs, "threads_per_process": self.threads},
                  "dataset": {"pros": HandymanProfile.objects.count(), "pros_online": len(online_ids)},
                  "config": {k: getattr(config, k) for k in ("wave_size", "offer_timeout_seconds", "max_pending_offers", "max_contacts",
                                                             "radius_steps", "far_radius_km", "step_seconds")}, "sizes": {}}
        self.stdout.write(f"Machine {report['machine']}, {version}, max_connections {max_conn}, charge {self.procs} × {self.threads}, "
                          f"{len(online_ids)} professionnels disponibles sur {report['dataset']['pros']}")
        for n in [int(x) for x in o["sizes"].split(",") if x.strip()]:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{n} demandes simultanées"))
            report["sizes"][str(n)] = self._size(n, random.Random(o["seed"] + n), online_ids)
        if o["out"]:
            json.dump(report, open(o["out"], "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
            self.stdout.write(f"\nRésultats : {o['out']}")


argparse_hidden = "(interne)"
