"""Garde-fous de déploiement : ce qui a déjà cassé (ou aurait cassé) un environnement ne doit plus passer en silence.

- la file Celery par défaut est écoutée par le worker de chaque compose (sinon aucune tâche ne s'exécute) ;
- la pile staging ne peut pas entrer en collision avec la production sur le Traefik partagé ;
- toute variable du compose staging est documentée dans .env.staging.example, qui ne contient aucun secret réel ;
- les réglages de production refusent un PUBLIC_WEB_URL absent ou non HTTPS (QR vers localhost sinon) ;
- les secrets (Firebase, .env, sauvegardes) n'entrent ni dans Git ni dans l'image Docker.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from django.conf import settings

ROOT = Path(settings.BASE_DIR)


def _compose(name):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def _labels(service):
    raw = service.get("labels") or []
    if isinstance(raw, dict):
        return [f"{k}={v}" for k, v in raw.items()]
    return list(raw)


def _traefik_names(compose):
    """Noms globaux Traefik (routeurs, services, middlewares) déclarés dans les labels d'un compose."""
    names = set()
    for svc in compose["services"].values():
        for label in _labels(svc):
            m = re.match(r"traefik\.http\.(routers|services|middlewares)\.([^.=]+)[.=]", label)
            if m:
                names.add((m.group(1), m.group(2)))
    return names


def _worker_queues(compose):
    queues = {}
    for name, svc in compose["services"].items():
        command = svc.get("command")
        text = " ".join(command) if isinstance(command, list) else str(command or "")
        if "celery" in text and " worker" in text:
            m = re.search(r"--queues=(\S+)", text)
            queues[name] = set(m.group(1).split(",")) if m else {"celery"}
    return queues


@pytest.mark.parametrize("compose_file", ["docker-compose.yml", "docker-compose.staging.yml"])
def test_celery_default_queue_is_consumed_by_every_worker(compose_file):
    workers = _worker_queues(_compose(compose_file))
    assert workers, "aucun worker Celery dans " + compose_file
    for name, queues in workers.items():
        assert settings.CELERY_TASK_DEFAULT_QUEUE in queues, (
            f"{compose_file}:{name} n'écoute pas la file par défaut « {settings.CELERY_TASK_DEFAULT_QUEUE} » : "
            "les tâches (notifications, push, badges, purge GPS) ne s'exécuteraient jamais")


def test_staging_worker_also_drains_the_legacy_celery_queue():
    # Producteurs d'une ancienne version (file « celery ») pendant une mise à jour progressive.
    for queues in _worker_queues(_compose("docker-compose.staging.yml")).values():
        assert "celery" in queues


def test_staging_cannot_collide_with_production_on_the_shared_traefik():
    prod, stg = _compose("docker-compose.yml"), _compose("docker-compose.staging.yml")
    clash = _traefik_names(prod) & _traefik_names(stg)
    assert not clash, f"noms Traefik partagés avec la production : {sorted(clash)}"
    assert stg["name"] == "tratra-staging"
    assert not [v for v in (stg.get("volumes") or {}).values() if v and v.get("external")], "volume externe en staging"
    for name, svc in stg["services"].items():
        assert "container_name" not in svc, f"{name}: container_name rendrait les noms globaux"
        assert not svc.get("ports"), f"{name}: aucun port publié (Traefik uniquement)"
        nets = svc.get("networks") or {}
        if "proxy" in nets:  # réseau partagé avec la production : le nom de service sert d'alias DNS, il doit être unique
            assert name.endswith("-stg"), f"{name}: service sur « proxy » sans suffixe -stg (alias DNS en collision)"
            if isinstance(nets, dict):
                aliases = (nets["proxy"] or {}).get("aliases") or []
                assert all(a.endswith("-stg") for a in aliases), f"{name}: alias proxy sans suffixe -stg"
    prod_proxy_services = {n for n, s in prod["services"].items() if "proxy" in (s.get("networks") or [])}
    assert not (prod_proxy_services & set(stg["services"])), "nom de service identique à un service de production sur « proxy »"


def test_staging_healthcheck_presents_public_host_and_https_scheme():
    api = _compose("docker-compose.staging.yml")["services"]["tratraweb-stg"]["healthcheck"]["test"]
    text = " ".join(api)
    assert "Host:" in text and "X-Forwarded-Proto: https" in text and "/readyz" in text
    assert "127.0.0.1" in text


