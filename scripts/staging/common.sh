#!/usr/bin/env bash
# Fonctions communes des scripts de staging (à sourcer). N'exécute rien par lui-même.
#
# Garde-fous : ces scripts ne pilotent QUE le projet Compose « tratra-staging » et refusent de tourner si .env ne décrit
# pas un hôte de staging. Le fichier .env n'est jamais « sourcé » (valeurs arbitraires) : extraction clé par clé.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
STAGING_SCRIPTS="$ROOT/scripts/staging"

COMPOSE_FILE="docker-compose.staging.yml"
# STAGING_PROJECT : uniquement pour la répétition locale (scripts/staging/rehearsal.sh) ; ne jamais le pointer vers la production.
PROJECT="${STAGING_PROJECT:-tratra-staging}"

dc() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }

if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; N=$'\033[0m'; else B=""; G=""; R=""; Y=""; N=""; fi
say()  { printf '%s[staging]%s %s\n' "$B" "$N" "$*"; }
ok()   { printf '%s[ OK ]%s %s\n' "$G" "$N" "$*"; }
warn() { printf '%s[WARN]%s %s\n' "$Y" "$N" "$*" >&2; }
die()  { printf '%s[ERR ]%s %s\n' "$R" "$N" "$*" >&2; exit 1; }

# envval CLE : dernière valeur de CLE dans .env (sans guillemets). Ne l'affichez jamais pour un secret.
envval() { sed -n "s/^$1=//p" .env | tail -n1 | sed -e 's/^"//' -e 's/"$//'; }

guard() {
  command -v docker >/dev/null || die "docker introuvable"
  docker compose version >/dev/null 2>&1 || die "« docker compose » (v2) introuvable"
  [ -f "$COMPOSE_FILE" ] || die "$COMPOSE_FILE introuvable (lancer depuis le dépôt)"
  [ -f .env ] || die ".env introuvable : cp .env.staging.example .env && chmod 600 .env, puis renseigner les valeurs"

  local host; host="$(envval tratraweb_HOST)"
  case "$host" in
    *staging*|*stg*) ;;
    *) [ "${STAGING_ALLOW_ANY_HOST:-0}" = "1" ] || die "tratraweb_HOST='${host}' ne ressemble pas à un hôte de staging : refus (garde-fou anti-production)" ;;
  esac
  [ "$(envval DJANGO_ENV)" = "prod" ]   || die "DJANGO_ENV doit valoir « prod » (le staging exécute les réglages de production)"
  [ "$(envval DEBUG)" = "False" ]        || die "DEBUG doit valoir False"
  [ "$(envval SENTRY_ENVIRONMENT)" != "production" ] || die "SENTRY_ENVIRONMENT ne doit pas valoir « production »"
  [ "$(envval CREATE_SUPERUSER)" != "1" ] || die "CREATE_SUPERUSER=1 interdit (mot de passe par défaut faible)"

  # Variables obligatoires restées à « CHANGE_ME » (on n'affiche que les NOMS)
  local missing; missing="$(grep -E '^[A-Za-z_][A-Za-z0-9_]*=.*CHANGE_ME' .env | cut -d= -f1 | tr '\n' ' ' || true)"
  [ -z "$missing" ] || die "variables à renseigner dans .env : ${missing}"
  local perms; perms="$(stat -c '%a' .env 2>/dev/null || stat -f '%Lp' .env)"
  case "$perms" in 600|400) ;; *) warn ".env a les droits ${perms} : exécuter chmod 600 .env" ;; esac
}

# running SERVICE : vrai si le conteneur du service tourne
running() { [ -n "$(dc ps --status running -q "$1" 2>/dev/null)" ]; }

# health SERVICE : état de santé Docker (healthy/unhealthy/starting/none)
health() {
  local id; id="$(dc ps -q "$1" 2>/dev/null | head -n1)"
  [ -n "$id" ] || { echo "absent"; return; }
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id"
}

# wait_stack : attend que l'API, les WebSocket, le worker Celery et le frontend soient « healthy » et que beat tourne (les vérifications qui suivent
# interrogent le worker et le frontend : sans cette attente elles échouent à tort pendant leur période de démarrage).
wait_stack() {
  local svc i
  for svc in tratraweb-stg tratraws-stg worker tratrafrontend-stg; do
    for i in $(seq 1 120); do
      case "$(health "$svc")" in healthy) break ;; unhealthy) die "$svc en échec de santé : docker compose -p ${PROJECT} -f ${COMPOSE_FILE} logs $svc" ;; esac
      sleep 5
    done
    [ "$(health "$svc")" = "healthy" ] || die "$svc non sain après 10 min"
  done
  for i in $(seq 1 24); do running beat && return 0; sleep 5; done
  die "beat ne tourne pas : docker compose -p ${PROJECT} -f ${COMPOSE_FILE} logs beat"
}
