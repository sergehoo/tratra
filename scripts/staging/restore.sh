#!/usr/bin/env bash
# Restaure la base de STAGING depuis une sauvegarde (et, avec --with-objects, les objets MinIO).
# DESTRUCTIF pour le staging : la base est supprimée puis recréée. Confirmation obligatoire (taper « tratra-staging »).
# Usage : scripts/staging/restore.sh backups/<horodatage> [--with-objects] [--yes]
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
guard

DIR="${1:-}"; shift || true
WITH_OBJECTS=0; ASSUME_YES=0
for a in "$@"; do case "$a" in --with-objects) WITH_OBJECTS=1 ;; --yes) ASSUME_YES=1 ;; *) die "option inconnue : $a" ;; esac; done
[ -n "$DIR" ] && [ -s "${DIR}/db.dump" ] || die "usage : restore.sh backups/<horodatage> [--with-objects] [--yes]"

if command -v sha256sum >/dev/null; then (cd "$DIR" && sha256sum -c db.dump.sha256 >/dev/null) || die "empreinte du dump invalide"
else (cd "$DIR" && shasum -a 256 -c db.dump.sha256 >/dev/null) || die "empreinte du dump invalide"; fi

if [ "$ASSUME_YES" != "1" ]; then
  printf 'Supprimer et recréer la base du projet %s depuis %s ? Tapez « %s » pour confirmer : ' "$PROJECT" "$DIR" "$PROJECT"
  read -r answer; [ "$answer" = "$PROJECT" ] || die "annulé"
fi

DB_USER="$(envval DB_USER)"; DB_NAME="$(envval DB_NAME)"
running tratradb || dc up -d tratradb
until [ "$(health tratradb)" = "healthy" ]; do sleep 2; done

say "Arrêt des applications (web, worker, beat, frontend)"
dc stop tratrafrontend-stg beat worker tratraweb-stg >/dev/null 2>&1 || true

say "Recréation de la base ${DB_NAME}"
dc exec -T tratradb psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" \
  -c "DROP DATABASE IF EXISTS \"${DB_NAME}\";" \
  -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";" > /dev/null

say "Restauration ${DIR}/db.dump"
dc exec -T tratradb pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges < "${DIR}/db.dump" \
  || warn "pg_restore a signalé des avertissements (messages « existe déjà » sans gravité) : vérifier avec verify.sh"
ok "base restaurée"

if [ "$WITH_OBJECTS" = "1" ] && [ -d "${DIR}/minio" ]; then
  say "Restauration des objets MinIO (les objets absents de la sauvegarde sont supprimés)"
  running minio-stg || dc up -d minio-stg
  dc run --rm --no-deps -v "$PWD/${DIR}/minio:/backup:ro" --entrypoint /bin/sh minio-init -ec \
    'mc alias set local http://minio-stg:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mirror --quiet --overwrite --remove /backup local'
  ok "objets restaurés"
fi
say "Applications arrêtées : les relancer avec « docker compose -p ${PROJECT} -f ${COMPOSE_FILE} up -d --no-build » (ou rollback.sh)."