def test_every_compose_variable_is_documented_in_the_staging_env_example():
    compose_text = (ROOT / "docker-compose.staging.yml").read_text(encoding="utf-8")
    documented = set(re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)=", (ROOT / ".env.staging.example").read_text(encoding="utf-8"), re.M))
    used = set()
    for m in re.finditer(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)([^}]*)\}", compose_text):
        if not m.group(2).startswith((":-", "-")):          # sans valeur par défaut = obligatoire
            used.add(m.group(1))
    missing = used - documented
    assert not missing, f"variables du compose staging absentes de .env.staging.example : {sorted(missing)}"


def test_staging_env_example_declares_every_variable_the_production_settings_demand():
    documented = set(re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)=", (ROOT / ".env.staging.example").read_text(encoding="utf-8"), re.M))
    required = {
        "DJANGO_ENV", "SECRET_KEY", "ALLOWED_HOSTS", "CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS", "PUBLIC_WEB_URL",
        "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "REDIS_URL", "REDIS_HOST",
        "MINIO_ENABLED", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_STORAGE_BUCKET_NAME", "KYC_STORAGE_BUCKET_NAME",
        "AWS_S3_ENDPOINT_URL", "SMS_BACKEND", "FCM_CREDENTIALS_FILE", "FCM_PROJECT_ID", "ROUTING_OSRM_URL",
        "tratraweb_HOST", "FRONTEND_HOST", "NEXT_PUBLIC_API_BASE",
    }
    assert not (required - documented), f"manquantes : {sorted(required - documented)}"


def test_staging_env_example_holds_placeholders_only():
    secret_key = re.compile(r"(PASSWORD|SECRET|TOKEN|API_KEY|SECRET_KEY|_USERS)$")
    for line in (ROOT / ".env.staging.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m and secret_key.search(m.group(1)):
            assert m.group(2) == "" or m.group(2).startswith("CHANGE_ME"), f"{m.group(1)} contient une valeur réelle ?"


def test_firebase_key_env_files_and_backups_stay_out_of_git_and_images():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    docker_ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ".env.staging" in ignore and "secrets/*" in ignore and "backups/" in ignore
    assert re.search(r"^\.env\.\*", docker_ignore, re.M) and "secrets/" in docker_ignore and "backups/" in docker_ignore


# ── Réglages de production : PUBLIC_WEB_URL ─────────────────────────────────────────────────────────────────────────

_PROD_ENV = {
    "DJANGO_ENV": "prod", "DJANGO_SETTINGS_MODULE": "tratra.settings",
    "SECRET_KEY": "CiSyntheticSecret-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4Y5z6",
    "MINIO_ENABLED": "True", "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "y",
    "AWS_STORAGE_BUCKET_NAME": "media", "KYC_STORAGE_BUCKET_NAME": "kyc-private",
    "AWS_S3_ENDPOINT_URL": "https://minio.example.test", "MEDIA_PUBLIC_HOSTS": "minio.example.test",
    "ALLOWED_HOSTS": "api.example.test", "CORS_ALLOWED_ORIGINS": "https://app.example.test",
    "CSRF_TRUSTED_ORIGINS": "https://app.example.test", "SMS_BACKEND": "africastalking",
    "AT_USERNAME": "x", "AT_API_KEY": "x", "DB_NAME": "x", "DB_USER": "x", "DB_PASSWORD": "x", "DB_HOST": "127.0.0.1", "DB_PORT": "1",
    "STRIPE_WEBHOOK_SECRET": "x", "PAYMENT_WEBHOOK_SECRET": "x",
}


def _load_prod_settings(**extra):
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "GDAL_LIBRARY_PATH", "GEOS_LIBRARY_PATH")}
    for name in ("GDAL_LIBRARY_PATH", "GEOS_LIBRARY_PATH"):          # développement macOS : chemins Homebrew déduits par dev.py
        if name not in env and getattr(settings, name, None):
            env[name] = str(getattr(settings, name))
    env.update(_PROD_ENV)
    env.update(extra)
    code = "import django; django.setup(); from django.conf import settings; print('PUBLIC_WEB_URL=' + settings.PUBLIC_WEB_URL)"
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


def test_production_refuses_a_missing_public_web_url():
    r = _load_prod_settings()
    assert r.returncode != 0 and "PUBLIC_WEB_URL must be explicitly configured" in r.stderr


def test_production_refuses_a_non_https_public_web_url():
    r = _load_prod_settings(PUBLIC_WEB_URL="http://app.example.test")
    assert r.returncode != 0 and "PUBLIC_WEB_URL must use HTTPS" in r.stderr


def test_production_accepts_an_https_public_web_url():
    r = _load_prod_settings(PUBLIC_WEB_URL="https://app.example.test/")
    assert r.returncode == 0, r.stderr[-400:]
    assert "PUBLIC_WEB_URL=https://app.example.test" in r.stdout          # barre finale retirée
