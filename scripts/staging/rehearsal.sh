#!/usr/bin/env bash
# RÉPÉTITION LOCALE du staging : toute la pile (PostgreSQL/PostGIS, Redis, MinIO, API Django/Daphne, Celery worker + beat, frontend React, Traefik)
# est construite et démarrée sur CE poste, avec les VRAIS scripts de déploiement (deploy.sh, verify.sh, backup.sh, restore.sh, rollback.sh).
# Elle sert à valider le Dockerfile, le compose, l'entrypoint, les migrations et les scripts AVANT de toucher un serveur. Elle ne touche ni la
# production ni le projet « tratra-staging » : projet Compose, réseau, conteneur Traefik, images et dossier distincts, tous supprimés par `down`.
#
#   scripts/staging/rehearsal.sh up [--rebuild]   construit les images (étiquette « rehearsal ») et déploie
#   scripts/staging/rehearsal.sh verify           rejoue scripts/staging/verify.sh
#   scripts/staging/rehearsal.sh admins           rejoue la fermeture du passe-droit historique : rôles, MFA, security_preflight --strict (comptes JETABLES)
#   scripts/staging/rehearsal.sh recette          joue la recette du pilote (scripts/pilot/recette_api.py) par HTTPS sur comptes de répétition JETABLES
#   scripts/staging/rehearsal.sh drill            répète sauvegarde → modification → rollback (scripts backup.sh / rollback.sh) et vérifie le retour
#   scripts/staging/rehearsal.sh shell            ouvre un shell Django dans le conteneur de l'API (comptes de recette, security_preflight…)
#   scripts/staging/rehearsal.sh env              affiche le dossier de travail et les URL (aucun secret)
#   scripts/staging/rehearsal.sh down             supprime TOUT (conteneurs, volumes, réseau, images, dossier)
#
# Différences assumées avec un vrai staging : certificat signé par une AC LOCALE jetable (pas de Let's Encrypt), noms *.localtest.me (résolus en 127.0.0.1),
# identifiants SMS FICTIFS (aucun SMS ne part), MinIO joint par son adresse interne. Les ports 80 et 443 du poste doivent être libres.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="${REHEARSAL_DIR:-${TMPDIR:-/tmp}/tratra-rehearsal}"
PROJECT="tratra-rehearsal"; NET="rehearsal-proxy"; TRAEFIK="rehearsal-traefik"; TAG="rehearsal"
DOMAIN="localtest.me"
API_HOST="api-stg.${DOMAIN}"; FRONT_HOST="app-stg.${DOMAIN}"

