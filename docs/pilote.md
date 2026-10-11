# Pilote Tratra — du poste de développement aux téléphones

Fil conducteur **exécutable** : chaque étape est une commande (ou une action humaine signalée 👤). Détails : [déploiement staging](deploiement-staging.md) ·
[sécurité administrateurs](securite-admin.md) · [push FCM](push-fcm.md) · [paiements](paiements.md) · [SMS](sms-otp.md) · [recette](recette-pilote.md).
Rien n'est poussé ni déployé par ces documents : chaque commande est lancée à la main, sur le bon poste.

## 1. Répétition locale (avant tout serveur) — 15 min

Construit les deux images, démarre **toute** la pile (PostgreSQL/PostGIS, Redis, MinIO, API Django/Daphne + WebSocket, Celery worker + beat, frontend React, Traefik en HTTPS
auto-signé) avec les **vrais** scripts de déploiement, puis se vérifie. Ne touche ni la production ni `tratra-staging`.

```bash
scripts/staging/rehearsal.sh up            # construction + déploiement + verify.sh (ports 80/443 libres, Docker lancé) — 0 anomalie attendue
scripts/staging/rehearsal.sh admins        # rôles historiques → MFA exigée par l'API → préflight strict, sur des comptes jetables
scripts/staging/rehearsal.sh recette       # recette HTTP complète du pilote (47 contrôles) par HTTPS
scripts/staging/rehearsal.sh drill         # sauvegarde → modification → rollback → contrôle du retour
scripts/staging/rehearsal.sh shell         # shell Django dans le conteneur
scripts/staging/rehearsal.sh down          # supprime tout (conteneurs, volumes, réseau, images, dossier de travail)
```

## 2. Serveur de staging — pré-requis 👤

```bash
# DNS : 4 enregistrements A/AAAA vers le serveur (adminer facultatif)
#   api-staging.<domaine>   app-staging.<domaine>   minio-staging.<domaine>   minio-console-staging.<domaine>
docker network ls | grep -w proxy                  # réseau de VOTRE Traefik (Dokploy : dokploy-network). Ne pas le recréer.
docker compose version                             # Compose v2
```
Traefik : entrypoint `websecure` et résolveur ACME (`lets` par défaut ; **Dokploy : `TRAEFIK_CERTRESOLVER=letsencrypt` et `PROXY_NETWORK=dokploy-network`**).

## 3. Variables d'environnement

`cp .env.staging.example .env && chmod 600 .env` puis remplacer chaque `CHANGE_ME` (le script de déploiement refuse de démarrer sinon). **Toute variable lue par les réglages figure dans le
gabarit** (test `test_every_setting_read_from_the_environment_is_documented…`). Secrets aléatoires : `docs/deploiement-staging.md` § 3.

