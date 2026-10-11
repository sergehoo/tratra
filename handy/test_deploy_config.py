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


def _load_prod_settings(code=None, **extra):
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "GDAL_LIBRARY_PATH", "GEOS_LIBRARY_PATH")}
    for name in ("GDAL_LIBRARY_PATH", "GEOS_LIBRARY_PATH"):          # développement macOS : chemins Homebrew déduits par dev.py
        if name not in env and getattr(settings, name, None):
            env[name] = str(getattr(settings, name))
    env.update(_PROD_ENV)
    env.update(extra)
    code = code or "import django; django.setup(); from django.conf import settings; print('PUBLIC_WEB_URL=' + settings.PUBLIC_WEB_URL)"
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


_ADMIN_SECURITY_CODE = ("import django; django.setup(); from django.conf import settings; "
                        "print('MFA=%s BYPASS=%s' % (settings.BACKOFFICE_MFA_REQUIRED, settings.LEGACY_STAFF_BYPASS))")


def test_production_requires_admin_mfa_and_closes_the_legacy_staff_bypass_by_default():
    r = _load_prod_settings(code=_ADMIN_SECURITY_CODE, PUBLIC_WEB_URL="https://app.example.test")
    assert r.returncode == 0, r.stderr[-400:]
    assert "MFA=True BYPASS=False" in r.stdout


def test_production_relaxation_must_be_explicit_and_is_reported_by_the_deploy_check():
    r = _load_prod_settings(code=_ADMIN_SECURITY_CODE, PUBLIC_WEB_URL="https://app.example.test", BACKOFFICE_MFA_REQUIRED="0", LEGACY_STAFF_BYPASS="1")
    assert r.returncode == 0 and "MFA=False BYPASS=True" in r.stdout
    check = ("import django; django.setup(); from backoffice.checks import admin_security; print(sorted(w.id for w in admin_security(None)))")
    r = _load_prod_settings(code=check, PUBLIC_WEB_URL="https://app.example.test", BACKOFFICE_MFA_REQUIRED="0", LEGACY_STAFF_BYPASS="1")
    assert "tratra.W001" in r.stdout and "tratra.W002" in r.stdout


# Variables lues par les réglages mais volontairement ABSENTES du gabarit : propres au conteneur ou dangereuses en staging.
UNDOCUMENTED_ON_PURPOSE = {
    "GDAL_LIBRARY_PATH", "GEOS_LIBRARY_PATH",     # chemins des bibliothèques SIG : posés par l'image Docker
    "CORS_ALLOW_ALL_ORIGINS",                     # ne doit JAMAIS être activé hors développement
    "ENABLE_SSL_HARDENING",                       # réservé au poste de développement
}


def test_every_setting_read_from_the_environment_is_documented_in_the_staging_env_example():
    """Aucune variable de réglage (Firebase, SMS, paiements, domaines, sécurité, stockage…) ne reste « secrète » : toute variable lue par
    les réglages ou les modules d'envoi figure dans `.env.staging.example`, active (`NOM=`) ou facultative (`# NOM=`)."""
    example = (ROOT / ".env.staging.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*([A-Za-z][A-Za-z0-9_]{2,})=", example, re.M))
    read = set()
    for name in ("tratra/settings/base.py", "tratra/settings/prod.py", "handy/sms.py", "handy/push.py", "handy/services/gateway.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        read |= set(re.findall(r"(?:config|env_bool|os\.getenv|os\.environ\.get|env)\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]", text))
    missing = sorted(read - documented - UNDOCUMENTED_ON_PURPOSE)
    assert not missing, f"variables d'environnement lues mais absentes de .env.staging.example : {missing}"


