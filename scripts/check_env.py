#!/usr/bin/env python3
"""Contrôle du fichier .env AVANT `docker compose up` : liste d'un seul coup TOUS les écarts avec les exigences des réglages de production.

    python3 scripts/check_env.py [chemin/.env]        # défaut : ./.env

`manage.py check --deploy` s'arrête à la première erreur (un seul `ImproperlyConfigured` à la fois) : ce script reprend les mêmes règles
(tratra/settings/prod.py, docker-compose.yml, docs/pilote.md) et les affiche ensemble. Il n'affiche JAMAIS une valeur — seulement le nom
de la variable et la règle non respectée. Bibliothèque standard uniquement. Code de sortie 1 s'il reste une erreur (les avertissements n'échouent pas)."""
import re
import sys
from pathlib import Path


def parse(path: Path, issues=None) -> dict:
    """Lit un .env comme Docker Compose (dernière valeur gagnante). `issues` reçoit (variable, règle) pour les lignes douteuses :
    espaces autour de « = » (ni `docker run --env-file` ni l'entrée de l'API ne les tolèrent tous) et variable définie plusieurs fois."""
    env, seen = {}, set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)(\s*)=(\s*)(.*)$", line)
        if m and not line.lstrip().startswith("#"):
            name, before, after, value = m.groups()
            if issues is not None:
                if before or after:
                    issues.append((name, "espaces autour du « = » : écrire NOM=valeur sans espace"))
                if name in seen:
                    issues.append((name, "définie plusieurs fois dans le fichier (la dernière l'emporte) : ne garder qu'une ligne"))
            seen.add(name)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            env[name] = value
    return env