| Famille | Variables | Qui les fournit | Règle |
|---|---|---|---|
| **Domaines** | `tratraweb_HOST`, `FRONTEND_HOST`, `MINIO_*_HOST`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `PUBLIC_WEB_URL`, `NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_SITE_URL` | 👤 DNS | l'hôte de l'API contient « staging »/« stg » (garde-fou anti-production) ; tout en HTTPS ; `PUBLIC_WEB_URL` = frontend (QR) |
| **Sécurité** | `SECRET_KEY`, `DB_PASSWORD`, `MFA_ENCRYPTION_KEY`, `BACKOFFICE_MFA_REQUIRED=1`, `LEGACY_STAFF_BYPASS=0`, secrets de webhook | généré | jamais de valeur de production ; MFA et fermeture du passe-droit = défauts de production |
| **Stockage** | `MINIO_ROOT_*`, `AWS_*`, `AWS_STORAGE_BUCKET_NAME`, `KYC_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `KYC_*` | généré | buckets dédiés au staging ; KYC privé (URL signées) ; aucune politique anonyme |
| **SMS (OTP)** | `SMS_BACKEND`, `TWILIO_*` ou `AT_*` | 👤 compte Twilio ou Africa's Talking | **l'OTP n'est jamais contourné** ; un compte d'essai n'envoie qu'aux numéros vérifiés |
| **Push** | `FCM_CREDENTIALS_FILE` (`./secrets/fcm-service-account.json`), `FCM_PROJECT_ID` | 👤 projet Firebase **de Tratra** | fichier hors Git et hors image (`chmod 0400`, uid 10001) ; vide = pas de push, pas d'erreur |
| **Paiements** | `PAYMENT_*_WEBHOOK_SECRET`, `OM_*`, `MTN_MOMO_*`, `STRIPE_*`, `PAYMENT_RETURN_URL` … | 👤 comptes marchands | **vides** tant qu'un prestataire n'est pas qualifié (`docs/paiements.md`) : la méthode répond « indisponible » ; espèces toujours disponibles |
| **E-mail / suivi** | `EMAIL_*`, `SENTRY_DSN`, `ROUTING_OSRM_URL` | 👤 | facultatifs |

## 4. Déploiement, migrations, sauvegarde, retour arrière

```bash
# Poste de développement : envoyer la révision SANS publier la branche
git archive --format=tar.gz --prefix=tratra-staging/ HEAD | ssh <serveur> 'tar -xz -C ~'
# Serveur
cd ~/tratra-staging && cp .env.staging.example .env && chmod 600 .env   # puis renseigner .env
scripts/staging/deploy.sh          # sauvegarde → build → up → attente de santé (migrations par l'entrypoint) → verify.sh
```
- **Migrations** : appliquées par l'entrypoint (`check --deploy` puis `migrate`), **non destructives** (cliquet `handy/test_migration_safety.py`), 35 depuis `origin/main`.
  Contrôle : `docker compose -p tratra-staging -f docker-compose.staging.yml exec tratraweb-stg python manage.py migrate --check`.
- **Sauvegarde** (automatique avant chaque déploiement, manuelle possible) : `scripts/staging/backup.sh` → `backups/<horodatage>/` (dump PostgreSQL, objets MinIO, images étiquetées `rollback-<horodatage>`, manifeste).
- **Retour arrière** : `scripts/staging/rollback.sh "$(cat backups/LAST)" --with-objects` (restaure la base, réétiquette les images précédentes, relance sans construire, re-vérifie).
  Restauration seule : `scripts/staging/restore.sh backups/<horodatage> [--with-objects]`.
- **Dokploy** : service *Compose* → `./docker-compose.staging.yml` → onglet *Environment* = contenu de `.env` ; rollback = redéployer la révision précédente (ou `rollback.sh` en SSH).

## 5. Administrateurs : rôles, MFA, pré-vol strict 👤

```bash
DC="docker compose -p tratra-staging -f docker-compose.staging.yml"
$DC exec tratraweb-stg python manage.py createsuperuser                         # première fois seulement (mot de passe fort, saisi à la main)
$DC exec tratraweb-stg python manage.py assign_legacy_staff_roles               # liste le personnel historique SANS rôle (simulation)
$DC exec tratraweb-stg python manage.py assign_legacy_staff_roles --assign 7=ops --assign 9=finance --apply
# Chaque administrateur se connecte au Back-Office et active sa double authentification (QR + 10 codes de secours).
$DC exec tratraweb-stg python manage.py security_preflight --strict              # code 0 = rôles attribués, ≥ 2 super administrateurs, réglages fermés
$DC exec tratraweb-stg python manage.py security_preflight --strict --require-mfa   # contrôle FINAL : chaque compte actif a activé sa double authentification
```

## 6. Celery, notifications, push

```bash
$DC exec tratraweb-stg python manage.py celery_check --db           # noms, cadences, files écoutées, base du beat
$DC exec tratraweb-stg python manage.py push_check --token          # compte de service Firebase valide ?
$DC exec tratraweb-stg python manage.py push_check --user 12 --send # VRAI push de test (application FERMÉE sur le téléphone)
$DC exec tratraweb-stg python manage.py payments_check --ping       # prestataires de paiement (indisponibles tant que non configurés)
```

## 7. APK pilote pointant vers le staging

Dépôt Flutter (`handy_tratra/flutter_tratra`), clé de signature pilote hors Git (`android/key.properties` → `~/.tratra-pilot/`) :
```bash
export FIREBASE_PROJECT_ID=… FIREBASE_MESSAGING_SENDER_ID=… FIREBASE_API_KEY_ANDROID=… FIREBASE_APP_ID_ANDROID=…   # 👤 console Firebase DE TRATRA (facultatif : sans = pas de push)
tool/build_pilot_apk.sh --api https://api-staging.<domaine>/handy --version 1.0.0-pilot.2 --build 102
adb install -r build/pilot/tratra-pilot-1.0.0-pilot.2-api-staging.<domaine>.apk
```
Le script refuse : base non HTTPS, hôte local/IP/« example », signature absente (jamais de clé debug), Firebase partiel, tests rouges ; il vérifie la signature et que l'hôte est bien figé dans l'APK.

## 8. Recette

```bash
python3 scripts/pilot/recette_api.py --api https://api-staging.<domaine>/handy      # 47 contrôles (voir docs/recette-pilote.md)
```
Puis la recette manuelle sur téléphones : `docs/recette-pilote.md` (SMS réel, KYC humain, push application fermée, Android réel, Back-Office avec MFA).

## 8 bis. Mettre à jour un serveur de PRODUCTION existant (docker-compose.yml) — sans coupure imprévue

`docker compose up --build -d` reconstruit **et redémarre** l'API avec les réglages de production actuels : si `.env` est incomplet, elle refuse de démarrer. À faire dans l'ordre :

```bash
cd /home/ubuntu/tratra && git pull
# 1. Compléter .env (modèle : .env.example — le gabarit complet commenté : .env.staging.example). Plus aucun « variable is not set » ci-dessous :
docker compose config -q
python3 scripts/check_env.py            # liste d'un coup TOUS les écarts du .env avec la production (jamais de valeur affichée) ; `check --deploy` n'en montre qu'un à la fois
#    Variables que les versions récentes exigent : KYC_STORAGE_BUCKET_NAME (≠ AWS_STORAGE_BUCKET_NAME), FRONTEND_HOST, NEXT_PUBLIC_API_BASE (https://<hôte API>/handy),
#    PUBLIC_WEB_URL (https), SMS_BACKEND + identifiants (l'OTP n'est jamais contourné), AWS_S3_ENDPOINT_URL = adresse PUBLIQUE de MinIO en https (`https://<MINIO_API_HOST>`, pas `http://minio:9000`), SECRET_KEY aléatoire (pas `django-insecure-…`), ALLOWED_HOSTS (avec l'hôte de l'API), CORS_ALLOWED_ORIGINS, CSRF_TRUSTED_ORIGINS.
# 2. Sauvegarder la base :
docker compose exec -T tratradb pg_dump -U "$(sed -n 's/^DB_USER=//p' .env)" -d "$(sed -n 's/^DB_NAME=//p' .env)" -Fc > ~/tratra-avant-maj-$(date +%F).dump
# 3. Construire SANS redémarrer (MinIO est construit depuis les sources : docker/minio — l'image officielle n'est plus téléchargeable) :
docker compose build minio tratraweb tratrafrontend
# 4. Valider la configuration de production avec le NOUVEAU .env, sans toucher aux conteneurs en cours :
docker compose run --rm --no-deps tratraweb python manage.py check --deploy
# 5. Démarrer :
docker compose up -d
```
MinIO : même version que l'ancienne image, volume `minio_data` relu tel quel (aucune migration de données). Administrateurs : la MFA est exigée et le passe-droit historique fermé par défaut ;
pour la transition, voir le bloc « Sécurité de l'administration » de `.env.example` (relâcher explicitement, assigner les rôles, activer la MFA, puis remettre les défauts).

### Si `migrate` échoue avec « column "image_url" of relation "handy_service" already exists » (serveur ancien)

Cause : l'historique des migrations de la base ne porte pas les mêmes **noms** que le dépôt. Les migrations `handy 0016/0017` ont été générées ailleurs puis renommées
(un serveur réel avait `0016_booking_total_price` et `0017_heroslide`, qu'aucun commit du dépôt ne contient). Le schéma est déjà là — colonne `image_url`, table `handy_heroslide` —
mais Django ne reconnaît pas le nom `0017_service_image_url_alter_service_banner_heroslide` et rejoue l'ajout. Les lignes inconnues de `django_migrations` sont ignorées : ne **jamais** les supprimer.
Chaque migration échoue en bloc (DDL transactionnel) : une tentative qui échoue ne modifie rien. **API arrêtée** pendant la réparation (`docker compose stop tratraweb worker beat`).

```bash
# 1. Diagnostic en LECTURE SEULE : objets déjà présents + écarts modèle ↔ base (aucune écriture)
docker compose run --rm --no-deps -T tratraweb python manage.py shell < scripts/migration_drift.py
```
Lecture du résultat, migration par migration :

- **Tous** les objets de la migration sont listés comme déjà présents **et** aucun écart n'est signalé pour ses modèles → le schéma est déjà celui de la migration : on l'enregistre sans la rejouer.
- Seulement **une partie** des objets existe, ou un écart est signalé (colonne absente / en trop / nullabilité) → **ne rien enregistrer** ; réparer le schéma à la main (SQL ciblé) puis recontrôler.

```bash
# 2. Enregistrer UNE migration dont le schéma est confirmé complet (ici handy 0017) — aperçu puis application :
docker compose run --rm --no-deps tratraweb python manage.py migrate handy 0017_service_image_url_alter_service_banner_heroslide --fake --plan
docker compose run --rm --no-deps tratraweb python manage.py migrate handy 0017_service_image_url_alter_service_banner_heroslide --fake
# 3. Rejouer le diagnostic, puis la suite ; répéter 1–2 pour chaque nouvelle collision :
docker compose run --rm --no-deps -T tratraweb python manage.py shell < scripts/migration_drift.py
docker compose run --rm --no-deps tratraweb python manage.py migrate
```
Ne lancer `docker compose up -d` qu'une fois `migrate` terminé sans erreur.

### Si l'API redémarre en boucle avec « PermissionError: … /app/staticfiles/… » (volumes d'un ancien serveur)

Le conteneur tourne en utilisateur non-root (`appuser`, uid 10001). Un volume `static_volume` / `media_volume` créé par une ancienne image qui tournait en root reste à root :
`collectstatic` ne peut ni supprimer ni écrire dedans et l'entrypoint s'arrête après `migrate`. L'entrypoint le détecte désormais avant `collectstatic` et affiche cette commande. Réparation, une seule fois (ne supprime rien) :

```bash
docker compose run --rm --no-deps --user root --entrypoint sh tratraweb -c 'chown -R 10001:10001 /app/staticfiles /app/media' && docker compose up -d && docker compose ps
```

## 9. Ce qui demande une intervention humaine 👤

0. ~~Image MinIO de production~~ : corrigée — le compose de production construit `docker/minio` comme le staging (le serveur réel avait échoué sur « pull access denied for minio/mc »).
1. **Domaine et DNS** du staging (4 enregistrements) et accès SSH/Dokploy au serveur.
2. **Projet Firebase de Tratra** : compte de service (`secrets/fcm-service-account.json`) et les 4 options de l'application Android (aucun identifiant n'est disponible dans le dépôt).
3. **Fournisseur SMS** (Twilio ou Africa's Talking) : le staging refuse de démarrer sans lui ; l'OTP n'est jamais contourné.
4. **Comptes marchands** Orange Money / MTN MoMo / Stripe : seulement pour qualifier les paiements ; non nécessaires au pilote en espèces.
5. **Administrateurs réels** : attribuer les rôles, activer la MFA, conserver les codes de secours ; `security_preflight --strict`.
6. **KYC** des artisans de recette : approbation humaine dans le Back-Office.
7. **Recette sur téléphones** (Android réel, application fermée) et décision go/no-go (`docs/recette-pilote.md` § 3).
8. **Décision métier** : recouvrement de la commission sur les paiements en espèces (aucun fonds ne transite par Tratra).
