#!/usr/bin/env bash
# Déploiement du STAGING : sauvegarde → construction → démarrage → attente de santé → vérifications.
# À lancer manuellement sur le serveur de staging, dans le dépôt (révision à déployer déjà extraite).
# Jamais automatique, jamais en production. En cas d'échec, AUCUN retour arrière automatique : le script affiche la
# commande rollback.sh à lancer.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
guard
HERE="$STAGING_SCRIPTS"

say "Révision : $(git rev-parse --short HEAD 2>/dev/null || echo inconnue)$( [ -n "$(git status --porcelain 2>/dev/null)" ] && echo ' (modifications locales non commitées !)' )"
docker network inspect "$(envval PROXY_NETWORK | sed 's/^$/proxy/')" >/dev/null 2>&1 \
  || die "réseau Traefik introuvable : docker network create proxy (celui de votre Traefik)"
dc config -q || die "docker-compose.staging.yml invalide"

say "1/5 Sauvegarde préalable"
"$HERE/backup.sh" | tee /tmp/tratra-staging-backup.log
BACKUP="$(sed -n 's/^BACKUP=//p' /tmp/tratra-staging-backup.log | tail -n1)"; BACKUP="${BACKUP:-$(cat backups/LAST 2>/dev/null || true)}"

fail() {
  printf '\n'; warn "ÉCHEC du déploiement à l'étape : $1"
  [ -z "$BACKUP" ] || warn "Retour arrière : scripts/staging/rollback.sh ${BACKUP} --with-objects"
  exit 1
}

say "2/5 Construction des images (backend + frontend)"
dc build --pull tratraweb-stg tratrafrontend-stg || fail "construction"

say "3/5 Démarrage (migrations appliquées par l'entrypoint de l'API)"
dc up -d --remove-orphans || fail "démarrage"

say "4/5 Attente de la santé de l'API (jusqu'à 10 min : migrations, collectstatic)"
for _ in $(seq 1 120); do
  case "$(health tratraweb-stg)" in healthy) break ;; unhealthy) fail "API en échec de santé" ;; esac
  sleep 5
done
[ "$(health tratraweb-stg)" = "healthy" ] || fail "API non saine après 10 min"

say "5/5 Vérifications"
"$HERE/verify.sh" || fail "vérifications"
ok "Staging déployé. Sauvegarde de référence : ${BACKUP:-aucune}"
