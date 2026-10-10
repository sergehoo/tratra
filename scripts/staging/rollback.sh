#!/usr/bin/env bash
# Retour arrière du STAGING : restaure la base prise par backup.sh avant le déploiement, réétiquette les images
# précédentes (rollback-<horodatage>) puis relance la pile SANS reconstruire.
# Usage : scripts/staging/rollback.sh backups/<horodatage> [--with-objects] [--yes]
#   (backups/LAST contient la dernière sauvegarde : scripts/staging/rollback.sh "$(cat backups/LAST)")
# Ne touche JAMAIS à la production : il n'agit que sur le projet « tratra-staging ».
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
guard

DIR="${1:-}"
[ -n "$DIR" ] && [ -f "${DIR}/manifest.txt" ] || die "usage : rollback.sh backups/<horodatage> [--with-objects] [--yes]"
TS="$(basename "$DIR")"
TAG="$(envval IMAGE_TAG)"; TAG="${TAG:-staging}"

say "Rollback vers la sauvegarde ${TS}"
sed -n '1,4p' "${DIR}/manifest.txt"

# 1) Base (et objets) : arrête aussi les applications
if [ -s "${DIR}/db.dump" ]; then
  "$STAGING_SCRIPTS/restore.sh" "$@"
else
  warn "aucun dump dans ${DIR} (sauvegarde du premier déploiement) : base non restaurée"
  dc stop tratrafrontend-stg beat worker tratraweb-stg >/dev/null 2>&1 || true
fi

# 2) Images précédentes
for img in tratra-backend tratra-frontend; do
  if docker image inspect "${img}:rollback-${TS}" >/dev/null 2>&1; then
    docker tag "${img}:rollback-${TS}" "${img}:${TAG}"
    ok "${img}:${TAG} <- ${img}:rollback-${TS}"
  else
    warn "${img}:rollback-${TS} introuvable : l'image actuelle est conservée"
  fi
done

# 3) Relance sans construction (l'entrypoint rejoue « migrate » : sans effet sur une base restaurée)
say "Relance de la pile"
dc up -d --no-build --remove-orphans

say "Attente de la santé de l'API (jusqu'à 10 min)"
for _ in $(seq 1 120); do
  [ "$(health tratraweb-stg)" = "healthy" ] && break
  sleep 5
done
[ "$(health tratraweb-stg)" = "healthy" ] || die "l'API n'est pas saine après rollback : voir « docker compose -p ${PROJECT} -f ${COMPOSE_FILE} logs tratraweb-stg »"

"$STAGING_SCRIPTS/verify.sh"
ok "rollback terminé"
