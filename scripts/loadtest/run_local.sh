#!/usr/bin/env bash
# Tests de charge LOCAUX et reproductibles (jamais la production, aucun SMS ni push) : voir docs/scalabilite-30m.md.
#
#   scripts/loadtest/run_local.sh seed 200000 20000      base jetable tratra_loadtest : 200 000 comptes dont 20 000 professionnels
#   scripts/loadtest/run_local.sh measure                 mesures dans le processus (requêtes SQL par écran, Flash, annonces, stockage)
#   scripts/loadtest/run_local.sh http                    débit HTTP : Daphne 1 processus (comme la production) puis gunicorn N processus
#   scripts/loadtest/run_local.sh ws 2000                 connexions WebSocket tenues par un processus Daphne (+ mémoire)
#
# Variables : OUT (dossier des résultats, défaut ./loadtest-results), WORKERS (gunicorn, défaut 4), CONCURRENCY (« 8 32 64 »),
# SCENARIOS (« mix » par défaut ; ou un écran seul : catalog, nearby, notifications, unread, bookings, dashboard, flash_pros…),
# DURATION (s, défaut 20), LOADTEST_REDIS_PORT (Redis DÉDIÉ lancé ici, défaut 6391 ; jamais celui d'un autre projet).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

PY=venv/bin/python
OUT="${OUT:-$PWD/loadtest-results}"
WORKERS="${WORKERS:-4}"
CONCURRENCY="${CONCURRENCY:-8 32 64}"
SCENARIOS="${SCENARIOS:-mix}"
DURATION="${DURATION:-20}"
RPORT="${LOADTEST_REDIS_PORT:-6391}"
mkdir -p "$OUT"

# Environnement de mesure : réglages loadtest, Redis dédié, AUCUN fournisseur SMS ni compte de service push (même si le .env en contient).
export DJANGO_ENV=loadtest LOADTEST_REDIS_URL="redis://127.0.0.1:$RPORT"
export SMS_BACKEND="" TWILIO_ACCOUNT_SID="" TWILIO_AUTH_TOKEN="" TWILIO_PHONE_NUMBER="" TWILIO_MESSAGING_SERVICE_SID="" TWILIO_FROM=""
export AT_USERNAME="" AT_API_KEY="" FCM_CREDENTIALS_FILE="" FCM_CREDENTIALS_JSON="" SENTRY_DSN=""

redis_up() {
  if ! redis-cli -p "$RPORT" ping >/dev/null 2>&1; then
    redis-server --port "$RPORT" --bind 127.0.0.1 --save "" --appendonly no --daemonize yes --dir "$OUT" --logfile "$OUT/redis.log"
    for _ in $(seq 1 20); do redis-cli -p "$RPORT" ping >/dev/null 2>&1 && break; sleep 0.2; done
  fi
}
wait_http() { for _ in $(seq 1 60); do curl -fs -o /dev/null "http://127.0.0.1:$1/handy/catalog/" && return 0; sleep 0.5; done; return 1; }
# Mémoire d'un processus : empreinte physique sous macOS (compte la mémoire compressée, que le RSS ignore), RSS ailleurs.
rss_mb() {
  if command -v footprint >/dev/null 2>&1; then
    footprint -p "$1" 2>/dev/null | awk '/phys_footprint:/ {v=$2; u=$3} END {if (u ~ /^G/) v*=1024; if (u ~ /^K/) v/=1024; printf "%.1f", v}'
  else
    ps -o rss= -p "$1" 2>/dev/null | awk '{s+=$1} END {printf "%.1f", s/1024}'
  fi
}
tree_rss_mb() { ps -o rss=,ppid=,pid= -A | awk -v p="$1" '$3==p || $2==p {s+=$1} END {printf "%.1f", s/1024}'; }
top_category() { $PY manage.py shell -c "from django.db.models import Count; from handy.models import ServiceCategory as C; print(C.objects.filter(parent__isnull=True).annotate(n=Count('handymen')).order_by('-n').first().pk)" 2>/dev/null | tail -1; }