def test_images_are_built_on_a_supported_debian_release():
    """Debian 11 « bullseye » n'est plus maintenu : son miroir de sécurité retire les paquets (404) et l'image ne se construit plus. Les
    Dockerfile doivent partir d'une version supportée (bookworm ou plus récente, ou alpine)."""
    for name in ("Dockerfile", "frontend/Dockerfile"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            if line.strip().upper().startswith("FROM "):
                assert not re.search(r"bullseye|buster|stretch|jessie", line, re.I), f"{name} : image de base en fin de vie — {line.strip()}"


def test_staging_does_not_depend_on_minio_images_that_can_no_longer_be_pulled():
    """MinIO n'est plus publié sur Docker Hub ni quay.io (« pull access denied ») : le staging construit MinIO depuis les sources aux versions
    épinglées, aussi en production (le serveur réel a échoué sur « pull access denied for minio/mc »). Une référence à `minio/minio` ou
    `minio/mc` casserait tout serveur neuf ou toute reconstruction."""
    for name in ("docker-compose.staging.yml", "docker-compose.yml"):                     # staging ET production : « docker compose up --build » doit marcher sur un serveur neuf
        compose = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"image:\s*(quay\.io/)?minio/(minio|mc)\b", compose), name
        assert "context: ./docker/minio" in compose, name
    dockerfile = (ROOT / "docker/minio/Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"ARG MINIO_TAG=RELEASE\.\d{4}-\d\d-\d\dT[\d-]+Z", dockerfile) and re.search(r"ARG MC_TAG=RELEASE\.", dockerfile)
    assert "go install" in dockerfile and "sum.golang.org" in dockerfile      # intégrité des sources vérifiée par la base de sommes de contrôle de Go


_S3_CODE = ("import django; django.setup(); from django.conf import settings; print('VERIFY=%r' % (settings.AWS_S3_VERIFY,))")
_S3_ENV = dict(MINIO_ENABLED="True", AWS_ACCESS_KEY_ID="k", AWS_SECRET_ACCESS_KEY="s", AWS_STORAGE_BUCKET_NAME="b", KYC_STORAGE_BUCKET_NAME="k", AWS_S3_ENDPOINT_URL="https://s3.example.test",
               PUBLIC_WEB_URL="https://app.example.test")


@pytest.mark.parametrize("raw,expected", [("True", "True"), ("", "False"), ("/run/ca.pem", "'/run/ca.pem'")])
def test_s3_tls_verification_accepts_true_or_a_ca_bundle_path(raw, expected):
    """`AWS_S3_VERIFY` peut désigner un lot d'AC (PKI interne) : django-storages le transmet à boto3. `False`/vide est refusé en production."""
    r = _load_prod_settings(code=_S3_CODE, AWS_S3_VERIFY=raw, **_S3_ENV)
    if expected == "False":
        assert r.returncode != 0 and "AWS_S3_VERIFY must remain enabled" in r.stderr
    else:
        assert r.returncode == 0, r.stderr[-400:]
        assert f"VERIFY={expected}" in r.stdout


def test_production_healthcheck_presents_public_host_and_https_scheme():
    """Sans cela la sonde reçoit 400 (hôte refusé) puis 301 (redirection HTTPS) : l'API reste « unhealthy » et `docker compose up -d` n'a pas pu démarrer
    le worker, beat et le frontend qui en dépendent."""
    api = _compose("docker-compose.yml")["services"]["tratraweb"]["healthcheck"]
    text = " ".join(api["test"])
    assert "Host:" in text and "X-Forwarded-Proto: https" in text and "/readyz" in text and "tratraweb_HOST" in text
    assert api.get("start_period")


_CHECK_ENV = ROOT / "scripts" / "check_env.py"


def _check_env_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_env", _CHECK_ENV)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_GOOD_ENV = """DJANGO_ENV=prod
DEBUG=False
SECRET_KEY=Zk3-longue-cle-aleatoire-Zk3-longue-cle-aleatoire-Zk3-longue-cle-aleatoire-0
tratraweb_HOST=api.tratra.test
FRONTEND_HOST=app.tratra.test
MINIO_API_HOST=minio.tratra.test
MINIO_CONSOLE_HOST=minio-console.tratra.test
ALLOWED_HOSTS=api.tratra.test,tratraweb
CORS_ALLOWED_ORIGINS=https://app.tratra.test
CSRF_TRUSTED_ORIGINS=https://app.tratra.test,https://api.tratra.test
MINIO_ENABLED=True
MINIO_ROOT_USER=root
MINIO_ROOT_PASSWORD=pw-root
AWS_ACCESS_KEY_ID=key
AWS_SECRET_ACCESS_KEY=secret
AWS_STORAGE_BUCKET_NAME=tratra-media
KYC_STORAGE_BUCKET_NAME=tratra-kyc-private
AWS_S3_ENDPOINT_URL=https://minio.tratra.test
PUBLIC_WEB_URL=https://app.tratra.test
NEXT_PUBLIC_API_BASE=https://api.tratra.test/handy
SMS_BACKEND=twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=twtoken-9f3a
TWILIO_MESSAGING_SERVICE_SID=MGxxxx
DB_NAME=tratra
DB_USER=tratra
DB_PASSWORD=dbpw
DB_HOST=tratradb
REDIS_URL=redis://redis:6379/0
"""


def test_check_env_accepts_a_coherent_production_env_and_never_prints_a_value(tmp_path, capsys):
    module = _check_env_module()
    env = tmp_path / ".env"
    env.write_text(_GOOD_ENV, encoding="utf-8")
    assert module.main([str(env)]) == 0
    out = capsys.readouterr().out
    assert "0 erreur(s)" in out and "Zk3-longue-cle" not in out and "pw-root" not in out


def test_check_env_lists_every_gap_of_an_old_server_env_at_once_without_leaking_values(tmp_path, capsys):
    """Le cas réel d'un serveur dont le .env date d'un ancien modèle : clé de développement, endpoint MinIO interne en http, URL du site locale,
    bucket KYC absent, SMS non configuré — tout doit être signalé EN UNE FOIS (check --deploy ne montre qu'une erreur à la fois)."""
    module = _check_env_module()
    old = _GOOD_ENV.replace("Zk3-longue-cle-aleatoire-Zk3-longue-cle-aleatoire-Zk3-longue-cle-aleatoire-0", "django-insecure-abc123SECRETVALUE")
    old = old.replace("AWS_S3_ENDPOINT_URL=https://minio.tratra.test", "AWS_S3_ENDPOINT_URL=http://minio:9000")
    old = old.replace("PUBLIC_WEB_URL=https://app.tratra.test", "PUBLIC_WEB_URL=http://localhost:3000")
    old = old.replace("KYC_STORAGE_BUCKET_NAME=tratra-kyc-private\n", "").replace("SMS_BACKEND=twilio\n", "SMS_BACKEND=\n")
    env = tmp_path / ".env"
    env.write_text(old, encoding="utf-8")
    errors, _ = module.check(module.parse(env))
    names = {var for var, _ in errors}
    assert {"SECRET_KEY", "AWS_S3_ENDPOINT_URL", "PUBLIC_WEB_URL", "KYC_STORAGE_BUCKET_NAME", "SMS_BACKEND"} <= names
    assert module.main([str(env)]) == 1
    printed = capsys.readouterr().out
    for secret in ("abc123SECRETVALUE", "pw-root", "dbpw", "ACxxxxxxxx", "twtoken-9f3a"):
        assert secret not in printed
    assert module.main([str(tmp_path / "absent.env")]) == 2


def test_check_env_rules_match_the_production_settings(tmp_path):
    """Les règles du script sont celles de prod.py : un .env sans erreur pour le script doit être accepté par les réglages de production."""
    module = _check_env_module()
    env = module.parse(_write(tmp_path, _GOOD_ENV))
    assert module.check(env)[0] == []
    r = _load_prod_settings(code="import django; django.setup(); print('ok')", **{k: v for k, v in env.items() if k not in ("PATH", "HOME")})
    assert r.returncode == 0, r.stderr[-300:]


def _write(tmp_path, text):
    p = tmp_path / "prod.env"
    p.write_text(text, encoding="utf-8")
    return p


def test_check_env_catches_spaces_around_equals_urls_in_allowed_hosts_and_duplicates(tmp_path):
    """Le cas réel : `ALLOWED_HOSTS = https://api…,tratraweb,tratraweb_HOST` (espaces, schéma, nom de variable littéral) et `NEXT_PUBLIC_API_BASE` en double."""
    module = _check_env_module()
    bad = _GOOD_ENV.replace("ALLOWED_HOSTS=api.tratra.test,tratraweb", "ALLOWED_HOSTS = https://api.tratra.test,tratraweb,tratraweb_HOST")
    bad += "NEXT_PUBLIC_API_BASE=https://api.tratra.test/handy\n"
    env = tmp_path / ".env"
    env.write_text(bad, encoding="utf-8")
    issues = []
    errors, _ = module.check(module.parse(env, issues))
    rules = {(v, r.split(" ")[0]) for v, r in issues}
    assert ("ALLOWED_HOSTS", "espaces") in rules and ("NEXT_PUBLIC_API_BASE", "définie") in rules
    assert any(v == "ALLOWED_HOSTS" and "sans https://" in r for v, r in errors)
    fixed = _GOOD_ENV
    env.write_text(fixed, encoding="utf-8")
    issues = []
    assert module.check(module.parse(env, issues))[0] == [] and issues == []


# ---- Volumes d'un ancien serveur (créés par une image qui tournait en root) ----------------------------------------------

def _run_volume_check(*dirs):
    """Exécute la VRAIE fonction de l'entrypoint (extraite du script) sur des dossiers donnés."""
    src = (ROOT / "entrypoint.sh").read_text()
    func = re.search(r"^check_volumes_writable\(\) \{\n.*?^\}\n", src, re.S | re.M).group(0)
    script = 'error() { printf "%s\\n" "$*" >&2; }\nset -eu\n' + func + 'check_volumes_writable "$@"\n'
    return subprocess.run(["sh", "-c", script, "sh", *map(str, dirs)], capture_output=True, text=True)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignore les droits d'écriture : le cas ne peut pas se produire")
def test_entrypoint_refuses_a_volume_the_app_user_cannot_write_and_names_the_repair(tmp_path):
    static = tmp_path / "staticfiles"
    (static / "img").mkdir(parents=True)
    (static / "img" / "favicon.png").write_text("x")
    (static / "img").chmod(0o555)  # dossier « à root » : le fichier ne peut pas être supprimé (cas réel du serveur)
    try:
        res = _run_volume_check(static, tmp_path / "absent")
    finally:
        (static / "img").chmod(0o755)
    assert res.returncode != 0
    assert "n'est pas inscriptible" in res.stderr
    assert "chown -R" in res.stderr and "--user root" in res.stderr and "/app/staticfiles /app/media" in res.stderr


def test_entrypoint_accepts_writable_or_missing_volumes_and_runs_the_check_before_collectstatic(tmp_path):
    (tmp_path / "staticfiles" / "img").mkdir(parents=True)
    assert _run_volume_check(tmp_path / "staticfiles", tmp_path / "absent").returncode == 0
    src = (ROOT / "entrypoint.sh").read_text()
    sequence = src.split("# ---------- Run sequence ----------")[1]
    assert sequence.index("check_volumes_writable /app/staticfiles /app/media") < sequence.index("\ncollect_static")


# ---- SMS : liste ordonnée de fournisseurs (relève Twilio → Orange) ---------------------------------------------------------

_SMS_CODE = "import django; django.setup(); from django.conf import settings; print('SMS=' + settings.SMS_BACKEND)"
_TWILIO = {"TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tw", "TWILIO_FROM": "+1500"}


_SMS_VARS = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_PHONE_NUMBER", "TWILIO_MESSAGING_SERVICE_SID",
             "AT_USERNAME", "AT_API_KEY", "ORANGE_SMS_CLIENT_ID", "ORANGE_SMS_CLIENT_SECRET", "ORANGE_SMS_AUTHORIZATION_HEADER")


def _sms_prod(**extra):
    """Les réglages de production lisent aussi le `.env` du développeur (python-decouple) : on VIDE explicitement chaque variable SMS
    (une variable présente mais vide l'emporte sur le fichier) pour que le test ne dépende jamais d'identifiants réels."""
    return _load_prod_settings(code=_SMS_CODE, PUBLIC_WEB_URL="https://app.example.test", **{**dict.fromkeys(_SMS_VARS, ""), **extra})


def test_production_accepts_an_ordered_provider_list_and_normalises_it():
    r = _sms_prod(SMS_BACKEND=" Twilio , orange,twilio ", ORANGE_SMS_CLIENT_ID="cid", ORANGE_SMS_CLIENT_SECRET="sec", **_TWILIO)
    assert r.returncode == 0, r.stderr[-400:]
    assert r.stdout.strip().splitlines()[-1] == "SMS=twilio,orange"  # exact : aucun doublon, ordre conservé


def test_production_accepts_orange_alone_with_either_form_of_credentials():
    r = _sms_prod(SMS_BACKEND="orange", ORANGE_SMS_CLIENT_ID="cid", ORANGE_SMS_CLIENT_SECRET="sec")
    assert r.returncode == 0 and "SMS=orange" in r.stdout, r.stderr[-400:]
    r = _sms_prod(SMS_BACKEND="orange", ORANGE_SMS_AUTHORIZATION_HEADER="Basic abc")
    assert r.returncode == 0, r.stderr[-400:]


@pytest.mark.parametrize("extra,message", [
    ({"SMS_BACKEND": "orange"}, "ORANGE_SMS_CLIENT_ID and ORANGE_SMS_CLIENT_SECRET"),
    ({"SMS_BACKEND": "orange", "ORANGE_SMS_CLIENT_ID": "cid"}, "ORANGE_SMS_CLIENT_ID and ORANGE_SMS_CLIENT_SECRET"),
    ({"SMS_BACKEND": "twilio,orange", **_TWILIO}, "ORANGE_SMS_CLIENT_ID and ORANGE_SMS_CLIENT_SECRET"),   # relève incomplète : jamais acceptée
    ({"SMS_BACKEND": "twilio,orange", "ORANGE_SMS_CLIENT_ID": "c", "ORANGE_SMS_CLIENT_SECRET": "s"}, "TWILIO_ACCOUNT_SID"),
    ({"SMS_BACKEND": "twilio,console", **_TWILIO}, 'SMS_BACKEND must be'),
    ({"SMS_BACKEND": "twilio,inconnu", **_TWILIO}, 'SMS_BACKEND must be'),
    ({"SMS_BACKEND": ",,"}, 'SMS_BACKEND must be'),
])
def test_production_refuses_an_incomplete_or_unknown_provider_chain(extra, message):
    r = _sms_prod(**extra)
    assert r.returncode != 0 and message in r.stderr


def _check_env_run(tmp_path, capsys, env_text):
    module = _check_env_module()
    path = tmp_path / ".env"
    path.write_text(env_text, encoding="utf-8")
    code = module.main([str(path)])
    return code, capsys.readouterr().out


_ORANGE_VARS = "ORANGE_SMS_CLIENT_ID=orange-cid-77\nORANGE_SMS_CLIENT_SECRET=orange-secret-88\n"


def test_check_env_accepts_a_twilio_then_orange_chain_without_the_single_provider_warning(tmp_path, capsys):
    code, out = _check_env_run(tmp_path, capsys, _GOOD_ENV.replace("SMS_BACKEND=twilio\n", "SMS_BACKEND=twilio,orange\n") + _ORANGE_VARS)
    assert code == 0 and "0 erreur(s)" in out
    assert "un seul fournisseur" not in out and "orange-secret-88" not in out and "twtoken-9f3a" not in out


def test_check_env_suggests_a_failover_when_only_one_provider_is_configured(tmp_path, capsys):
    code, out = _check_env_run(tmp_path, capsys, _GOOD_ENV)
    assert code == 0 and "un seul fournisseur (twilio)" in out and "twilio,orange" in out


def test_check_env_flags_missing_orange_credentials_and_unknown_providers(tmp_path, capsys):
    code, out = _check_env_run(tmp_path, capsys, _GOOD_ENV.replace("SMS_BACKEND=twilio\n", "SMS_BACKEND=twilio,orange\n"))
    assert code != 0 and "ORANGE_SMS_CLIENT_ID" in out and "ORANGE_SMS_CLIENT_SECRET" in out
    code, out = _check_env_run(tmp_path, capsys, _GOOD_ENV.replace("SMS_BACKEND=twilio\n", "SMS_BACKEND=twilio,inconnu\n"))
    assert code != 0 and "liste ordonnée" in out
    code, out = _check_env_run(tmp_path, capsys, _GOOD_ENV.replace("SMS_BACKEND=twilio\n", "SMS_BACKEND=orange\n") + "ORANGE_SMS_AUTHORIZATION_HEADER=Basic abc\n")
    assert code == 0  # l'en-tête fourni par le portail suffit


def test_sms_module_and_production_settings_parse_the_provider_list_the_same_way(monkeypatch):
    from handy import sms

    class _S:  # réglages minimaux : `backend_names` lit `settings.SMS_BACKEND`
        DEBUG = False

    for raw in (" Twilio , orange,twilio ", "orange;twilio", "twilio  orange", "africastalking"):
        monkeypatch.setattr(sms, "settings", type("S", (), {"DEBUG": False, "SMS_BACKEND": raw})())
        r = _sms_prod(SMS_BACKEND=raw, ORANGE_SMS_CLIENT_ID="c", ORANGE_SMS_CLIENT_SECRET="s", AT_USERNAME="u", AT_API_KEY="k", **_TWILIO)
        assert r.returncode == 0, r.stderr[-300:]
        assert r.stdout.strip().splitlines()[-1] == f"SMS={','.join(sms.backend_names())}"


def test_production_refuses_a_twilio_orange_chain_without_a_twilio_sender():
    r = _sms_prod(SMS_BACKEND="twilio,orange", TWILIO_ACCOUNT_SID="a", TWILIO_AUTH_TOKEN="b",
                  ORANGE_SMS_CLIENT_ID="c", ORANGE_SMS_CLIENT_SECRET="s")
    assert r.returncode != 0 and "TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM" in r.stderr


@pytest.mark.parametrize("sender,ok", [("", True), ("2250000", True), ("+225 0000", True), ("tel:+2250000", True),
                                       ("tel%3A%2B2250000", True), ("abc", False), ("12", False), ("tel:+", False)])
def test_production_checks_the_orange_sender_like_the_sms_module_does(sender, ok):
    """Un numéro d'expéditeur illisible ferait échouer la construction d'Orange à CHAQUE envoi et rendrait Twilio inutilisable aussi :
    il doit être refusé au démarrage, avec exactement la règle de handy.sms.orange_sender."""
    from handy import sms

    assert bool(__import__("re").fullmatch(r"\d{5,15}", sms.orange_sender(sender))) is ok
    r = _sms_prod(SMS_BACKEND="twilio,orange", ORANGE_SMS_CLIENT_ID="c", ORANGE_SMS_CLIENT_SECRET="s", ORANGE_SMS_SENDER=sender, **_TWILIO)
    assert (r.returncode == 0) is ok, r.stderr[-300:]
    if not ok:
        assert "ORANGE_SMS_SENDER" in r.stderr


@pytest.mark.parametrize("sender,ok", [("", True), ("+225 0000", True), ("tel%3A%2B2250000", True), ("abc", False), ("12", False)])
def test_check_env_checks_the_orange_sender_like_production(tmp_path, capsys, sender, ok):
    env = _GOOD_ENV.replace("SMS_BACKEND=twilio\n", "SMS_BACKEND=twilio,orange\n") + _ORANGE_VARS + f"ORANGE_SMS_SENDER={sender}\n"
    code, out = _check_env_run(tmp_path, capsys, env)
    assert (code == 0) is ok, out
    assert ("ORANGE_SMS_SENDER" in out) is (not ok)


@pytest.mark.parametrize("extra,needle", [
    ("ORANGE_SMS_CLIENT_ID=seul-identifiant\n", "ORANGE_SMS_CLIENT_SECRET"),
    ("ORANGE_SMS_CLIENT_SECRET=seul-secret\n", "ORANGE_SMS_CLIENT_ID"),
])
def test_check_env_refuses_half_of_the_orange_credentials_without_printing_them(tmp_path, capsys, extra, needle):
    code, out = _check_env_run(tmp_path, capsys, _GOOD_ENV.replace("SMS_BACKEND=twilio\n", "SMS_BACKEND=twilio,orange\n") + extra)
    assert code != 0 and needle in out and "seul-" not in out


def test_check_env_refuses_a_local_provider_and_counts_duplicates_once(tmp_path, capsys):
    code, out = _check_env_run(tmp_path, capsys, _GOOD_ENV.replace("SMS_BACKEND=twilio\n", "SMS_BACKEND=console\n"))
    assert code != 0 and "liste ordonnée" in out
    code, out = _check_env_run(tmp_path, capsys, _GOOD_ENV.replace("SMS_BACKEND=twilio\n", "SMS_BACKEND=twilio,twilio\n"))
    assert code == 0 and "un seul fournisseur (twilio)" in out  # « twilio,twilio » n'est PAS une relève


def test_app_and_worker_reach_the_public_minio_host_from_inside_the_containers():
    """Les URL signées pointent vers l'hôte PUBLIC de MinIO ; depuis un conteneur, l'IP publique du serveur n'est souvent pas joignable (timeout de
    60 s, 500 dans l'administration). L'API et le worker résolvent donc ce nom vers la passerelle de l'hôte, où Traefik écoute sur 443."""
    import yaml

    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    for name in ("tratraweb", "worker"):
        assert "${MINIO_API_HOST}:host-gateway" in services[name].get("extra_hosts", []), name
