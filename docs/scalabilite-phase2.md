# Tratra — scalabilité, phase 2

Suite de [scalabilite-30m.md](scalabilite-30m.md). Les optimisations de la phase 1 sont conservées (Smart Dispatch à coût constant,
annonces par lots, préfiltre spatial, rayon plafonné). Cette phase lève les goulots restants sans refonte ni microservices.
Rien n'est poussé ni déployé ; aucun SMS ni push réel n'a été émis.

## 1. Ce qui change

| # | Changement | Fichiers | Effet |
|---|---|---|---|
| 1 | HTTP servi par **gunicorn** (WSGI, processus × fils `gthread`, connexions PostgreSQL gardées ouvertes) ; **Daphne** ne sert plus que `/ws/` (service `tratraws`, routeur Traefik prioritaire sur le même hôte) | `docker-compose*.yml`, `docker/gunicorn.conf.py`, `tratra/settings/prod.py` | L'API n'est plus plafonnée à un cœur ; les WebSocket et leur authentification (billets signés délivrés par l'API) sont inchangées |
| 2 | **Éligibilité pré-calculée** : `HandymanProfile.published` (indexée), recalculée **dans la transaction** de chaque changement (KYC, spécialités, offres, métier, compte, validation), réconciliée toutes les 15 min et au démarrage | `handy/eligibility.py`, `handy/eligibility_sync.py`, migration 0060, commande `eligibility_sync` | La recherche publique, le Smart Dispatch et les listes ne recalculent plus la règle sur tout le pays |
| 3 | **« Près de moi »** : tri « plus proches voisins » par l'index `geography(location)` (même distance que le tri précédent), total **plafonné** à 1 000 (`count_capped`) | `handy/proximity.py`, `handy/api/views.py`, migration 0061, `frontend` (« Plus de 1 000 offres ») | Plus de comptage exhaustif ni de tri de toutes les offres du rayon |
| 4 | **PgBouncer** et **Redis séparés** prêts, **désactivés** (profils Compose) ; réglages par variables (`CELERY_BROKER_URL`, `CHANNELS_REDIS_URL`, `DB_CONN_MAX_AGE`, `DB_DISABLE_SERVER_SIDE_CURSORS`) ; résultats Celery non stockés | `docker/pgbouncer/`, `docker-compose.yml`, `tratra/settings/*.py` | Infrastructure de production inchangée tant que rien n'est activé |
| 5 | **Rétention des notifications** configurable (désactivée par défaut), purge par lots bornés, catégories protégées (paiements, compte, engagements), push non envoyés jamais purgés | `handy/notifications.py`, commande `notifications_purge`, tâche quotidienne | La plus grosse table cesse de croître sans limite quand l'exploitant choisit une durée |
| 6 | **Celery** : files `flash`, `otp`, `default`, `bulk` avec **routage explicite** et **un worker par file** ; push réservé atomiquement (`queued → sending`) ; fermeture des alertes Flash hors de la requête | `tratra/settings/base.py`, `handy/notifications.py`, `handy/tasks.py`, `flash/*` | Une alerte de mission ne peut plus attendre derrière une annonce ou une purge ; un push n'est jamais envoyé deux fois |
| 7 | **Plafonds SMS anti-fraude inchangés** ; aucun relèvement automatique (test : valeurs par défaut figées, aucun code ne les modifie) | `handy/test_scalability_phase2.py` | — |

## 2. Mesures avant / après

Mêmes données (base jetable de 200 000 comptes, 20 000 professionnels, 50 728 offres, 1 M de notifications), mêmes scénarios, tirs
« avant » et « après » enchaînés. Avant = code de la phase 1 servi comme en production (Daphne, 1 processus) ; après = phase 2
(gunicorn 3 processus × 4 fils, configuration `docker/gunicorn.conf.py`). Limites : § 6.

**HTTP — 16 utilisateurs simultanés, 15 s par tir**

| Scénario | Débit avant → après | p95 avant → après | p99 avant → après | CPU serveur par requête | Lignes SQL lues par requête | Erreurs |
|---|---|---|---|---|---|---|
| Mélange réaliste (recherche, notifications, tableaux de bord, Flash…) | 19,3 → **37,5 req/s** | 3 253 → **1 362 ms** | 3 937 → **2 300 ms** | — | 308 440 → **133 486** | 0 / 0 |
| « Près de moi » 10 km | 7,8 → **16,5 req/s** | 3 734 → **1 730 ms** | 4 128 → **2 072 ms** | — | 1 232 569 → **367 455** | 0 / 0 |
| Catalogue | 193 → **778 req/s** | 141 → **45 ms** | 238 → **85 ms** | 7,5 → **3,2 ms** | — | 0 / 0 |
| Notifications (authentifié) | 142 → **477 req/s** | 182 → **69 ms** | 221 → **159 ms** | 9,7 → **5,5 ms** | — | 0 / 0 |

Mémoire mesurée : Daphne (tout le HTTP) 292 Mo → gunicorn 3 processus ≈ 460 Mo + Daphne WebSocket seul ≈ 194 Mo ; un worker Celery
dédié de concurrence 2 ≈ 205 Mo (quatre workers ≈ 0,8 Go). Prévoir **≈ +1 Go** de mémoire sur le serveur par rapport à aujourd'hui.
WebSocket après séparation : **1 000 connexions sur 1 000** ouvertes avec des billets délivrés par gunicorn (p95 d'ouverture 1,2 s).

**Dans le processus (médiane, 5 appels)**

| Écran | Avant | Après |
|---|---|---|
| Liste des services d'un métier | 245 ms (SQL 203 ms) | **38 ms** (SQL 22 ms) |
| Services proches 10 km | 243 ms | **115 ms** |
| Services proches 10 km, métier le plus fourni | 163 ms | **91 ms** |
| Fiche publique d'un professionnel | 8,6 ms | 4,7 ms |
| Flash : choisir son pro | 715 ms | 631 ms |
| Une vague Smart Dispatch (plomberie, Abidjan) | 1 036 ms | 967 ms |

Le reste (notifications, messages, tableaux de bord) ne dépend pas de l'éligibilité : écarts dans le bruit de la machine (§ 6).
Gestion de gunicorn : avec un recyclage à 2 000 requêtes, chaque processus redémarrait toutes les 3 s à 700 req/s (3 connexions
coupées) : la valeur par défaut est passée à 20 000 (aucune erreur ensuite).

## 3. Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `WEB_CONCURRENCY` | 3 | Processus gunicorn (≈ cœurs disponibles ; à ajuster par la mesure sur le serveur) |
| `GUNICORN_THREADS` | 4 | Fils par processus (appels lents : paiement, Firebase, assistant) |
| `GUNICORN_TIMEOUT` / `GUNICORN_MAX_REQUESTS` | 120 s / 20 000 | Délai d'une requête ; recyclage progressif des processus |
| `WEB_DB_CONN_MAX_AGE` | 60 | Connexions PostgreSQL gardées ouvertes par l'API (Daphne : toujours 0) |
| `CELERY_DEFAULT_CONCURRENCY` / `CELERY_FLASH_CONCURRENCY` / `CELERY_OTP_CONCURRENCY` / `CELERY_BULK_CONCURRENCY` | 2 / 2 / 1 / 2 | Concurrence de chaque worker dédié |
| `CELERY_TASK_IGNORE_RESULT` | true | Résultats de tâches non stockés (aucun appelant ne les lit) |
| `NOTIFICATION_RETENTION_DAYS` | 0 (désactivée) | Durée de conservation des notifications **lues** |
| `NOTIFICATION_UNREAD_RETENTION_DAYS` | 0 (jamais) | Durée de conservation des notifications **non lues** |
| `NOTIFICATION_RETENTION_PROTECTED_CATEGORIES` | payment,account,engagement | Jamais purgées |
| `NOTIFICATION_PURGE_BATCH` / `NOTIFICATION_PURGE_MAX_BATCHES` | 5 000 / 200 | Taille d'un lot ; lots par passage (1 M de lignes au plus par jour) |
| `CELERY_BROKER_URL`, `CHANNELS_REDIS_URL` (+ `CACHE_URL` existant) | vides | Redis séparés (profil `redis-split`) ; vides = Redis commun actuel |
| `DB_DISABLE_SERVER_SIDE_CURSORS` | false | `true` obligatoire derrière PgBouncer en mode transaction |

## 4. Procédure de déploiement (production)

Prérequis : sauvegarde de la base (`pg_dump`) et des images actuelles ; fenêtre calme (quelques secondes de coupure des WebSocket).

1. Récupérer le code, puis construire **une seule** image backend (réutilisée par l'API, les WebSocket, les workers et beat) et le
   site : `docker compose build tratraweb tratrafrontend`.
2. `docker compose up -d --remove-orphans` :
   - `tratraweb` démarre sous gunicorn, applique les migrations 0060-0061 (colonne `published` calculée, index géographique) puis
     `eligibility_sync` ;
   - `tratraws` (Daphne) démarre ensuite (attend la bonne santé de l'API) ; Traefik lui envoie `/ws/` ;
   - `worker`, `worker-flash`, `worker-otp`, `worker-bulk` et `beat` sont recréés sur la nouvelle image.
3. Vérifications :
   - `docker compose exec tratraweb python manage.py eligibility_sync --check` (aucun écart) ;
   - `docker compose exec tratraweb python manage.py celery_check --db` ;
   - `docker compose exec worker celery -A tratra inspect active_queues` (chaque file a son worker) ;
   - `python3 scripts/staging/ws_check.py --api https://api.tratra.net/handy` (WebSocket : 403 sans billet, donc routé vers Daphne) ;
   - une connexion et une conversation dans l'application (temps réel).
4. Rétention : laisser `NOTIFICATION_RETENTION_DAYS=0` ; plus tard, `manage.py notifications_purge --dry-run --days 180` puis choisir.

**Retour arrière** : revenir au commit précédent puis `docker compose up -d --build --remove-orphans`. Les migrations 0060-0061 sont
additives (une colonne et un index ignorés par l'ancien code) : aucun retour de migration n'est nécessaire.

**Activer PgBouncer** (plus tard, sur mesure) : `docker compose --profile pgbouncer up -d pgbouncer`, puis pour l'API et les workers
`DB_HOST=pgbouncer`, `DB_PORT=6432`, `DB_DISABLE_SERVER_SIDE_CURSORS=true` ; garder les migrations sur PostgreSQL direct
(`docker compose exec -e DB_HOST=tratradb -e DB_PORT=5432 tratraweb python manage.py migrate`). Le fuseau du serveur PostgreSQL
doit rester UTC.

**Séparer Redis** (plus tard) : `docker compose --profile redis-split up -d`, puis `CELERY_BROKER_URL=redis://redis-broker:6379/0`,
`CACHE_URL=redis://redis-cache:6379/0`, `CHANNELS_REDIS_URL=redis://redis-channels:6379/0` et redémarrer l'API, les WebSocket et les
workers. Les files en cours sur l'ancien Redis sont à vider avant (ou rejouées par les tâches périodiques).

## 5. Risques et parades

| Risque | Parade |
|---|---|
| Copie `published` en retard après une écriture en masse sans signal | Gardes directes (compte désactivé, validation retirée : effet immédiat) ; réservation et acceptation Flash revérifient la règle complète ; réconciliation 15 min et au démarrage ; `eligibility_sync --check` |
| Mémoire : un service WebSocket et trois workers de plus | Concurrences basses par défaut, réglables ; à mesurer sur le serveur avant d'augmenter `WEB_CONCURRENCY` |
| Routage `/ws/` | Routeur dédié de priorité 100 ; `ws_check.py` le vérifie (403 sans billet) |
| Total « près de moi » plafonné | `count` ≤ 1 000 et `count_capped` ; le site affiche « Plus de 1 000 offres » ; l'application n'utilise que `results` |
| Push réservé puis worker arrêté net | La notification reste « sending » (aucun double envoi ; au pire pas de push, l'historique in-app reste) |
| Purge de données | Désactivée par défaut, aperçu `--dry-run`, catégories protégées, livraisons d'annonces conservées |

## 6. Protocole de mesure et limites

- Banc : `scripts/loadtest/run_local.sh` (base jetable `tratra_loadtest`, Redis dédié, aucun SMS ni push), avec désormais par tir :
  débit, p50/p95/p99, erreurs, CPU du serveur (temps CPU cumulé de ses processus), CPU de la machine (`iostat`), mémoire du serveur
  (empreinte physique, pic), activité SQL (`pg_stat_database` : transactions/s, lignes lues par requête, taux de cache) — une ligne
  JSON par tir dans `loadtest-results/runs.jsonl` (`probe.py`).
- Avant : code de la phase 1 figé dans un worktree Git ; après : code courant. Même base (la colonne `published` et l'index ajoutés
  par la phase 2 sont ignorés par l'ancien code).
- **Limites** : machine de développement (Apple M3, 8 Go) avec PostgreSQL x86 sous Rosetta, générateur sur la même machine, et une
  machine virtuelle Docker tierce occupant la mémoire (jusqu'à 10 Go de mémoire d'échange utilisés) : un premier tir « avant » a
  dû être annulé (requêtes bloquées), et les écarts de quelques millisecondes sont du bruit. Les rapports avant/après sont
  significatifs ; les valeurs absolues ne sont PAS des capacités de production.
- Commandes :
  `LABEL=avant SERVERS=daphne SCENARIOS="mix nearby catalog notifications" CONCURRENCY=16 DURATION=15 scripts/loadtest/run_local.sh http`
  puis `LABEL=après SERVERS=gunicorn GUNICORN_CONF=docker/gunicorn.conf.py WEB_CONCURRENCY=3 GUNICORN_THREADS=4 … run_local.sh http`.
