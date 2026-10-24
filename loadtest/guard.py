"""Garde-fous des tests de charge : refus net (exception) au moindre doute — jamais la production, jamais un SMS ni un push réel.

Vérifié au démarrage de l'application `loadtest` (apps.py) et de nouveau par chaque commande avant d'écrire quoi que ce soit."""
import os
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", ""}
# Noms d'hôte de la production : jamais une cible, quelle que soit l'option passée.
PRODUCTION_HOSTS = ("tratra.net", "www.tratra.net", "api.tratra.net")


def problems() -> list:
    """Liste des raisons de refuser (vide = environnement de mesure sûr)."""
    from handy import push, sms

    out = []
    if os.environ.get("DJANGO_ENV") != "loadtest":
        out.append("DJANGO_ENV doit valoir « loadtest » (réglages tratra/settings/loadtest.py).")
    db = settings.DATABASES["default"]
    if not str(db.get("NAME") or "").startswith(("tratra_loadtest", "test_tratra_loadtest")):
        out.append(f"Base « {db.get('NAME')} » refusée : seule une base « tratra_loadtest… » jetable est autorisée.")
    if str(db.get("HOST") or "") not in LOCAL_HOSTS:
        out.append(f"Serveur de base « {db.get('HOST')} » refusé : base locale uniquement.")
    if settings.DEBUG:
        out.append("DEBUG doit être coupé (il garde chaque requête SQL en mémoire et fausse les mesures).")
    if getattr(settings, "SMS_ENABLED", True):
        out.append("SMS_ENABLED doit être faux.")
    if sms.backend_names():
        out.append(f"Fournisseur SMS actif ({sms.backend_name()}) : aucun SMS n'est permis pendant les mesures.")
    if push.is_configured():
        out.append("Push FCM configuré : aucun push réel n'est permis pendant les mesures.")
    return out


def assert_safe() -> None:
    issues = problems()
    if issues:
        raise ImproperlyConfigured("Tests de charge refusés : " + " ".join(issues))


def check_target(url: str, *, allow_hosts=()) -> str:
    """Hôte d'une cible HTTP/WebSocket : locale, ou explicitement autorisée ET jamais la production. Renvoie l'hôte."""
    host = (urlsplit(url).hostname or "").lower()
    if host in PRODUCTION_HOSTS or host.endswith(".tratra.net") and not host.split(".")[0].startswith(("staging", "recette")):
        raise ValueError(f"Cible « {host} » refusée : aucun test de charge sur la production.")
    if host in LOCAL_HOSTS or host.endswith((".localhost", ".test")) or host in allow_hosts:
        return host
    raise ValueError(f"Cible « {host} » non autorisée (locale par défaut ; --allow-host pour un environnement de recette).")
