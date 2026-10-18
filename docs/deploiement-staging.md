# Déploiement du staging Tratra

Procédure exécutable, vérifiée localement (voir « Ce qui a été vérifié »). **Rien ici ne touche la production** : le staging est
un projet Compose distinct (`tratra-staging`) avec sa propre base PostgreSQL/PostGIS, son Redis et son MinIO, des noms Traefik
préfixés `tratra-stg-` et des services en `-stg` sur le réseau `proxy` partagé. Les scripts refusent de tourner si `.env` ne
décrit pas un hôte de staging.

## 0. Existant identifié

| Élément | Fichier | Remarque |
|---|---|---|
| Image API | `Dockerfile` (Python 3.12, GDAL/GEOS/PROJ, utilisateur 10001) | `CMD` = `entrypoint.sh daphne …` |
| Pile production | `docker-compose.yml` | PostGIS 16, Redis 7, MinIO, Daphne, Next.js, Celery worker + beat, Adminer ; **Traefik externe**, réseau externe `proxy`, résolveur `lets` |
| Entrypoint | `entrypoint.sh` | attend db/redis, `check --deploy`, `migrate`, `collectstatic`, puis Daphne (HTTP **et** WebSocket `/ws/`) |
| Sondes | `/healthz`, `/readyz` (base + Redis) | |
| Dokploy | **aucun fichier ni référence dans le dépôt** | la pile est un Compose + Traefik standard : utilisable comme service « Compose » Dokploy (§ 6) |
| Staging (ajouté) | `docker-compose.staging.yml`, `.env.staging.example`, `scripts/staging/*` | non appliqué, aucun déploiement lancé |

### Défauts de déploiement trouvés (et traités)

