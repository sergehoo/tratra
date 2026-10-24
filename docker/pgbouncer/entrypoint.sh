#!/bin/sh
# Configuration de PgBouncer générée au démarrage depuis l'environnement (aucun secret dans l'image ni dans Git).
#   PGB_DB_HOST / PGB_DB_PORT        serveur PostgreSQL réel (défaut tratradb:5432)
#   DB_NAME / DB_USER / DB_PASSWORD  mêmes valeurs que Django (le mot de passe ne sort jamais du conteneur)
#   PGB_POOL_MODE                    transaction (défaut ; exige DB_DISABLE_SERVER_SIDE_CURSORS=true côté Django) | session
#   PGB_DEFAULT_POOL_SIZE            connexions PostgreSQL par base/utilisateur (défaut 20)
#   PGB_MAX_CLIENT_CONN              connexions clientes acceptées (défaut 500)
set -eu
: "${DB_NAME:?DB_NAME requis}" "${DB_USER:?DB_USER requis}" "${DB_PASSWORD:?DB_PASSWORD requis}"
CONF=/tmp/pgbouncer
mkdir -p "$CONF"
umask 077
printf '"%s" "%s"\n' "$DB_USER" "$DB_PASSWORD" > "$CONF/userlist.txt"
cat > "$CONF/pgbouncer.ini" <<EOF
[databases]
${DB_NAME} = host=${PGB_DB_HOST:-tratradb} port=${PGB_DB_PORT:-5432} dbname=${DB_NAME}

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
unix_socket_dir =
auth_type = scram-sha-256
auth_file = ${CONF}/userlist.txt
pool_mode = ${PGB_POOL_MODE:-transaction}
default_pool_size = ${PGB_DEFAULT_POOL_SIZE:-20}
reserve_pool_size = 5
max_client_conn = ${PGB_MAX_CLIENT_CONN:-500}
server_reset_query = DISCARD ALL
ignore_startup_parameters = extra_float_digits,options
log_connections = 0
log_disconnections = 0
EOF
exec pgbouncer "$CONF/pgbouncer.ini"
