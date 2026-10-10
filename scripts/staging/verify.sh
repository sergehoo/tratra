#!/usr/bin/env bash
# Vérifications du STAGING après déploiement : conteneurs, HTTP/TLS, routes API, WebSocket, migrations, Celery/Beat,
# couche de canaux Redis, stockage objet, Firebase. Lecture seule : aucune donnée n'est créée ni modifiée.
# Usage : scripts/staging/verify.sh        → code 0 si aucune ANOMALIE (les AVERTISSEMENTS n'échouent pas)
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
guard

API_HOST="$(envval tratraweb_HOST)"; FRONT_HOST="$(envval FRONTEND_HOST)"
API="https://${API_HOST}"; FRONT="https://${FRONT_HOST}"
ERR=0; WARNS=0
pass() { ok "$*"; }
fail() { printf '%s[ERR ]%s %s\n' "$R" "$N" "$*" >&2; ERR=$((ERR + 1)); }
note() { warn "$*"; WARNS=$((WARNS + 1)); }
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$@" || echo 000; }

say "1. Conteneurs"
for svc in tratradb redis minio-stg tratraweb-stg worker beat tratrafrontend-stg; do
  st="$(health "$svc")"
  case "$st" in healthy|running) pass "$svc : $st" ;; *) fail "$svc : $st" ;; esac
done

say "2. HTTP / TLS (${API_HOST}, ${FRONT_HOST})"
[ "$(code "${API}/healthz")" = "200" ] && pass "GET /healthz 200 (certificat TLS valide)" || fail "GET /healthz"
ready="$(curl -s --max-time 20 "${API}/readyz" || true)"
echo "$ready" | grep -q '"ready"' && pass "GET /readyz : base + Redis joignables" || fail "GET /readyz : ${ready:-pas de réponse}"
[ "$(code "${FRONT}/")" = "200" ] && pass "frontend ${FRONT}/ 200" || fail "frontend ${FRONT}/"
loc="$(curl -sI --max-time 20 "http://${API_HOST}/healthz" | tr -d '\r' | sed -n 's/^[Ll]ocation: //p')"
case "$loc" in https://*) pass "HTTP → HTTPS ($loc)" ;; *) note "pas de redirection HTTP→HTTPS visible (dépend de l'entrypoint web de Traefik)" ;; esac

say "3. Routes API (sans authentification : le code attendu prouve que la route existe ET qu'elle est protégée)"
route() { # METHODE CHEMIN ATTENDU
  local m="$1" p="$2" want="$3" got
  if [ "$m" = "POST" ]; then got="$(code -X POST -H 'Content-Type: application/json' -d '{}' "${API}${p}")"; else got="$(code "${API}${p}")"; fi
  case "|${want}|" in *"|${got}|"*) pass "$m $p -> $got" ;; *) fail "$m $p -> $got (attendu $want)" ;; esac
}
route GET  /handy/categories/ 200
route GET  /handy/services/ 200
route GET  /handy/handymen/featured/ 200
route GET  /handy/handymen/1/trust/ '200|404'      # 404 si aucun profil publié d'identifiant 1
route GET  /handy/verify/id/TR-AAAA-BBBB/ 404
route POST /handy/verify/pass/ 401
route GET  /handy/users/me/ 401
route GET  /handy/me/dashboard/ 401
route GET  /handy/me/trust/ 401
route GET  /handy/me/tratra-id/ 401
route POST /handy/devices/ 401
route GET  /handy/bookings/1/live/ 401
route POST /handy/bookings/1/live/ticket/ 401
route POST /handy/bookings/1/identity-pass/ 401
route GET  /handy/business/orgs/ 401
route GET  /handy/business/equipment/lookup/EQ-AAAA-BBBB/ 401
route POST /handy/auth/login/ 400
route GET  /api/schema/ 401      # documentation interactive réservée aux administrateurs en production
route GET  /admin/login/ 200

say "4. WebSocket (refus sans billet = pile ASGI attachée et routée par Traefik)"
if command -v python3 >/dev/null; then
  python3 "$STAGING_SCRIPTS/ws_check.py" --api "${API}/handy" && pass "ws_check : /ws/live/ et /ws/chat/ répondent 403 sans billet" || fail "ws_check (voir ci-dessus)"
else
  w="$(code --http1.1 -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' "${API}/ws/live/1/")"
  [ "$w" = "403" ] && pass "WS /ws/live/1/ sans billet -> 403" || fail "WS /ws/live/1/ -> $w (attendu 403)"
fi

say "5. Application (dans le conteneur de l'API)"
out="$(dc exec -T tratraweb-stg python manage.py shell 2>&1 <<'PY'
import asyncio
from django.conf import settings
from django.db import connection
from django.core.files.storage import default_storage, storages

