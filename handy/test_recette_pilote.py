"""Recette du PILOTE, rejouée sans réseau : le MÊME scénario que `scripts/pilot/recette_api.py` (client → réservation → artisan → mission →
messages → espèces → avis, puis contrat de longue durée), exécuté sur l'API réelle (JWT, throttles, idempotence, permissions) — mais dans la
suite de tests. Si ce test passe, la recette HTTP contre une vraie pile ne peut échouer que pour des raisons d'environnement (comptes, OTP, KYC,
configuration), jamais pour un défaut de parcours."""
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from engagements import tasks as engagement_tasks
from handy.models import User
from handy.test_eligibility import artisan, service

pytestmark = pytest.mark.django_db
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pilot" / "recette_api.py"
spec = importlib.util.spec_from_file_location("recette_api", SCRIPT)
recette_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recette_api)
PASSWORD = "Tr4tra!Recette-2026"


class DjangoTransport:
    """Même interface que `HttpTransport`, branchée sur le client de test DRF (aucun réseau)."""

    def __init__(self):
        self.c = APIClient()

    def request(self, method, path, *, json_body=None, fields=None, files=None, headers=None, token=None):
        extra = {"HTTP_" + k.upper().replace("-", "_"): v for k, v in (headers or {}).items()}
        if token:
            extra["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        call = getattr(self.c, method.lower())
        url = "/handy" + path
        if files is not None:
            data = {**(fields or {}), **{k: SimpleUploadedFile(name, content, content_type=ctype) for k, (name, content, ctype) in files.items()}}
            r = call(url, data, format="multipart", **extra)
        elif json_body is not None:
            r = call(url, json_body, format="json", **extra)
        else:
            r = call(url, **extra)
        raw = b"".join(r.streaming_content) if getattr(r, "streaming", False) else r.content
        ctype = r.get("Content-Type", "")
        return recette_api.Resp(r.status_code, r.json() if ctype.startswith("application/json") else None, dict(r.items()), raw)


@pytest.fixture(autouse=True)
def _fresh():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def accounts():
    client = User.objects.create_user("rc_client", "rcc@x.test", PASSWORD, user_type="client", is_verified=True, first_name="Awa", last_name="Recette")
    pro = artisan("rc_artisan")
    pro.set_password(PASSWORD)
    pro.first_name = "Moussa"
    pro.save()
    service(pro)
    return client, pro


def build(accounts, **over):
    today = timezone.localdate()
    log = []
    r = recette_api.Recette(DjangoTransport(), ("rc_client", over.get("pw", PASSWORD)), ("rc_artisan", PASSWORD), today=today, log=log.append,
                            tick=lambda: engagement_tasks.run(today + timedelta(days=1)))
    return r, log


def test_the_whole_pilot_recette_passes_on_the_real_api(accounts):
    r, log = build(accounts)
    results = r.run("all")
    failed = [label for label, ok, _ in results if not ok]
    assert failed == [] and len(results) >= 45, "\n".join(log[-12:])
    text = "\n".join(log)
    assert "Réservation : client → artisan → mission" in text and "Contrat de longue durée" in text and "ÉCHEC" not in text
    assert "à faire" not in text                                   # le tick a généré l'échéance : aucune étape laissée à vérifier
    # Jamais « vérifié par un prestataire » dans cette recette (aucun prestataire n'est impliqué).
    assert all("provider_verified" not in str(ok) for _, ok, _ in results)


def test_the_booking_and_contract_journeys_can_run_separately(accounts):
    r, _ = build(accounts)
    assert all(ok for _, ok, _ in r.run("booking"))
    r2, _ = build(accounts)
    assert all(ok for _, ok, _ in r2.run("contract"))


def test_a_wrong_password_fails_loudly_at_the_login_step_without_leaking_it(accounts):
    r, log = build(accounts, pw="mauvais-mot-de-passe-2026")
    with pytest.raises(recette_api.RecetteFailure) as e:
        r.run("all")
    assert "connexion client" in str(e.value)
    assert "mauvais-mot-de-passe-2026" not in "\n".join(log)


def test_the_contract_journey_does_not_depend_on_the_hourly_tick(accounts):
    """Les échéances sont générées dès l'acceptation : la recette se déroule entièrement sans attendre la tâche horaire `engagements-tick`
    (qui sert aux rappels, renouvellements et au rattrapage). Si une échéance manquait, le script le dit au lieu d'afficher un faux succès."""
    today = timezone.localdate()
    log = []
    r = recette_api.Recette(DjangoTransport(), ("rc_client", PASSWORD), ("rc_artisan", PASSWORD), today=today, log=log.append, tick=None)
    results = r.run("contract")
    assert all(ok for _, ok, _ in results) and not any("NON vérifiées" in line for line in log)


def test_the_script_refuses_unsafe_or_incomplete_invocations(monkeypatch, capsys):
    monkeypatch.delenv("RECETTE_CLIENT", raising=False)
    assert recette_api.main(["--api", "http://api.exemple.ci/handy"]) == 2                    # HTTP en clair hors localhost
    assert recette_api.main(["--api", "https://api.exemple.ci/handy"]) == 2                   # comptes de recette non fournis
    assert "RECETTE_PASSWORD" in capsys.readouterr().err