def check(env: dict):
    """Renvoie (erreurs, avertissements) : listes de (variable, règle). Aucune valeur n'y figure."""
    errors, warns = [], []
    err = lambda var, rule: errors.append((var, rule))      # noqa: E731
    warn = lambda var, rule: warns.append((var, rule))      # noqa: E731
    get = lambda k: env.get(k, "").strip()                  # noqa: E731
    truthy = lambda k, default=False: (get(k).lower() in ("1", "true", "yes", "on")) if get(k) else default   # noqa: E731

    for k, v in env.items():
        if "CHANGE_ME" in v or "example.com" in v.lower() or "example.test" in v.lower():
            err(k, "valeur de gabarit à remplacer (CHANGE_ME / example.com)")

    if get("DJANGO_ENV") != "prod":
        err("DJANGO_ENV", "doit valoir « prod » (sinon les réglages de développement s'appliquent)")
    if get("DEBUG").lower() in ("1", "true", "yes", "on"):
        err("DEBUG", "doit être False en production")

    key = get("SECRET_KEY")
    if not key:
        err("SECRET_KEY", "absente")
    elif key.startswith("django-insecure-"):
        err("SECRET_KEY", "clé de DÉVELOPPEMENT (django-insecure-…) : à remplacer par une clé aléatoire (python3 -c \"import secrets; print(secrets.token_urlsafe(64))\")")
    elif len(key) < 50:
        err("SECRET_KEY", "trop courte (50 caractères minimum)")

    api, front = get("tratraweb_HOST"), get("FRONTEND_HOST")
    for var in ("tratraweb_HOST", "FRONTEND_HOST", "MINIO_API_HOST", "MINIO_CONSOLE_HOST"):
        if not get(var):
            err(var, "absente (utilisée par les routeurs Traefik du compose)")
    hosts = [h.strip() for h in get("ALLOWED_HOSTS").split(",") if h.strip()]
    if not hosts or "*" in hosts:
        err("ALLOWED_HOSTS", "doit lister explicitement les hôtes de production (pas de *)")
    elif any("://" in h or "/" in h for h in hosts):
        err("ALLOWED_HOSTS", "des NOMS d'hôtes nus, sans https:// ni chemin (ex. api.exemple.ci,tratraweb) — un nom avec https:// ne correspond à aucune requête")
    elif any(h.endswith("_HOST") for h in hosts):
        err("ALLOWED_HOSTS", "contient un nom de variable (…_HOST) au lieu de sa valeur : le .env n'interprète pas les variables, écrire le nom d'hôte réel")
    elif api and api not in hosts:
        err("ALLOWED_HOSTS", "doit contenir l'hôte de l'API (tratraweb_HOST) — sinon 400 sur toutes les requêtes et sonde de santé en échec")
    for var in ("CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"):
        origins = [o.strip() for o in get(var).split(",") if o.strip()]
        if not origins:
            err(var, "absente")
        elif any(not o.startswith("https://") for o in origins):
            err(var, "origines en https:// uniquement")
        elif front and f"https://{front}" not in origins:
            warn(var, "ne contient pas https://<FRONTEND_HOST> : le navigateur du site serait refusé")

    if not truthy("MINIO_ENABLED"):
        err("MINIO_ENABLED", "doit valoir True (stockage objet obligatoire en production)")
    for var in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_STORAGE_BUCKET_NAME", "KYC_STORAGE_BUCKET_NAME"):
        if not get(var):
            err(var, "absente")
    if get("KYC_STORAGE_BUCKET_NAME") and get("KYC_STORAGE_BUCKET_NAME") == get("AWS_STORAGE_BUCKET_NAME"):
        err("KYC_STORAGE_BUCKET_NAME", "doit être DIFFÉRENT de AWS_STORAGE_BUCKET_NAME (pièces d'identité dans un bucket privé distinct)")
    endpoint = get("AWS_S3_ENDPOINT_URL")
    if not endpoint:
        err("AWS_S3_ENDPOINT_URL", "absente")
    elif not endpoint.lower().startswith("https://"):
        err("AWS_S3_ENDPOINT_URL", "doit être en https:// — l'adresse PUBLIQUE de MinIO : https://<MINIO_API_HOST> (pas http://minio:9000)")
    elif get("MINIO_API_HOST") and endpoint.rstrip("/") != f"https://{get('MINIO_API_HOST')}":
        warn("AWS_S3_ENDPOINT_URL", "diffère de https://<MINIO_API_HOST> : les liens signés doivent pointer vers l'hôte public de MinIO")
    if get("AWS_S3_VERIFY") and not truthy("AWS_S3_VERIFY", True) and get("AWS_S3_VERIFY").lower() in ("0", "false", "no", "off"):
        err("AWS_S3_VERIFY", "ne peut pas être désactivée en production")

    web = get("PUBLIC_WEB_URL")
    if not web:
        err("PUBLIC_WEB_URL", "absente (encodée dans les QR Tratra ID / mission)")
    elif not web.lower().startswith("https://"):
        err("PUBLIC_WEB_URL", "doit être en https:// — l'URL du frontend (http://localhost:3000 est la valeur par défaut de développement)")
    elif front and web.rstrip("/") != f"https://{front}":
        warn("PUBLIC_WEB_URL", "diffère de https://<FRONTEND_HOST>")
    base = get("NEXT_PUBLIC_API_BASE")
    if not base:
        err("NEXT_PUBLIC_API_BASE", "absente (figée dans le frontend au build)")
    elif not (base.startswith("https://") and base.rstrip("/").endswith("/handy")):
        err("NEXT_PUBLIC_API_BASE", "doit être de la forme https://<hôte API>/handy")

    providers = []
    for item in re.split(r"[,;\s]+", get("SMS_BACKEND").lower()):
        if item and item not in providers:
            providers.append(item)
    needs = {"twilio": ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"), "orange": (), "africastalking": ("AT_USERNAME", "AT_API_KEY")}
    if not providers or any(p not in needs for p in providers):
        err("SMS_BACKEND", "doit valoir « twilio », « orange » ou « africastalking », ou une liste ordonnée (twilio,orange) pour la relève automatique (l'OTP n'est jamais contourné)")
    else:
        for provider in providers:
            for var in needs[provider]:
                if not get(var):
                    err(var, f"absente (exigée par SMS_BACKEND={provider})")
        if "twilio" in providers and not any(get(v) for v in ("TWILIO_MESSAGING_SERVICE_SID", "TWILIO_FROM", "TWILIO_PHONE_NUMBER")):
            err("TWILIO_MESSAGING_SERVICE_SID", "ou TWILIO_FROM : l'une des deux est exigée avec Twilio")
        if "orange" in providers and not (get("ORANGE_SMS_AUTHORIZATION_HEADER") or (get("ORANGE_SMS_CLIENT_ID") and get("ORANGE_SMS_CLIENT_SECRET"))):
            err("ORANGE_SMS_CLIENT_ID", "et ORANGE_SMS_CLIENT_SECRET (ou ORANGE_SMS_AUTHORIZATION_HEADER) sont exigés avec Orange")
        if "orange" in providers:
            sender = re.sub(r"\D", "", re.sub(r"^(?:tel(?::|%3A))?\s*(?:\+|%2B)?", "", get("ORANGE_SMS_SENDER") or "2250000", flags=re.I))
            if not re.fullmatch(r"\d{5,15}", sender):
                err("ORANGE_SMS_SENDER", "doit être le numéro d'expéditeur Orange du pays, en chiffres (ex. 2250000) — sinon Orange ET le fournisseur de relève sont inutilisables")
        if len(providers) == 1:
            warn("SMS_BACKEND", f"un seul fournisseur ({providers[0]}) : s'il tombe, plus aucun code OTP — ex. SMS_BACKEND=twilio,orange pour une relève automatique")

    for var in ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST"):
        if not get(var):
            err(var, "absente")
    if not get("REDIS_URL") and not get("REDIS_HOST"):
        err("REDIS_URL", "absente")

    if not truthy("BACKOFFICE_MFA_REQUIRED", True):
        warn("BACKOFFICE_MFA_REQUIRED", "double authentification des administrateurs DÉSACTIVÉE (transition seulement)")
    if truthy("LEGACY_STAFF_BYPASS", False):
        warn("LEGACY_STAFF_BYPASS", "passe-droit historique du personnel sans rôle OUVERT (transition seulement)")
    return errors, warns


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0] if argv else ".env")
    if not path.is_file():
        print(f"Fichier introuvable : {path}", file=sys.stderr)
        return 2
    issues = []
    errors, warns = check(parse(path, issues))
    errors = [(v, r) for v, r in issues if "espaces" in r or "plusieurs fois" in r] + errors
    for var, rule in errors:
        print(f"[ERREUR] {var} : {rule}")
    for var, rule in warns:
        print(f"[AVERT.] {var} : {rule}")
    print(f"\n{len(errors)} erreur(s), {len(warns)} avertissement(s) — aucune valeur n'est affichée.")
    if not errors:
        print("Configuration cohérente : docker compose run --rm --no-deps tratraweb python manage.py check --deploy peut être lancé.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
