# PgBouncer (mutualisation des connexions PostgreSQL) depuis les paquets Debian stables : aucune dépendance à une image tierce qui
# pourrait disparaître des registres (cf. docker/minio). Désactivé par défaut : profil Compose « pgbouncer » (docs/scalabilite-phase2.md).
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends pgbouncer postgresql-client && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /usr/local/bin/pgbouncer-entrypoint
RUN chmod 0755 /usr/local/bin/pgbouncer-entrypoint
USER postgres
EXPOSE 6432
ENTRYPOINT ["/usr/local/bin/pgbouncer-entrypoint"]