print("DEBUG=%s" % settings.DEBUG)
print("PUBLIC_WEB_URL=%s" % settings.PUBLIC_WEB_URL)
print("ALLOWED_HOSTS=%s" % ",".join(settings.ALLOWED_HOSTS))
print("STORAGE=%s" % default_storage.__class__.__name__)
print("KYC=%s" % storages["private_kyc"].__class__.__name__)
print("CELERY_QUEUE=%s" % settings.CELERY_TASK_DEFAULT_QUEUE)
from tratra.asgi import application
print("ASGI=%s" % ",".join(sorted(application.application_mapping)))
with connection.cursor() as c:
    c.execute("select postgis_version()")
    print("POSTGIS=%s" % c.fetchone()[0].split()[0])
    c.execute("select count(*) from django_migrations")
    print("MIGRATIONS=%s" % c.fetchone()[0])
from handy import push
print("FCM=%s" % ("configured" if push.is_configured() else "absent"))
from django_celery_beat.models import PeriodicTask
print("BEAT=%s" % ",".join(sorted(PeriodicTask.objects.exclude(name__startswith="celery.").values_list("task", flat=True))))
from channels.layers import get_channel_layer
async def roundtrip():
    layer = get_channel_layer()
    ch = await layer.new_channel()
    await layer.group_add("verify-staging", ch)
    await layer.group_send("verify-staging", {"type": "verify.ping", "n": 7})
    msg = await asyncio.wait_for(layer.receive(ch), 5)
    await layer.group_discard("verify-staging", ch)
    return msg["n"]
print("CHANNELS=%s" % asyncio.run(roundtrip()))
PY
)" || true
val() { printf '%s\n' "$out" | sed -n "s/^$1=//p" | tail -n1; }
[ "$(val DEBUG)" = "False" ] && pass "DEBUG=False" || fail "DEBUG=$(val DEBUG)"
case "$(val PUBLIC_WEB_URL)" in "https://${FRONT_HOST}") pass "PUBLIC_WEB_URL = frontend staging (QR valides)" ;; *) fail "PUBLIC_WEB_URL=$(val PUBLIC_WEB_URL) (attendu ${FRONT})" ;; esac
case ",$(val ALLOWED_HOSTS)," in *",${API_HOST},"*) pass "ALLOWED_HOSTS contient ${API_HOST}" ;; *) fail "ALLOWED_HOSTS ne contient pas ${API_HOST}" ;; esac
case "$(val STORAGE)" in *S3*) pass "stockage média : $(val STORAGE)" ;; *) fail "stockage média : $(val STORAGE) (attendu S3/MinIO)" ;; esac
case "$(val KYC)" in *S3*) pass "stockage KYC privé : $(val KYC) (bucket distinct, URL signées)" ;; *) fail "stockage KYC : $(val KYC) (attendu S3 privé)" ;; esac
[ "$(val CELERY_QUEUE)" = "default" ] && pass "file Celery par défaut = default (écoutée par le worker)" || fail "CELERY_TASK_DEFAULT_QUEUE=$(val CELERY_QUEUE)"
[ "$(val ASGI)" = "http,websocket" ] && pass "ASGI : http + websocket attachés" || fail "ASGI=$(val ASGI) (la pile WebSocket n'est pas attachée : voir les journaux [asgi])"
[ -n "$(val POSTGIS)" ] && pass "PostGIS $(val POSTGIS)" || fail "PostGIS indisponible"
[ "${out:+x}" = "x" ] && [ -n "$(val MIGRATIONS)" ] && pass "migrations appliquées : $(val MIGRATIONS) lignes" || fail "table django_migrations illisible"
[ "$(val CHANNELS)" = "7" ] && pass "couche de canaux Redis : aller-retour de groupe OK (diffusion WebSocket multi-processus)" || fail "couche de canaux Redis : $(val CHANNELS)"
[ "$(val FCM)" = "configured" ] && pass "FCM : identifiants chargés" || note "FCM absent : aucun push (la notification in-app reste fiable)"
for t in trust.tasks.reevaluate_all_profiles business.tasks.run_preventive_plans live.tasks.purge_positions; do
  case ",$(val BEAT)," in *",${t},"*) pass "beat : ${t}" ;; *) fail "beat : ${t} absente (le conteneur beat a-t-il démarré après les migrations ?)" ;; esac
done

say "6. Migrations et Celery"
dc exec -T tratraweb-stg python manage.py migrate --check >/dev/null 2>&1 && pass "migrate --check : aucune migration en attente" || fail "migrations en attente"
dc exec -T tratraweb-stg python manage.py makemigrations --check --dry-run >/dev/null 2>&1 && pass "makemigrations --check : modèles et migrations alignés" || fail "makemigrations --check"
dc exec -T worker celery -A tratra inspect ping --timeout 8 2>/dev/null | grep -q pong && pass "worker Celery : pong" || fail "worker Celery : pas de réponse"
dc exec -T worker celery -A tratra inspect active_queues --timeout 8 2>/dev/null | grep -q "'name': 'default'\|\"name\": \"default\"\|name: default" && pass "worker : écoute la file default" || fail "worker : file default non écoutée"
dc exec -T worker celery -A tratra inspect registered --timeout 8 2>/dev/null | grep -q "handy.tasks.send_push" && pass "worker : tâche handy.tasks.send_push enregistrée" || fail "worker : send_push absente"

say "Résultat : ${ERR} anomalie(s), ${WARNS} avertissement(s)"
[ "$ERR" -eq 0 ] || exit 1
