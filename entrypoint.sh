#!/bin/sh
set -eu

# ---------- Helpers ----------
log()   { printf "\033[1;34m[entrypoint]\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m[ OK ]\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
error() { printf "\033[1;31m[ERR ]\033[0m %s\n" "$*" >&2; }

# ---------- Defaults (adaptés à Docker) ----------
: "${DJANGO_SETTINGS_MODULE:=tratra.settings}"
: "${DEBUG:=False}"

# DB dans Docker : service "tratradb"
: "${DB_HOST:=tratradb}"
: "${DB_PORT:=5432}"
: "${DB_NAME:=tratra}"
: "${DB_USER:=postgres}"
: "${DB_PASSWORD:=}"

# Redis dans Docker : service "redis"
: "${REDIS_HOST:=redis}"
: "${REDIS_PORT:=6379}"

: "${COLLECTSTATIC:=auto}"     # auto|always|skip
: "${RUN_MIGRATIONS:=1}"       # 1 pour exécuter les migrations au démarrage
: "${CREATE_SUPERUSER:=0}"     # 1 pour créer un superuser si non présent

# ---------- Wait for Postgres ----------
wait_for_postgres() {
  if [ -z "${DB_HOST}" ]; then
    warn "DB_HOST non défini → skip wait for Postgres."
    return 0
  fi

  log "Attente Postgres ${DB_HOST}:${DB_PORT} (db=${DB_NAME} user=${DB_USER})…"
  until python - <<'PYCODE'
import os, sys, time
host=os.getenv("DB_HOST"); port=int(os.getenv("DB_PORT","5432"))
name=os.getenv("DB_NAME"); user=os.getenv("DB_USER"); pwd=os.getenv("DB_PASSWORD")

def try_psycopg2():
    import psycopg2
    psycopg2.connect(host=host, port=port, dbname=name or "postgres", user=user or None, password=pwd or None).close()

def try_psycopg3():
    import psycopg
    psycopg.connect(host=host, port=port, dbname=name or "postgres", user=user or None, password=pwd or None).close()

for _ in range(60):
    try:
        try:
            try_psycopg2()
        except ModuleNotFoundError:
            try_psycopg3()
        print("DB up")
        sys.exit(0)
    except Exception:
        time.sleep(2)

print("Timeout waiting for DB", file=sys.stderr)
sys.exit(1)
PYCODE
  do
    sleep 2
  done
  ok "Postgres prêt."
}

# ---------- Wait for Redis ----------
wait_for_redis() {
  if [ -z "${REDIS_HOST}" ]; then
    warn "REDIS_HOST non défini → skip wait for Redis."
    return 0
  fi
  log "Attente Redis ${REDIS_HOST}:${REDIS_PORT}…"
  python - <<'PYCODE'
import os, sys, socket, time
host=os.getenv("REDIS_HOST","redis"); port=int(os.getenv("REDIS_PORT","6379"))
for _ in range(60):
    try:
        s=socket.create_connection((host, port), timeout=2); s.close()
        print("Redis up"); sys.exit(0)
    except Exception:
        time.sleep(1)
print("Timeout waiting for Redis", file=sys.stderr); sys.exit(1)
PYCODE
  ok "Redis prêt."
}

# ---------- Préflight Channels ----------
# ---------- Préflight Channels (compatible Channels 4) ----------
channels_preflight() {
  log "Vérification ASGI…"
  python - <<'PY'
import os, sys, importlib

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE","tratra.settings"))

try:
    import django
    django.setup()
except Exception as e:
    print("django.setup() FAILED:", e)
    sys.exit(2)

# Charge l'app ASGI
try:
    app = importlib.import_module("tratra.asgi")
except Exception as e:
    print("import tratra.asgi FAILED:", e)
    sys.exit(2)

# Vérifie la présence de l'application ASGI
if not hasattr(app, "application"):
    print("No 'application' attribute found in tratra.asgi")
    sys.exit(2)

print("ASGI application loaded OK")
sys.exit(0)
PY
}

# ---------- Django checks / migrations / static ----------
django_checks() {
  log "Django system check…"
  # n'arrête pas le container si des WARN déploy sont émis
  python manage.py check --deploy || warn "check --deploy a émis des avertissements."
}

run_migrations() {
  if [ "${RUN_MIGRATIONS}" = "1" ]; then
    log "Migrations…"
    python manage.py migrate --noinput
    ok "Migrations OK."
  else
    warn "Skip migrate (RUN_MIGRATIONS != 1)"
  fi
}

collect_static() {
  case "$COLLECTSTATIC" in
    always)
      log "collectstatic (always)…"
      python manage.py collectstatic --noinput
      ;;
    auto)
      python - <<'PYCODE'
import os, subprocess
if os.getenv("DEBUG","False").lower() not in ("1","true","yes"):
    subprocess.check_call(["python","manage.py","collectstatic","--noinput"])
else:
    print("DEBUG on -> skip collectstatic")
PYCODE
      ;;
    skip)
      warn "COLLECTSTATIC=skip → on saute collectstatic."
      ;;
    *)
      warn "COLLECTSTATIC inconnu -> mode auto."
      python - <<'PYCODE'
import os, subprocess
if os.getenv("DEBUG","False").lower() not in ("1","true","yes"):
    subprocess.check_call(["python","manage.py","collectstatic","--noinput"])
else:
    print("DEBUG on -> skip collectstatic")
PYCODE
      ;;
  esac
}

ensure_dirs_permissions() {
  mkdir -p /app/staticfiles /app/media
  chmod -R u+rwX,go+rX /app/staticfiles /app/media || true
}

create_superuser_if_needed() {
  if [ "${CREATE_SUPERUSER}" = "1" ]; then
    log "Création superuser (si absent)…"
    python - <<'PYCODE'
import os, django
from django.contrib.auth import get_user_model
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE","tratra.settings"))
django.setup()
User=get_user_model()
username=os.getenv("DJANGO_SUPERUSER_USERNAME","admin")
email=os.getenv("DJANGO_SUPERUSER_EMAIL","admin@example.com")
password=os.getenv("DJANGO_SUPERUSER_PASSWORD","admin")
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"Superuser créé: {username}")
else:
    print(f"Superuser existant: {username}")
PYCODE
    ok "Superuser vérifié."
  else
    warn "CREATE_SUPERUSER=0 → skip création superuser."
  fi
}

# ---------- Run sequence ----------
log "DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE} | DEBUG=${DEBUG}"
wait_for_postgres
wait_for_redis
django_checks
channels_preflight
run_migrations
collect_static
ensure_dirs_permissions
create_superuser_if_needed

log "Démarrage du process application: $*"
exec "$@"