say()  { printf '\033[1m[rehearsal]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[ERR ]\033[0m %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "$1 introuvable"; }
export STAGING_PROJECT="$PROJECT" STAGING_SKIP_BUILD=1
# Le certificat de la répétition est signé par une AC locale (WORK/pki/ca.pem) : les contrôles VÉRIFIENT le TLS (aucun -k).
export STAGING_CURL_OPTS="--cacert $WORK/pki/ca.pem" SSL_CERT_FILE="$WORK/pki/ca.pem"

dc() { (cd "$WORK" && docker compose -p "$PROJECT" -f docker-compose.staging.yml "$@"); }

# AC locale JETABLE + certificat générique *.localtest.me : Traefik le sert, l'API et les scripts lui font confiance (AWS_CA_BUNDLE, SSL_CERT_FILE).
make_pki() {
  mkdir -p "$WORK/pki" "$WORK/secrets" "$WORK/traefik-dynamic"
  [ -f "$WORK/pki/server.pem" ] && return 0
  ( cd "$WORK/pki"
    openssl genrsa -out ca.key 2048 2>/dev/null
    # Python 3.13+ exige les extensions d'une vraie AC (basicConstraints CA:TRUE + keyUsage keyCertSign) : sans elles, la vérification TLS échoue.
    printf '[req]\ndistinguished_name=dn\nx509_extensions=v3_ca\nprompt=no\n[dn]\nCN=Tratra Rehearsal CA (jetable)\n[v3_ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n' > ca.cnf
    openssl req -x509 -new -key ca.key -sha256 -days 30 -config ca.cnf -out ca.pem
    openssl genrsa -out server.key 2048 2>/dev/null
    openssl req -new -key server.key -subj "/CN=*.${DOMAIN}" -out server.csr
    printf 'subjectAltName=DNS:*.%s,DNS:%s\nextendedKeyUsage=serverAuth\n' "$DOMAIN" "$DOMAIN" > ext.cnf
    openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out server.pem -days 30 -sha256 -extfile ext.cnf 2>/dev/null
    chmod 644 ca.pem server.pem; chmod 600 ca.key server.key )
  cp "$WORK/pki/ca.pem" "$WORK/secrets/rehearsal-ca.pem"; chmod 644 "$WORK/secrets/rehearsal-ca.pem"
  printf 'tls:\n  stores:\n    default:\n      defaultCertificate:\n        certFile: /certs/server.pem\n        keyFile: /certs/server.key\n' > "$WORK/traefik-dynamic/tls.yml"
}

make_env() {
  python3 - "$REPO/.env.staging.example" "$WORK/.env" "$DOMAIN" <<'PY'
import base64, hashlib, re, secrets, sys
src, dst, domain = sys.argv[1:4]
text = open(src, encoding="utf-8").read().replace("staging.example.com", f"stg.{domain}")
def rand(n=48):
    return secrets.token_urlsafe(n).replace("-", "a").replace("_", "b")[:n]
fixed = {
    "IMAGE_TAG": "rehearsal", "PROXY_NETWORK": "rehearsal-proxy", "SENTRY_ENVIRONMENT": "rehearsal",
    "DB_NAME": "tratra_rehearsal", "DB_USER": "tratra_rehearsal",
    "AWS_S3_ENDPOINT_URL": f"https://minio-stg.{domain}", "AWS_S3_CUSTOM_DOMAIN": f"minio-stg.{domain}", "MEDIA_PUBLIC_HOSTS": f"minio-stg.{domain}", "AWS_S3_VERIFY": "/run/tratra-secrets/rehearsal-ca.pem",   # chemin de l'AC locale de la répétition (montée avec ./secrets) : TLS vérifié, jamais désactivé
    "MINIO_ROOT_USER": "rehearsal_minio", "AWS_ACCESS_KEY_ID": "rehearsal_minio",
    "SMS_BACKEND": "twilio", "TWILIO_ACCOUNT_SID": "AC" + "0" * 32, "TWILIO_AUTH_TOKEN": rand(32), "TWILIO_MESSAGING_SERVICE_SID": "MG" + "0" * 32,   # FICTIFS : aucun SMS
    "EMAIL_HOST": "localhost", "EMAIL_HOST_USER": "rehearsal", "EMAIL_HOST_PASSWORD": rand(16),
    "BASIC_AUTH_USERS": "admin:{SHA}" + base64.b64encode(hashlib.sha1(rand(16).encode()).digest()).decode(),
}
minio_pw = rand(32)
fixed["MINIO_ROOT_PASSWORD"], fixed["AWS_SECRET_ACCESS_KEY"] = minio_pw, minio_pw
out = []
for line in text.splitlines():
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
    if m:
        k, v = m.groups()
        if k in fixed:
            line = f"{k}={fixed[k]}"
        elif "CHANGE_ME" in v:
            line = f"{k}={rand(60)}"
    out.append(line)
present = {m.group(1) for m in (re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", l) for l in out) if m}
out += [f"{k}={v}" for k, v in fixed.items() if k not in present]       # variables propres à la répétition, absentes du gabarit (ex. AWS_CA_BUNDLE)
open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
  chmod 600 "$WORK/.env"
  # Hôtes courts « stg » (le garde-fou des scripts exige « stg » ou « staging » dans l'hôte de l'API).
  sed -i.bak -e "s#api-stg\.stg\.${DOMAIN}#${API_HOST}#g" -e "s#app-stg\.stg\.${DOMAIN}#${FRONT_HOST}#g" "$WORK/.env"; rm -f "$WORK/.env.bak"
}

cmd_up() {
  need docker; need python3; need openssl
  docker info >/dev/null 2>&1 || die "le démon Docker ne répond pas (lancer Docker Desktop)"
  for port in 80 443; do
    if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && [ -z "$(docker ps -q -f name="^${TRAEFIK}$")" ]; then die "le port ${port} du poste est déjà utilisé : libérez-le avant la répétition"; fi
  done
  mkdir -p "$WORK/secrets" "$WORK/backups"
  cp "$REPO/docker-compose.staging.yml" "$WORK/"
  rm -rf "$WORK/scripts"; mkdir -p "$WORK/scripts"; cp -R "$REPO/scripts/staging" "$WORK/scripts/staging"
  make_pki
  [ -f "$WORK/.env" ] || make_env
  say "Dossier de travail : $WORK (hors dépôt)"

  docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
  # Les conteneurs de la pile joignent les noms publics (API, frontend, MinIO) comme sur un vrai serveur : alias réseau de Traefik (épingle de cheveux).
  docker rm -f "$TRAEFIK" >/dev/null 2>&1 || true
  say "Traefik local (AC locale jetable : le résolveur ACME « lets » est déclaré mais inatteignable, Traefik sert alors le certificat *.localtest.me)"
  docker run -d --name "$TRAEFIK" --network "$NET" --network-alias "$API_HOST" --network-alias "$FRONT_HOST" --network-alias "minio-stg.${DOMAIN}" \
      -p 80:80 -p 443:443 -v /var/run/docker.sock:/var/run/docker.sock:ro -v "$WORK/pki:/certs:ro" -v "$WORK/traefik-dynamic:/etc/traefik/dynamic:ro" traefik:v3.6 \
      --providers.docker=true --providers.docker.exposedByDefault=false --providers.docker.network="$NET" --providers.file.directory=/etc/traefik/dynamic \
      --entrypoints.web.address=:80 --entrypoints.websecure.address=:443 \
      --certificatesresolvers.lets.acme.email=rehearsal@${DOMAIN} --certificatesresolvers.lets.acme.storage=/tmp/acme.json \
      --certificatesresolvers.lets.acme.tlschallenge=true --certificatesresolvers.lets.acme.caserver=https://127.0.0.1:1/dir >/dev/null

  if [ "${1:-}" = "--rebuild" ] || ! docker image inspect "tratra-backend:${TAG}" >/dev/null 2>&1; then
    say "Construction de l'image API (tratra-backend:${TAG})"
    docker build -t "tratra-backend:${TAG}" "$REPO"
  fi
  if [ "${1:-}" = "--rebuild" ] || ! docker image inspect "tratra-minio:${TAG}" >/dev/null 2>&1; then
    say "Construction de l'image MinIO depuis les sources (tratra-minio:${TAG}) — l'image officielle n'est plus publiée"
    docker build -t "tratra-minio:${TAG}" "$REPO/docker/minio"
  fi
  if [ "${1:-}" = "--rebuild" ] || ! docker image inspect "tratra-frontend:${TAG}" >/dev/null 2>&1; then
    say "Construction de l'image frontend (tratra-frontend:${TAG})"
    docker build -t "tratra-frontend:${TAG}" \
      --build-arg "NEXT_PUBLIC_API_BASE=https://${API_HOST}/handy" --build-arg "NEXT_PUBLIC_SITE_URL=https://${FRONT_HOST}" --build-arg "NEXT_PUBLIC_PAYMENT_METHODS=cash" "$REPO/frontend"
  fi

  say "Déploiement avec le VRAI script : scripts/staging/deploy.sh (sauvegarde → démarrage → santé → verify.sh)"
  (cd "$WORK" && chmod +x scripts/staging/*.sh && scripts/staging/deploy.sh)
  cmd_env
}

# Rejoue, sur la pile de répétition (réglages de PRODUCTION, vraie base), la procédure du pilote pour les administrateurs historiques :
# personnel sans rôle → préflight bloquant → attribution des rôles → MFA exigée par l'API → activation → préflight --strict --require-mfa.
cmd_admins() {
  local pw; pw="$(openssl rand -base64 24 | tr -d '=/+' | cut -c1-24)Aa1!"
  local pf="python manage.py security_preflight"
  say "1/6 Comptes historiques JETABLES (2 anciens administrateurs sans rôle, 2 super administrateurs)"
  dc exec -T -e RH_PW="$pw" tratraweb-stg python manage.py shell <<'PY' >/dev/null
import os
from django.contrib.auth import get_user_model
U = get_user_model(); pw = os.environ["RH_PW"]
U.objects.filter(username__startswith="rh_").delete()      # rejouable : on repart de comptes neufs (rôles et MFA compris)
for name, kw in (("rh_old_ops", {}), ("rh_old_fin", {}), ("rh_super_a", {"is_superuser": True}), ("rh_super_b", {"is_superuser": True})):
    u, _ = U.objects.get_or_create(username=name, defaults=dict(email=f"{name}@rehearsal.test", is_staff=True, is_verified=True, **kw))
    u.is_staff, u.is_active = True, True; u.is_superuser = bool(kw.get("is_superuser")); u.set_password(pw); u.save()
PY
  say "2/6 Préflight AVANT attribution : doit être BLOQUANT (personnel sans rôle)"
  if dc exec -T tratraweb-stg $pf --strict >/dev/null 2>&1; then die "le préflight aurait dû bloquer"; fi
  dc exec -T tratraweb-stg $pf 2>&1 | sed -n '/Bloquants/,$p' | sed 's/^/        /'
  say "3/6 Attribution des rôles (simulation puis application)"
  local ids; ids="$(dc exec -T tratraweb-stg python manage.py shell -c "from django.contrib.auth import get_user_model as g; U=g(); print(*[f'{u.pk}:{u.username}' for u in U.objects.filter(username__in=['rh_old_ops','rh_old_fin'])])")"
  local ops fin; ops="$(printf '%s\n' $ids | grep rh_old_ops | cut -d: -f1)"; fin="$(printf '%s\n' $ids | grep rh_old_fin | cut -d: -f1)"
  dc exec -T tratraweb-stg python manage.py assign_legacy_staff_roles --assign "${ops}=ops" --assign "${fin}=finance" | sed 's/^/        /'
  dc exec -T tratraweb-stg python manage.py assign_legacy_staff_roles --assign "${ops}=ops" --assign "${fin}=finance" --apply | sed 's/^/        /'
  say "4/6 Préflight APRÈS attribution : plus aucun bloquant de rôles"
  dc exec -T tratraweb-stg $pf --strict | sed 's/^/        /'
  say "5/6 La MFA est EXIGÉE par l'API du Back-Office (HTTPS) : un administrateur sans appareil activé est refusé"
  local tok code
  tok="$(curl -s --cacert "$WORK/pki/ca.pem" -X POST "https://${API_HOST}/handy/auth/login/" -H 'Content-Type: application/json' -d "{\"username\":\"rh_old_fin\",\"password\":\"${pw}\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access",""))')"
  [ -n "$tok" ] || die "connexion de l'administrateur de répétition impossible"
  # /backoffice/me/ (identité) reste lisible pour afficher l'écran d'activation ; toute route de DONNÉES est refusée tant que la MFA n'est pas activée.
  code="$(curl -s --cacert "$WORK/pki/ca.pem" -H "Authorization: Bearer ${tok}" "https://${API_HOST}/handy/backoffice/dashboard/" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("code"))')"
  [ "$code" = "mfa_enrollment_required" ] && printf '        refus attendu sur /backoffice/dashboard/ : %s\n' "$code" || die "l'API aurait dû répondre mfa_enrollment_required (reçu : ${code})"
  say "6/6 Activation de la MFA (équivalent d'un scan de QR) puis préflight final --strict --require-mfa"
  if dc exec -T tratraweb-stg $pf --strict --require-mfa >/dev/null 2>&1; then die "--require-mfa aurait dû bloquer (MFA non activée)"; fi
  dc exec -T tratraweb-stg python manage.py shell <<'PY' >/dev/null
import base64, time
from django.contrib.auth import get_user_model
from django_otp.oath import TOTP
from backoffice import mfa
for u in get_user_model().objects.filter(is_staff=True):
    if mfa.confirmed_device(u) is None:
        secret = mfa.begin_enrollment(u)["secret"]
        t = TOTP(base64.b32decode(secret), step=30, digits=6); t.time = time.time()
        mfa.confirm_enrollment(u, f"{t.token():06d}")
PY
  dc exec -T tratraweb-stg $pf --strict --require-mfa | sed 's/^/        /'
  dc exec -T tratraweb-stg python manage.py staff_mfa | sed 's/^/        /'
  say "Procédure des administrateurs validée de bout en bout sur la pile de répétition."
}

# Comptes de recette JETABLES : un client et un artisan dont le dossier est complété comme après approbation humaine du KYC (étape humaine
# simulée UNIQUEMENT dans cette répétition — en vrai staging le KYC est approuvé par un administrateur, jamais contourné).
cmd_recette() {
  local pw; pw="$(openssl rand -base64 24 | tr -d '=/+' | cut -c1-20)Aa1!"
  dc exec -T -e RC_PW="$pw" tratraweb-stg python manage.py shell <<'PY' >/dev/null
import os
from django.contrib.auth import get_user_model
from handy.models import Service, ServiceCategory
from handy.testing import make_eligible
U = get_user_model(); pw = os.environ["RC_PW"]
def account(username, **kw):
    u = U.objects.filter(username=username).first() or U.objects.create_user(username, f"{username}@rehearsal.test", pw, **kw)
    u.set_password(pw); u.is_active = True; u.save()           # rejouable : mêmes comptes, nouveau mot de passe
    return u
client = account("rc_client", user_type="client", is_verified=True, first_name="Awa", last_name="Recette", phone="+2250700077701")
pro = account("rc_artisan", user_type="handyman", is_verified=True, first_name="Moussa", last_name="Recette", phone="+2250700077702")
cat, _ = ServiceCategory.objects.get_or_create(slug="plomberie", defaults={"name": "Plomberie"})
make_eligible(pro.handyman_profile, category=cat)
Service.objects.get_or_create(handyman=pro, title="Dépannage plomberie", defaults=dict(category=cat, description="Fuite, robinetterie.", price_type="fixed", price=15000, is_active=True))
PY
  say "Recette HTTPS contre https://${API_HOST}/handy (comptes rc_client / rc_artisan, mot de passe aléatoire non affiché)"
  RECETTE_CLIENT=rc_client RECETTE_ARTISAN=rc_artisan RECETTE_PASSWORD="$pw" python3 "$REPO/scripts/pilot/recette_api.py" --api "https://${API_HOST}/handy"
}

# Répétition du retour arrière : sauvegarde, modification marquée de la base, rollback (scripts réels), contrôle que la modification a disparu.
cmd_drill() {
  say "1/4 Sauvegarde (backup.sh)"
  (cd "$WORK" && scripts/staging/backup.sh) | tail -3
  local dir; dir="$(cat "$WORK/backups/LAST")"
  say "2/4 Modification marquée : un compte « rh_marker » est créé APRÈS la sauvegarde"
  dc exec -T tratraweb-stg python manage.py shell -c "from django.contrib.auth import get_user_model as g; g().objects.filter(username='rh_marker').delete(); g().objects.create_user('rh_marker','m@rehearsal.test','Zz-9x!kQ2mV7aPw')" >/dev/null 2>&1
  [ "$(dc exec -T tratraweb-stg python manage.py shell -c "from django.contrib.auth import get_user_model as g; print(g().objects.filter(username='rh_marker').count())" 2>/dev/null | tail -1)" = "1" ] || die "marqueur non créé"
  say "3/4 Retour arrière (rollback.sh ${dir} --with-objects --yes) : restauration de la base, images précédentes, relance, verify.sh"
  (cd "$WORK" && scripts/staging/rollback.sh "$dir" --with-objects --yes) | tail -12
  say "4/4 Contrôle : le marqueur doit avoir DISPARU et la pile être saine"
  [ "$(dc exec -T tratraweb-stg python manage.py shell -c "from django.contrib.auth import get_user_model as g; print(g().objects.filter(username='rh_marker').count())" 2>/dev/null | tail -1)" = "0" ] || die "le marqueur est toujours là : la base n'a pas été restaurée"
  say "Retour arrière validé : base restaurée, pile saine."
}

cmd_verify() { (cd "$WORK" && scripts/staging/verify.sh); }
cmd_shell()  { dc exec tratraweb-stg python manage.py shell; }

cmd_env() {
  say "Dossier : $WORK"
  say "API      : https://${API_HOST}/handy   (AC locale : curl --cacert $WORK/pki/ca.pem)"
  say "Frontend : https://${FRONT_HOST}"
  say "Commandes : cd '$WORK' && STAGING_PROJECT=${PROJECT} STAGING_SKIP_BUILD=1 STAGING_CURL_OPTS=\"--cacert $WORK/pki/ca.pem\" SSL_CERT_FILE=$WORK/pki/ca.pem scripts/staging/<verify|backup|restore|rollback>.sh"
  say "           docker compose -p ${PROJECT} -f docker-compose.staging.yml exec tratraweb-stg python manage.py <commande>"
}

cmd_down() {
  need docker
  if [ -d "$WORK" ]; then dc down -v --remove-orphans 2>/dev/null || true; fi
  docker rm -f "$TRAEFIK" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  if [ -d "$WORK/backups" ]; then
    for f in "$WORK"/backups/*/images.txt; do
      [ -f "$f" ] || continue
      while read -r image _; do [ -n "$image" ] && docker rmi "$image" >/dev/null 2>&1 || true; done < "$f"
    done
  fi
  docker rmi "tratra-backend:${TAG}" "tratra-frontend:${TAG}" "tratra-minio:${TAG}" >/dev/null 2>&1 || true
  rm -rf "$WORK"
  say "Répétition supprimée (conteneurs, volumes, réseau, images « ${TAG} » et sauvegardes de répétition)."
}

case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  verify) cmd_verify ;;
  admins) cmd_admins ;;
  recette) cmd_recette ;;
  drill) cmd_drill ;;
  shell) cmd_shell ;;
  env) cmd_env ;;
  down) cmd_down ;;
  *) sed -n '2,19p' "$0"; exit 2 ;;
esac
