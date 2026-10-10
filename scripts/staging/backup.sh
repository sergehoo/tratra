#!/usr/bin/env bash
# Sauvegarde AVANT déploiement : base PostgreSQL (dump compressé), objets MinIO, instantané des images (étiquette
# rollback-<horodatage>) et manifeste (révision git, dernière migration par application).
# Usage : scripts/staging/backup.sh          → crée backups/<horodatage>/  (droits 700, jamais versionné)
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
guard

TS="$(date +%Y%m%d-%H%M%S)"
DIR="backups/${TS}"
umask 077
mkdir -p "$DIR"

DB_USER="$(envval DB_USER)"; DB_NAME="$(envval DB_NAME)"

if ! running tratradb; then
  warn "base de staging arrêtée : premier déploiement ? Rien à sauvegarder (dossier ${DIR} vide)."
  echo "$DIR" > backups/LAST
  exit 0
fi

say "1/4 Dump PostgreSQL ${DB_NAME} → ${DIR}/db.dump"
dc exec -T tratradb pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc --no-owner > "${DIR}/db.dump"
[ -s "${DIR}/db.dump" ] || die "dump vide"
dc exec -T tratradb pg_restore --list < "${DIR}/db.dump" > /dev/null || die "dump illisible (pg_restore --list a échoué)"
ok "dump valide ($(wc -c < "${DIR}/db.dump" | tr -d ' ') octets)"

say "2/4 Objets MinIO → ${DIR}/minio"
if running minio-stg; then
  mkdir -p "${DIR}/minio"
  dc run --rm --no-deps -v "$PWD/${DIR}/minio:/backup" --entrypoint /bin/sh minio-init -ec \
    'mc alias set local http://minio-stg:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mirror --quiet --overwrite local /backup' \
    && ok "objets copiés" || warn "copie MinIO incomplète"
else
  warn "MinIO arrêté : objets non sauvegardés"
fi

say "3/4 Instantané des images (rollback-${TS})"
: > "${DIR}/images.txt"
for img in tratra-backend tratra-frontend; do
  tag="$(envval IMAGE_TAG)"; tag="${tag:-staging}"
  if docker image inspect "${img}:${tag}" >/dev/null 2>&1; then
    docker tag "${img}:${tag}" "${img}:rollback-${TS}"
    echo "${img}:rollback-${TS} <- ${img}:${tag} ($(docker image inspect -f '{{.Id}}' "${img}:${tag}"))" >> "${DIR}/images.txt"
    ok "${img}:rollback-${TS}"
  else
    warn "${img}:${tag} absente (première construction ?)"
  fi
done

say "4/4 Manifeste"
{
  echo "date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git=$(git rev-parse HEAD 2>/dev/null || echo inconnu)"
  echo "project=${PROJECT}"
  echo "image_tag=$(envval IMAGE_TAG)"
  echo "--- dernière migration appliquée par application :"
  dc exec -T tratradb psql -U "$DB_USER" -d "$DB_NAME" -Atc "SELECT app || ' ' || max(name) FROM django_migrations GROUP BY app ORDER BY app" 2>/dev/null || echo "(indisponible)"
} > "${DIR}/manifest.txt"
if command -v sha256sum >/dev/null; then (cd "$DIR" && sha256sum db.dump > db.dump.sha256); else (cd "$DIR" && shasum -a 256 db.dump > db.dump.sha256); fi

echo "$DIR" > backups/LAST
ok "sauvegarde terminée : ${DIR}"
echo "BACKUP=${DIR}"
