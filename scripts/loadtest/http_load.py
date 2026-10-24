#!/usr/bin/env python3
"""Générateur de charge HTTP et WebSocket (aiohttp, déjà dans requirements.txt) — JAMAIS contre la production.

  python scripts/loadtest/http_load.py --target http://127.0.0.1:8000 --tokens tokens.json --scenario mix --concurrency 32 --duration 30
  python scripts/loadtest/http_load.py --target http://127.0.0.1:8001 --tokens tokens.json --ws 2000 --duration 60

Boucle fermée : C utilisateurs virtuels enchaînent les appels pendant D secondes (pas de file d'attente cachée côté client). Résultat :
débit, latences p50/p95/p99, erreurs par code. Cible locale par défaut ; un environnement de recette doit être nommé avec --allow-host
(et ne jamais être la production : les hôtes tratra.net, www et api sont refusés quoi qu'il arrive)."""
import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import Counter
from urllib.parse import urlsplit

import aiohttp

PRODUCTION_HOSTS = {"tratra.net", "www.tratra.net", "api.tratra.net", "minioapi.tratra.net"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
ABIDJAN = (5.345, -4.00)


def check_target(url, allow):
    host = (urlsplit(url).hostname or "").lower()
    if host in PRODUCTION_HOSTS or (host.endswith(".tratra.net") and not host.split(".")[0].startswith(("staging", "recette"))):
        sys.exit(f"Cible « {host} » refusée : aucun test de charge sur la production.")
    if host in LOCAL_HOSTS or host.endswith((".localhost", ".test")) or host in allow:
        return host
    sys.exit(f"Cible « {host} » non autorisée (locale par défaut ; --allow-host <hôte de recette>).")


def scenarios(tokens, category):
    """(nom, poids, fabrique de requête) ; chaque fabrique renvoie (méthode, chemin, jeton ou None)."""
    clients = [t for t in tokens if t["role"] == "client"]
    pros = [t for t in tokens if t["role"] == "pro"]
    lat, lng = ABIDJAN

    def jitter():
        return f"lat={lat + random.uniform(-0.05, 0.05):.4f}&lng={lng + random.uniform(-0.05, 0.05):.4f}"

    def conv():
        t = random.choice([c for c in clients if c.get("conversation")] or clients)
        return "GET", f"/handy/me/conversations/{t.get('conversation') or 0}/messages/", t
    table = {
        "catalog": (20, lambda: ("GET", "/handy/catalog/", None)),
        "nearby": (15, lambda: ("GET", f"/handy/services/nearby/?{jitter()}&radius_km=10", None)),
        "nearby_trade": (10, lambda: ("GET", f"/handy/services/nearby/?{jitter()}&radius_km=10&category_id={category}", None)),
        "notifications": (15, lambda: ("GET", "/handy/notifications/", random.choice(clients))),
        "unread": (15, lambda: ("GET", "/handy/me/messages/unread/", random.choice(clients))),
        "bookings": (8, lambda: ("GET", "/handy/bookings/", random.choice(clients))),
        "dashboard": (5, lambda: ("GET", "/handy/me/dashboard/", random.choice(clients))),
        "pro_dashboard": (3, lambda: ("GET", "/handy/me/dashboard/", random.choice(pros or clients))),
        "messages": (6, conv),
        "flash_pros": (3, lambda: ("GET", f"/handy/flash/pros/?category={category}&{jitter()}", random.choice(clients))),
    }
    return table


async def http_run(args, tokens):
    table = scenarios(tokens, args.category)
    if args.scenario == "mix":
        names = list(table)
        weights = [table[n][0] for n in names]
    else:
        names, weights = [args.scenario], [1]
    lat_by = {n: [] for n in names}
    codes = Counter()
    deadline = time.monotonic() + args.duration
    connector = aiohttp.TCPConnector(limit=0, force_close=False)
    timeout = aiohttp.ClientTimeout(total=args.timeout)

    async def user(session):
        while time.monotonic() < deadline:
            name = random.choices(names, weights)[0]
            method, path, tok = table[name][1]()
            headers = {"Host": args.host_header} if args.host_header else {}
            if tok:
                headers["Authorization"] = f"Bearer {tok['access']}"
            t = time.perf_counter()
            try:
                async with session.request(method, args.target + path, headers=headers) as r:
                    await r.read()
                    codes[r.status] += 1
            except Exception as exc:  # noqa: BLE001 — délai dépassé, connexion refusée : compté comme erreur
                codes[type(exc).__name__] += 1
                continue
            lat_by[name].append(time.perf_counter() - t)

    started = time.monotonic()
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        await asyncio.gather(*(user(session) for _ in range(args.concurrency)))
    elapsed = time.monotonic() - started
    all_lat = sorted(x for v in lat_by.values() for x in v)
    total = sum(codes.values())

    def pct(values, q):
        return round(values[min(len(values) - 1, int(q * (len(values) - 1)))] * 1000, 1) if values else None
    report = {"target": args.target, "scenario": args.scenario, "concurrency": args.concurrency, "seconds": round(elapsed, 1),
              "requests": total, "rps": round(total / elapsed, 1), "codes": dict(codes),
              "p50_ms": pct(all_lat, 0.5), "p95_ms": pct(all_lat, 0.95), "p99_ms": pct(all_lat, 0.99),
              "by_scenario": {n: {"n": len(v), "p50_ms": pct(sorted(v), 0.5), "p95_ms": pct(sorted(v), 0.95)}
                              for n, v in lat_by.items() if v}}
    return report


async def ws_run(args, tokens):
    """N connexions /ws/inbox/ tenues D secondes (ping toutes les 25 s) : capacité de connexions d'un processus."""
    users = [t for t in tokens][: args.ws] if len(tokens) >= args.ws else [tokens[i % len(tokens)] for i in range(args.ws)]
    ws_base = args.target.replace("http", "ws", 1)
    connected, failed = 0, Counter()
    connect_times = []
    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=args.timeout)) as session:
        sem = asyncio.Semaphore(100)   # ouvertures progressives (100 poignées de main à la fois), connexions tenues ensuite
        hold_until = []

        async def one(t):
            nonlocal connected
            ws = None
            try:
                async with sem:
                    async with session.post(args.http_target + "/handy/me/realtime/ticket/",
                                            headers={"Authorization": f"Bearer {t['access']}"}) as r:
                        ticket = (await r.json())["ticket"]
                    t0 = time.perf_counter()
                    ws = await session.ws_connect(f"{ws_base}/ws/inbox/?ticket={ticket}", heartbeat=None)
                    msg = await ws.receive_json(timeout=args.timeout)
                    if msg.get("type") != "ready":
                        failed["not_ready"] += 1
                        return
                    connect_times.append(time.perf_counter() - t0)
                    connected += 1
                if not hold_until:
                    hold_until.append(time.monotonic() + args.duration)
                while time.monotonic() < hold_until[0]:
                    await asyncio.sleep(min(25, max(0.1, hold_until[0] - time.monotonic())))
                    if time.monotonic() < hold_until[0]:
                        await ws.send_json({"type": "ping"})
                        await ws.receive_json(timeout=args.timeout)
            except Exception as exc:  # noqa: BLE001
                failed[type(exc).__name__] += 1
            finally:
                if ws is not None:
                    await ws.close()
        await asyncio.gather(*(one(t) for t in users))
    connect_times.sort()
    return {"target": ws_base, "requested": args.ws, "connected": connected, "failed": dict(failed),
            "connect_p50_ms": round(statistics.median(connect_times) * 1000, 1) if connect_times else None,
            "connect_p95_ms": round(connect_times[int(0.95 * (len(connect_times) - 1))] * 1000, 1) if connect_times else None}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", required=True)
    p.add_argument("--http-target", default="", help="Mode WebSocket : serveur HTTP qui délivre les billets (défaut : --target).")
    p.add_argument("--tokens", required=True)
    p.add_argument("--scenario", default="mix")
    p.add_argument("--category", type=int, default=1)
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument("--duration", type=float, default=20)
    p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--ws", type=int, default=0)
    p.add_argument("--host-header", default="")
    p.add_argument("--allow-host", action="append", default=[])
    p.add_argument("--out", default="")
    args = p.parse_args()
    args.target = args.target.rstrip("/")
    args.http_target = (args.http_target or args.target).rstrip("/")
    check_target(args.target, set(args.allow_host))
    check_target(args.http_target, set(args.allow_host))
    with open(args.tokens, encoding="utf-8") as fh:
        tokens = json.load(fh)
    report = asyncio.run(ws_run(args, tokens) if args.ws else http_run(args, tokens))
    text = json.dumps(report, ensure_ascii=False)
    print(text)
    if args.out:
        with open(args.out, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


if __name__ == "__main__":
    main()
