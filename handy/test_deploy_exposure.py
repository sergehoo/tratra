"""Exposition réseau : ni Adminer ni la console MinIO ne sont routés par Traefik ; base, Redis et MinIO ne publient aucun port."""
import re
from pathlib import Path

import pytest

from handy.test_deploy_config import _compose

ROOT = Path(__file__).resolve().parent.parent
COMPOSES = ["docker-compose.yml", "docker-compose.staging.yml"]


def _labels(svc):
    raw = svc.get("labels") or []
    return [raw] if isinstance(raw, str) else list(raw if isinstance(raw, list) else [f"{k}={v}" for k, v in raw.items()])


@pytest.mark.parametrize("name", COMPOSES)
def test_aucune_route_traefik_pour_adminer_ni_la_console_minio(name):
    compose = _compose(name)
    for svc_name, svc in compose["services"].items():
        for label in _labels(svc):
            low = str(label).lower()
            assert "adminer" not in low, f"{name}/{svc_name}: route Adminer ({label})"
            assert "console" not in low, f"{name}/{svc_name}: route console ({label})"
            assert not re.search(r"server\.port=9001\b", low), f"{name}/{svc_name}: port 9001 exposé ({label})"


@pytest.mark.parametrize("name", COMPOSES)
def test_adminer_est_un_outil_a_la_demande_sans_port_ni_reseau_proxy(name):
    compose = _compose(name)
    adminers = {n: s for n, s in compose["services"].items() if "adminer" in n}
    assert adminers, f"{name}: service Adminer attendu (profil tools)"
    for svc_name, svc in adminers.items():
        assert "tools" in (svc.get("profiles") or []), f"{svc_name}: doit rester derrière le profil « tools »"
        assert not svc.get("ports"), f"{svc_name}: aucun port publié"
        nets = svc.get("networks") or []
        assert "proxy" not in (nets if isinstance(nets, (list, dict)) else []), f"{svc_name}: ne doit pas être sur le réseau partagé avec Traefik"
        assert not _labels(svc), f"{svc_name}: aucune étiquette Traefik"


@pytest.mark.parametrize("name", COMPOSES)
def test_l_api_s3_de_minio_reste_servie_et_les_donnees_ne_publient_aucun_port(name):
    compose = _compose(name)
    minio = next(s for n, s in compose["services"].items() if re.fullmatch(r"minio(-stg)?", n))
    assert any(re.search(r"server\.port=9000\b", str(l)) for l in _labels(minio)), "l'API S3 (signatures temporaires) doit rester routée"
    assert "--console-address" in " ".join(minio["command"]) if isinstance(minio["command"], list) else "--console-address" in minio["command"]
    for svc_name, svc in compose["services"].items():
        image = str(svc.get("image", ""))
        if image.startswith(("postgis/", "postgres", "redis")) or "minio" in svc_name or "tratradb" in svc_name:
            assert not svc.get("ports"), f"{name}/{svc_name}: aucun port publié sur l'hôte"
        if image.startswith(("postgis/", "postgres", "redis")) or "tratradb" in svc_name:
            nets = svc.get("networks") or []
            assert "proxy" not in nets, f"{name}/{svc_name}: base de données / Redis jamais sur le réseau du proxy"


def test_les_exemples_d_environnement_ne_demandent_plus_d_hote_public_pour_ces_outils():
    for example in (".env.example", ".env.staging.example"):
        text = (ROOT / example).read_text(encoding="utf-8")
        for var in ("MINIO_CONSOLE_HOST", "ADMINER_HOST", "ADMINER_AUTH_SUFFIX", "BASIC_AUTH_USERS"):
            assert not re.search(rf"^{var}=", text, re.M), f"{example}: {var} ne doit plus exister"