case "${1:-}" in
  seed)
    $PY manage.py migrate --noinput >/dev/null
    $PY manage.py loadtest_seed --users "${2:-20000}" --pros "${3:-2000}" --reset
    ;;
  measure)
    $PY manage.py loadtest_measure --out "$OUT/measure-$(date +%Y%m%d-%H%M%S).json"
    ;;
  http)
    redis_up
    $PY manage.py loadtest_tokens --count 400 --out "$OUT/tokens.json" >/dev/null
    CAT="$(top_category)"
    for server in daphne gunicorn; do
      if [ "$server" = daphne ]; then
        venv/bin/daphne -b 127.0.0.1 -p 8101 tratra.asgi:application >"$OUT/daphne.log" 2>&1 & PID=$!; PORT=8101
      else
        LOADTEST_CONN_MAX_AGE=60 venv/bin/gunicorn tratra.wsgi:application -w "$WORKERS" -b 127.0.0.1:8102 --timeout 120 \
          >"$OUT/gunicorn.log" 2>&1 & PID=$!; PORT=8102
      fi
      wait_http "$PORT" || { echo "Serveur $server injoignable" >&2; kill "$PID"; exit 1; }
      for scenario in $SCENARIOS; do
        for c in $CONCURRENCY; do
          $PY scripts/loadtest/http_load.py --target "http://127.0.0.1:$PORT" --tokens "$OUT/tokens.json" --scenario "$scenario" \
            --category "$CAT" --concurrency "$c" --duration "$DURATION" --out "$OUT/http-$server.jsonl" >/dev/null
          echo "$server ($([ "$server" = gunicorn ] && echo "$WORKERS processus" || echo "1 processus")), $scenario, $c utilisateurs : $(tail -1 "$OUT/http-$server.jsonl")"
        done
      done
      echo "$server mémoire : $(tree_rss_mb "$PID") Mo"
      kill "$PID"; wait "$PID" 2>/dev/null || true
    done
    ;;
  ws)
    redis_up
    N="${2:-1000}"
    ulimit -n 16384 2>/dev/null || ulimit -n "$(ulimit -Hn)" 2>/dev/null || true   # une connexion = un descripteur (client et serveur)
    $PY manage.py loadtest_tokens --count "$N" --pros 0 --out "$OUT/tokens-ws.json" >/dev/null
    venv/bin/daphne -b 127.0.0.1 -p 8101 tratra.asgi:application >"$OUT/daphne-ws.log" 2>&1 & PID=$!
    wait_http 8101 || { echo "Daphne injoignable" >&2; kill "$PID"; exit 1; }
    BEFORE="$(rss_mb "$PID")"
    $PY scripts/loadtest/http_load.py --target "http://127.0.0.1:8101" --tokens "$OUT/tokens-ws.json" --ws "$N" --duration "$DURATION" \
      --out "$OUT/ws.jsonl" >"$OUT/ws-last.json" &
    LOAD=$!
    sleep $(( DURATION / 2 + 5 ))
    DURING="$(rss_mb "$PID")"; KEYS="$(redis-cli -p "$RPORT" -n 2 dbsize)"; RMEM="$(redis-cli -p "$RPORT" info memory | sed -n 's/^used_memory_human://p' | tr -d '\r')"
    wait "$LOAD" || true
    echo "WebSocket : $(cat "$OUT/ws-last.json")"
    echo "Daphne : $BEFORE Mo au repos → $DURING Mo pendant le test ; Redis (Channels) : $KEYS clés, $RMEM"
    kill "$PID"; wait "$PID" 2>/dev/null || true
    ;;
  stop-redis)
    redis-cli -p "$RPORT" shutdown nosave >/dev/null 2>&1 || true
    ;;
  *)
    sed -n '2,12p' "$0"; exit 2 ;;
esac
