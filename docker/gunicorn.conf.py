"""Gunicorn : sert TOUTE l'API HTTP (WSGI) ; Daphne ne sert plus que les WebSocket (/ws/, service tratraws). Voir docs/scalabilite-phase2.md.

Pourquoi : un seul processus Daphne plafonne l'API sur un cœur (mesuré : 211 req/s contre 1 289 pour 4 processus gunicorn sur le
même écran) et ne peut pas garder ses connexions PostgreSQL ouvertes. Ici, des processus (un par cœur environ) × des fils
d'exécution (`gthread` : un appel lent — Firebase, fournisseur de paiement, flux de l'assistant — n'immobilise pas tout un processus),
et des connexions PostgreSQL gardées ouvertes (DB_CONN_MAX_AGE, posé par le compose sur ce service seulement).

Réglages (environnement) : WEB_CONCURRENCY (processus, défaut 3), GUNICORN_THREADS (4), GUNICORN_TIMEOUT (120 s),
GUNICORN_MAX_REQUESTS (20 000 : recyclage progressif d'un processus, contre toute fuite mémoire), GUNICORN_ACCESS_LOG (true)."""
import os

bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
workers = max(1, int(os.getenv("WEB_CONCURRENCY", "3")))
worker_class = "gthread"
threads = max(1, int(os.getenv("GUNICORN_THREADS", "4")))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))          # au-delà des délais des appels sortants (IA 30 s, paiement 10 s)
graceful_timeout = 30                                         # redémarrage : les requêtes en cours se terminent
keepalive = 5                                                 # derrière Traefik (connexions réutilisées)
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "20000"))   # mesuré : 2 000 recyclait un processus toutes les 3 s à 700 req/s
max_requests_jitter = max_requests // 10                      # pas de redémarrage simultané de tous les processus
forwarded_allow_ips = "*"                                     # seul Traefik (réseau interne) joint ce port ; Django lit lui-même X-Forwarded-*
accesslog = "-" if os.getenv("GUNICORN_ACCESS_LOG", "true").lower() in ("1", "true", "yes", "on") else None
errorlog = "-"
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None   # battements des processus hors du disque (Docker)