1. **Celery** : les tâches partaient dans la file `celery` alors que le worker du compose n'écoute que `default,notifications` →
   aucune tâche ne s'exécutait (notifications, push FCM, réévaluation des badges, purge GPS). Corrigé : `CELERY_TASK_DEFAULT_QUEUE='default'`
   (`tratra/settings/base.py`) ; le worker staging écoute aussi `celery` (producteurs d'une ancienne version).
2. **Sonde de santé du compose de production** : `wget http://127.0.0.1:8000/readyz` reçoit **400** (hôte refusé) puis **301**
   (redirection HTTPS) → conteneur jamais « healthy ». Le compose staging présente l'hôte public et `X-Forwarded-Proto: https`.
   (Le compose de production n'a pas été modifié.)
3. **`PUBLIC_WEB_URL`** valait `http://localhost:3000` par défaut : QR Tratra ID / mission / équipements inutilisables. `prod.py`
   exige désormais une URL HTTPS explicite.
4. **CI** : le contrôle « Production settings check » échouait déjà (SMS) ; variables ajoutées (`PUBLIC_WEB_URL`, `SMS_BACKEND`, `AT_*`).
5. `asgi.py` n'attache la pile WebSocket qu'en `try/except` silencieux : un import cassé laisserait l'HTTP fonctionner sans WebSocket.
   `verify.sh` contrôle `ASGI=http,websocket` et le refus 403 sans billet.
6. **L'image API ne se construisait plus** : `python:3.12-bullseye` (Debian 11) n'est plus maintenue ; son miroir de sécurité répond 404 aux `apt-get install`
   (constaté le 10 oct. 2026). Corrigé : `python:3.12-bookworm` (+ test `test_images_are_built_on_a_supported_debian_release`).
   **Le compose de production utilise le même Dockerfile** : toute reconstruction d'image y échouait aussi.
7. **MinIO n'est plus téléchargeable** : `minio/minio` et `minio/mc` (Docker Hub) et `quay.io/minio/*` répondent « pull access denied » (distribution communautaire
   passée aux sources seules). Un serveur neuf ou la CI ne pouvaient plus démarrer la pile. Corrigé pour le staging : `docker/minio/Dockerfile` construit les MÊMES versions
   épinglées depuis les sources (`go install`, intégrité vérifiée par `sum.golang.org`) ; serveur et client `mc` dans une image `tratra-minio`. Le compose de **production** utilise la même image construite
   (le serveur réel avait échoué sur `docker compose up --build` : « pull access denied for minio/mc »).
8. **`makemigrations --check` échouait dans l'image** : l'application inutilisée `django-push-notifications` (migrations en `AutoField`, projet en `BigAutoField`) faisait
   détecter un changement à écrire « dans le paquet installé ». Retirée (le push passe par `handy/push.py`, FCM v1).
9. **Faux échecs de `verify.sh`** : `cmd | grep -q` sous `pipefail` (SIGPIPE) et vérifications lancées avant la fin du démarrage du worker/frontend. Corrigé (sorties capturées,
   `wait_stack` dans `deploy.sh` et `rollback.sh`).
10. **Traefik < 3.6 incompatible avec Docker ≥ 29** (API minimale 1.40) : le fournisseur Docker échoue (« Error response from daemon »). Utiliser Traefik ≥ 3.6 si le serveur a Docker 29.

## 1. Pré-requis serveur (une fois)

```bash
# DNS : 3 enregistrements A/AAAA vers le serveur de staging (api, app, minio) — console MinIO et Adminer ne sont jamais exposés
docker network ls | grep -w proxy        # DOIT exister (réseau de votre Traefik). Ne pas le recréer.
docker compose version                    # Compose v2
# Traefik : entrypoint « websecure » et résolveur « lets » (comme en production) ; Traefik gère les WebSocket nativement.
```

## 2. Obtenir le code sur le serveur (sans publier la branche)

```bash
# Depuis le poste de développement (révision à déployer = HEAD), sans git push :
git archive --format=tar.gz --prefix=tratra-staging/ HEAD | ssh <serveur-staging> 'tar -xz -C ~'
ssh <serveur-staging>
cd ~/tratra-staging
```
Variante : `git clone … && git checkout <branche-ou-tag>` une fois la branche poussée (hors périmètre de cette préparation).

## 3. Variables d'environnement

```bash
cp .env.staging.example .env && chmod 600 .env
# Secrets aléatoires (écrits dans .env sans les afficher) :
for k in SECRET_KEY DB_PASSWORD MINIO_ROOT_PASSWORD AWS_SECRET_ACCESS_KEY STRIPE_WEBHOOK_SECRET PAYMENT_WEBHOOK_SECRET \
         PAYMENT_OM_WEBHOOK_SECRET PAYMENT_MTN_WEBHOOK_SECRET PAYMENT_CARD_WEBHOOK_SECRET; do
  sed -i "s|^${k}=.*|${k}=$(openssl rand -base64 60 | tr -d '\n=/+')|" .env
done
sed -i "s|^MINIO_ROOT_USER=.*|MINIO_ROOT_USER=stg$(openssl rand -hex 4)|" .env
sed -i "s|^AWS_ACCESS_KEY_ID=.*|AWS_ACCESS_KEY_ID=$(sed -n 's/^MINIO_ROOT_USER=//p' .env)|" .env
sed -i "s|^AWS_SECRET_ACCESS_KEY=.*|AWS_SECRET_ACCESS_KEY=$(sed -n 's/^MINIO_ROOT_PASSWORD=//p' .env)|" .env
# À renseigner à la main : hôtes (tous les « example.com »), SMS_BACKEND + identifiants, SMTP (EMAIL_*), SENTRY_DSN (facultatif)
grep -nE 'CHANGE_ME|example\.com' .env | cut -d= -f1       # reste à faire (noms seulement)
```
Rappels : `ALLOWED_HOSTS` doit contenir l'hôte de l'API (la sonde de santé l'utilise) ; `PUBLIC_WEB_URL` = URL HTTPS du frontend staging ;
buckets média et KYC **distincts** ; `CREATE_SUPERUSER` reste à `0` ; l'OTP n'est jamais contourné (SMS réel ou bac à sable).

## 4. Firebase FCM (facultatif au premier démarrage : sans fichier, aucun push, aucune erreur)

1. Console Firebase → projet (recommandé : un projet dédié au staging) → application Android `com.tratra`.
2. Google Cloud → activer « Firebase Cloud Messaging API (V1) ».
3. Paramètres du projet → Comptes de service → **Générer une nouvelle clé privée** (JSON).
4. Sur le serveur :
   ```bash
   mkdir -p secrets && sudo chown 10001:10001 secrets && sudo chmod 500 secrets
   scp fcm-service-account.json <serveur-staging>:/tmp/ && sudo install -o 10001 -g 10001 -m 400 /tmp/fcm-service-account.json secrets/ && shred -u /tmp/fcm-service-account.json
   sed -i 's|^FCM_CREDENTIALS_FILE=.*|FCM_CREDENTIALS_FILE=/run/tratra-secrets/fcm-service-account.json|' .env
   docker compose -p tratra-staging -f docker-compose.staging.yml up -d tratraweb-stg worker      # recharge l'environnement
   docker compose -p tratra-staging -f docker-compose.staging.yml exec tratraweb-stg python manage.py shell -c "from handy import push; print(push.is_configured())"   # True
   ```
5. APK : `android/app/google-services.json` du **même** projet Firebase (package `com.tratra`) — fichier hors Git.
6. Test réel : connecter l'app (qui enregistre l'appareil via `POST /handy/devices/`), puis
   `… exec tratraweb-stg python manage.py shell -c "from handy import push; print(push.send_to_user(<ID_UTILISATEUR>, 'Test staging', 'Notification de test', {'t': 'test'}))"` → `{'sent': 1, 'removed': 0, …}`.

## 5. Déploiement

```bash
scripts/staging/deploy.sh      # sauvegarde → build → up → attente de santé → vérifications ; n'effectue AUCUN rollback automatique
```
Équivalent manuel :
```bash
export DC="docker compose -p tratra-staging -f docker-compose.staging.yml"
$DC config -q
scripts/staging/backup.sh
$DC build --pull tratraweb-stg tratrafrontend-stg
$DC up -d --remove-orphans
$DC logs -f tratraweb-stg            # attendre « Démarrage du process application »
```
Première mise en service uniquement :
```bash
$DC exec tratraweb-stg python manage.py createsuperuser      # mot de passe fort, saisi interactivement
```
Comptes de recette : inscription par l'API/l'application, puis approbation du KYC dans `/admin/` (le KYC reste humain).

## 6. Dokploy (variante)

Projet → *Create Service* → **Compose** → source Git (ou archive), **Compose Path** `./docker-compose.staging.yml`,
onglet *Environment* : coller le contenu de `.env.staging.example` complété (Dokploy l'écrit en `.env`, lu par le compose).
*Domains* : inutile (routage par labels Traefik). Réseau `proxy` : celui de Traefik. Déployer ; rollback = redéployer la révision précédente
(ou `scripts/staging/rollback.sh` en SSH).

## 7. Vérification

Avant le serveur : répéter toute la procédure en local (`scripts/staging/rehearsal.sh up|admins|recette|drill|down`, voir `docs/pilote.md`).

```bash
scripts/staging/verify.sh                                   # conteneurs, TLS, 19 routes, WebSocket, ASGI, migrations, Celery/Beat (CHAQUE tâche planifiée, lue dans les settings), Redis, MinIO, FCM
python3 scripts/staging/ws_check.py --api https://api-staging.example.com/handy          # WebSocket : 403 sans billet
TRATRA_TOKEN=<jeton d'accès d'un participant> python3 scripts/staging/ws_check.py --api https://api-staging.example.com/handy --booking <ID>   # 101 + état + pong
```
Compatibilité Flutter Android : API en HTTPS (le build release n'autorise pas le HTTP), WebSocket `wss://<hôte API>/ws/live/<id>/?ticket=…`
(chemin absolu fourni par le serveur), `POST /handy/devices/` présent (401 sans jeton), `minSdk` 24, aucun CORS requis (application native).

APK de staging :
```bash
cd ../handy_tratra/flutter_tratra            # android/key.properties et google-services.json en place (hors Git)
flutter build apk --release --build-name=1.0.0-pilot.1 --build-number=101 --dart-define=TRATRA_API_BASE=https://api-staging.example.com/handy
adb install -r build/app/outputs/flutter-apk/app-release.apk     # un com.tratra signé autrement doit d'abord être désinstallé
```

## 8. Sauvegarde, restauration, rollback

```bash
scripts/staging/backup.sh                                              # backups/<horodatage>/ : db.dump, minio/, images (étiquette rollback-<horodatage>), manifest.txt
scripts/staging/restore.sh backups/<horodatage> [--with-objects]       # supprime puis recrée la base staging (confirmation à saisir)
scripts/staging/rollback.sh "$(cat backups/LAST)" --with-objects       # restauration + images précédentes + relance sans build + vérification
```
Schéma seul (sans restaurer les données), testé sur une base jetable depuis l'état de `origin/main` :
```bash
$DC stop tratrafrontend-stg beat worker
$DC exec tratraweb-stg python manage.py migrate business zero
$DC exec tratraweb-stg python manage.py migrate live zero
$DC exec tratraweb-stg python manage.py migrate trust zero
$DC exec tratraweb-stg python manage.py migrate handy 0016        # dernier état de la production actuelle (origin/main)
```
⚠️ Ces retours **suppriment** les tables/colonnes des nouveaux modules (avis détaillés, badges, suivi, Business) : préférer la restauration du dump.

## 9. Migrations

35 migrations par rapport à `origin/main` : `handy` 0017→0040 (24), `backoffice` 0001–0003, `business` 0001–0002, `trust` 0001–0002, `announcements` 0001,
`continuity` 0001, `engagements` 0001, `live` 0001. Seules deux opérations destructives existent, toutes deux HISTORIQUES et déjà déployées
(`handy` 0014 `RemoveField deposit_balance`, 0015 `RenameField related_id`) ; aucune des 34 nouvelles n'en contient. Données : plans d'abonnement
(0026), nettoyage des fonctionnalités de plan (0028), rattachement des entreprises (`business` 0002), catégorie des notifications (0036).
Les ajouts de colonnes sur des tables existantes sont NULLABLES ou ont une valeur par défaut (ex. `handy` 0039 : `provider_verified_at`,
`provider_checked_at`, `provider_status`, `provider_session`) : l'ancienne version du code tourne sur le schéma migré pendant le déploiement.

**Cliquet automatique** : `handy/test_migration_safety.py` fait échouer la suite si une migration supprime ou renomme, si un `RunPython` n'a pas de
retour arrière, si un `RunSQL` contient `DROP`/`TRUNCATE`/`DELETE`, ou si une colonne obligatoire sans valeur par défaut est ajoutée à une table
existante — sauf dérogation écrite dans `REVIEWED` après revue. Il vérifie aussi `makemigrations --check`.

Répétitions (base jetable PostGIS 16) : schéma `origin/main` → HEAD **OK**, retour à `handy 0016` **OK** (voir § 8 : destructif), nouvel aller **OK** ;
et, le 10 oct. 2026, retour des DEUX derniers lots (`handy` 0039 + `engagements` + `handy` 0038 + `backoffice` 0003 — paiements, engagements, MFA)
puis ré-application **OK**, `makemigrations --check` propre. Un retour de ces lots supprime les tables `engagements_*` et `backoffice_staffmfa` :
préférer la restauration du dump (§ 8).

Répétition sur une copie de la production (opérateur autorisé ; **anonymiser** : téléphones, e-mails, documents KYC) :
```bash
pg_dump -Fc -h <hôte-prod> -U <utilisateur> <base> > prod.dump          # lecture seule côté production
cat prod.dump | $DC exec -T tratradb pg_restore -U "$(sed -n 's/^DB_USER=//p' .env)" -d "$(sed -n 's/^DB_NAME=//p' .env)" --no-owner --no-privileges
$DC exec tratraweb-stg python manage.py migrate --plan | tail -30
```

## 10. Check-list de mise en service (staging puis production)

Dans l'ordre ; chaque étape a sa procédure détaillée.

1. **Sauvegarde** : `scripts/staging/backup.sh` (§ 8) AVANT toute migration ; garder `backups/LAST`.
2. **Variables** (§ 3, `.env.staging.example`) : `BACKOFFICE_MFA_REQUIRED=1`, `LEGACY_STAFF_BYPASS=0` (défauts de production), `MFA_ENCRYPTION_KEY`, secrets de
   webhook distincts, prestataires de paiement **vides** tant qu'ils ne sont pas qualifiés (`docs/paiements.md`).
3. **Déploiement** (§ 5) puis `scripts/staging/verify.sh` : 0 anomalie.
4. **Administrateurs** (`docs/securite-admin.md`) : `manage.py assign_legacy_staff_roles` (liste, simulation) → `--assign ID=ROLE` (répétable) `--apply` → chaque administrateur
   active sa double authentification → `manage.py security_preflight --strict`.
5. **Celery** : `manage.py celery_check --db` (noms, cadences, files écoutées, base du beat) — `verify.sh` le fait aussi pour le worker.
6. **Push** (§ 4, `docs/push-fcm.md`) : `manage.py push_check --token`, puis `--user <id> --send` avec l'application FERMÉE sur un vrai téléphone.
7. **Paiements** (`docs/paiements.md`) : `manage.py payments_check --ping`, puis la procédure de qualification prestataire par prestataire ; espèces inchangées.
8. **Retour arrière** : `scripts/staging/rollback.sh "$(cat backups/LAST)" --with-objects` testé une fois sur le staging avant la production.

## 11. Nettoyage du staging

```bash
docker compose -p tratra-staging -f docker-compose.staging.yml down            # arrête, conserve les volumes
docker compose -p tratra-staging -f docker-compose.staging.yml down -v         # supprime AUSSI les données du staging (jamais ailleurs)
```

## Ce qui a été vérifié

**Répétition complète sur un poste (Docker Desktop, 10–11 oct. 2026)** — `scripts/staging/rehearsal.sh` : images API (Debian bookworm), frontend et MinIO (source) construites ;
pile démarrée avec les VRAIS scripts (`deploy.sh` → `verify.sh`) derrière Traefik v3.6 en HTTPS (AC locale jetable, TLS **vérifié**, aucun `-k`) :
- `verify.sh` : **0 anomalie** (conteneurs sains, TLS, 21 routes, WebSocket refusé sans billet, ASGI http+websocket, PostGIS, 148 migrations, Redis, 7 tâches du beat + registre du worker).
- `rehearsal.sh admins` : personnel sans rôle → préflight **bloquant** → attribution des rôles → la MFA est **exigée** par l'API (403 `mfa_enrollment_required`) → activation →
  `security_preflight --strict --require-mfa` **vert**.
- `rehearsal.sh recette` : la recette HTTP du pilote, **47/47** (réservation → mission → messages → espèces avec reçu stocké dans MinIO → avis, puis contrat longue durée avec PDF).
- `rehearsal.sh drill` : sauvegarde → modification marquée → `rollback.sh` (base + images + relance + `verify.sh`) → marqueur disparu, pile saine.
- Redéploiements successifs (sauvegarde d'une base qui tourne, `up -d` idempotent) sans anomalie.

Autres contrôles : `docker compose config` ; réglages de production avec les valeurs du gabarit ; `handy/test_deploy_config.py` (file Celery, collisions Traefik, variables **toutes** documentées,
secrets hors Git/image, `PUBLIC_WEB_URL`, image de base supportée, MinIO non téléchargeable, TLS S3) ; `celery_check` ; cliquet de migrations ; Android réel (copie de recette) pour PDF,
purge, reprise et hors-ligne.

**Non exécuté** : Let's Encrypt réel (nom de domaine public), Firebase réel (aucun projet Firebase de Tratra), SMS réel, appels réels aux prestataires de paiement, passage Wi-Fi → données
mobiles, build iOS natif, Dokploy lui-même (le compose y est compatible : `TRAEFIK_CERTRESOLVER`, `PROXY_NETWORK`).
