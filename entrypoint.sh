#!/usr/bin/env bash
set -euo pipefail

# ---------- Helpers ----------
log()   { printf "\033[1;34m[entrypoint]\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m[ OK ]\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
error() { printf "\033[1;31m[ERR ]\033[0m %s\n" "$*" >&2; }

# Defaults
: "${DJANGO_SETTINGS_MODULE:=abmci.settings.prod}"
: "${DEBUG:=False}"
: "${DB_HOST:=}"
: "${DB_PORT:=5432}"
: "${DB_NAME:=}"
: "${DB_USER:=}"
: "${DB_PASSWORD:=}"
: "${REDIS_HOST:=}"
: "${REDIS_PORT:=6379}"
: "${COLLECTSTATIC:=auto}"     # auto|always|skip
: "${RUN_MIGRATIONS:=1}"       # 1 pour exécuter les migrations au démarrage
: "${CREATE_SUPERUSER:=0}"     # 1 pour créer un superuser si non présent
#: "${DJANGO_SUPERUSER_USERNAME:=admin}"
#: "${DJANGO_SUPERUSER_EMAIL:=admin@example.com}"
#: "${DJANGO_SUPERUSER_PASSWORD:=admin}"

# ---------- Wait for Postgres ----------
wait_for_postgres() {
  if [ -z "$DB_HOST" ]; then
    warn "DB_HOST non défini → skip wait for Postgres."
    return 0
  fi

  log "Attente Postgres ${DB_HOST}:${DB_PORT} (db=${DB_NAME} user=${DB_USER})…"
  until python - <<'PYCODE'
import os, sys
import time
try:
    import psycopg2
except Exception as e:
    print("psycopg2 manquant ?", e); sys.exit(1)

host=os.getenv("DB_HOST"); port=int(os.getenv("DB_PORT","5432"))
name=os.getenv("DB_NAME"); user=os.getenv("DB_USER"); pwd=os.getenv("DB_PASSWORD")
for _ in range(60):
    try:
        psycopg2.connect(host=host, port=port, dbname=name or "postgres", user=user or None, password=pwd or None).close()
        print("DB up")
        sys.exit(0)
    except Exception as e:
        time.sleep(2)
print("Timeout waiting for DB", file=sys.stderr)
sys.exit(1)
PYCODE
  do sleep 2; done
  ok "Postgres prêt."
}

# ---------- Wait for Redis (facultatif) ----------
wait_for_redis() {
  if [ -z "$REDIS_HOST" ]; then
    warn "REDIS_HOST non défini → skip wait for Redis."
    return 0
  fi
  log "Attente Redis ${REDIS_HOST}:${REDIS_PORT}…"
  python - <<'PYCODE'
import os, sys, socket, time
host=os.getenv("REDIS_HOST"); port=int(os.getenv("REDIS_PORT","6379"))
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

# ---------- Django checks / migrations / static ----------
django_checks() {
  log "Django system check…"
  python manage.py check --deploy || warn "check --deploy a émis des avertissements."
}

run_migrations() {
  if [ "${RUN_MIGRATIONS}" = "1" ]; then
    log "Migrations…"
    python manage.py migrate --noinput
    ok "Migrations OK."
  else
    echo "Skip migrate (RUN_MIGRATIONS != 1)"
  fi
}

collect_static() {
  case "$COLLECTSTATIC" in
    always)
      log "collectstatic (always)…"
      python manage.py collectstatic --noinput
      ;;
    auto)
      # Lance collectstatic si DEBUG=False
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
      warn "COLLECTSTATIC inconnu (${COLLECTSTATIC}) → mode auto."
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
import os
from django.contrib.auth import get_user_model
import django
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
run_migrations
collect_static
ensure_dirs_permissions
create_superuser_if_needed

log "Démarrage du process application: $*"
exec "$@"