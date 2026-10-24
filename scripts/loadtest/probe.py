#!/usr/bin/env python3
"""Sondes du banc de charge (utilisées par run_local.sh) : CPU, mémoire, activité SQL. Lecture seule.

  probe.py cpu <pid>…            secondes de CPU cumulées des processus ET de leurs descendants (workers gunicorn)
  probe.py mem <pid>…            mémoire physique (actuelle et pic) des processus et descendants, en Mo
  probe.py pg                    compteurs PostgreSQL de la base de mesure (transactions, lignes lues, blocs) — DJANGO_ENV=loadtest
  probe.py iostat <fichier>      moyenne de l'utilisation CPU de la machine relevée par `iostat -w 1` pendant un tir
  probe.py summary <avant.json> <après.json> <secondes> <requêtes>   écarts par seconde et par requête
  probe.py line <runs.jsonl>     dernière mesure en une ligne lisible
"""
import json
import os
import re
import subprocess
import sys


def _tree(pids):
    rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,time="], capture_output=True, text=True).stdout.split("\n")
    table = {}
    for row in rows:
        parts = row.split()
        if len(parts) == 3:
            table[int(parts[0])] = (int(parts[1]), parts[2])
    out, todo = set(), [int(p) for p in pids]
    while todo:
        pid = todo.pop()
        if pid in out or pid not in table:
            continue
        out.add(pid)
        todo += [child for child, (parent, _) in table.items() if parent == pid]
    return out, table


def _seconds(text):
    days = 0
    if "-" in text:
        d, text = text.split("-", 1)
        days = int(d)
    parts = [float(p) for p in text.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts
    return days * 86400 + h * 3600 + m * 60 + s


def cpu(pids):
    tree, table = _tree(pids)
    print(round(sum(_seconds(table[p][1]) for p in tree), 2))


def mem(pids):
    tree, _ = _tree(pids)
    now = peak = 0.0
    for pid in tree:
        text = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True).stdout if sys.platform == "darwin" else ""
        if text:
            def mb(key):
                m = re.search(rf"{key}:\s+([\d.]+)\s+([KMG]B)", text)
                if not m:
                    return 0.0
                v = float(m.group(1))
                return v / 1024 if m.group(2) == "KB" else v * 1024 if m.group(2) == "GB" else v
            now += mb("phys_footprint")
            peak += mb("phys_footprint_peak")
        else:
            rss = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
            now += float(rss or 0) / 1024
            peak = max(peak, now)
    print(json.dumps({"processes": len(tree), "mb": round(now, 1), "peak_mb": round(peak, 1)}))


def pg():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tratra.settings")
    sys.path.insert(0, os.getcwd())
    import django

    django.setup()
    from django.db import connection

    with connection.cursor() as c:
        c.execute("SELECT xact_commit, xact_rollback, tup_returned, tup_fetched, tup_inserted, tup_updated, tup_deleted, blks_hit, "
                  "blks_read, numbackends FROM pg_stat_database WHERE datname = current_database()")
        names = [d[0] for d in c.description]
        print(json.dumps(dict(zip(names, c.fetchone()))))


def iostat(path):
    us = sy = n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 6 and all(re.fullmatch(r"[\d.]+", p) for p in parts[-6:]):
                # colonnes CPU d'iostat macOS : us sy id puis charge 1/5/15 min
                u, s = float(parts[-6]), float(parts[-5])
                us, sy, n = us + u, sy + s, n + 1
    print(json.dumps({"machine_cpu_pct": round((us + sy) / n, 1) if n else None, "samples": n}))


def summary(before, after, seconds, requests):
    a, b = json.load(open(before)), json.load(open(after))
    d = {k: b[k] - a[k] for k in a if k != "numbackends"}
    s, r = float(seconds), max(1, int(requests))
    hit = d["blks_hit"] + d["blks_read"]
    print(json.dumps({"sql_xact_per_s": round(d["xact_commit"] / s, 1), "rows_read_per_request": round((d["tup_returned"] + d["tup_fetched"]) / r),
                      "rows_written": d["tup_inserted"] + d["tup_updated"] + d["tup_deleted"],
                      "cache_hit_pct": round(100 * d["blks_hit"] / hit, 2) if hit else None, "disk_blocks_read": d["blks_read"]}))


def line(path):
    with open(path, encoding="utf-8") as fh:
        r = json.loads(fh.read().strip().splitlines()[-1])
    print(f"{r['label']} {r['server']:8} {r['scenario']:13} {r['concurrency']:3} util. : {r['rps']:7} req/s  p95 {r['p95_ms']} ms  "
          f"p99 {r['p99_ms']} ms  erreurs {r['errors']}  CPU serveur {r['server_cpu_pct']} %  machine {r.get('machine_cpu_pct')} %  "
          f"mém. {r['server_mem']['peak_mb']} Mo  SQL {r.get('sql_xact_per_s')} tx/s, {r.get('rows_read_per_request')} lignes/req")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"cpu": lambda: cpu(args), "mem": lambda: mem(args), "pg": pg, "iostat": lambda: iostat(args[0]),
     "summary": lambda: summary(*args), "line": lambda: line(args[0])}[cmd]()
