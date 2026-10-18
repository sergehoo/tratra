"""IP réelle du client derrière Traefik : verrouillage de connexion PAR CLIENT (et non pour tout le monde), liste noire non contournable."""
import pytest
from django.core.cache import cache
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient

from handy.models import IPBlacklist, User
from handy.security import client_ip

pytestmark = pytest.mark.django_db
PROXY = "10.0.0.2"          # adresse du reverse proxy (REMOTE_ADDR vu par l'application)
LOGIN = "/handy/auth/login/"


def _req(xff=None, remote=PROXY):
    extra = {"REMOTE_ADDR": remote}
    if xff is not None:
        extra["HTTP_X_FORWARDED_FOR"] = xff
    return RequestFactory().get("/", **extra)


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_une_seule_entree_est_fiable_celle_posee_par_notre_proxy():
    assert client_ip(_req("198.51.100.7")) == "198.51.100.7"
    assert client_ip(_req("6.6.6.6, 198.51.100.7")) == "198.51.100.7"            # le client écrit à gauche : ignoré
    assert client_ip(_req("6.6.6.6,7.7.7.7 , 198.51.100.7")) == "198.51.100.7"
    assert client_ip(_req("2001:db8::1")) == "2001:db8::1"
    assert client_ip(_req(None)) == PROXY                                       # accès sans en-tête : adresse de la connexion
    assert client_ip(_req("n'importe quoi")) == PROXY                           # entrée illisible : jamais prise telle quelle
    assert client_ip(_req("")) == PROXY


@override_settings(TRUSTED_PROXY_COUNT=0)
def test_sans_proxy_de_confiance_l_en_tete_est_ignore():
    assert client_ip(_req("1.2.3.4", remote="203.0.113.9")) == "203.0.113.9"


@override_settings(TRUSTED_PROXY_COUNT=2)
def test_deux_proxies_de_confiance():
    assert client_ip(_req("6.6.6.6, 198.51.100.7, 10.1.1.1")) == "198.51.100.7"


def test_la_limitation_de_debit_utilise_la_meme_regle(settings):
    from django.conf import settings as s
    assert s.REST_FRAMEWORK["NUM_PROXIES"] == s.TRUSTED_PROXY_COUNT
    assert s.AXES_CLIENT_IP_CALLABLE == "handy.security.client_ip"


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_cinq_echecs_bloquent_ce_client_mais_pas_les_autres():
    """Avant : toutes les requêtes venaient de l'adresse du proxy ; 5 échecs d'un inconnu bloquaient la connexion de TOUS les membres."""
    User.objects.create_user("membre_ok", password="Secret-Ok-123", phone="+2250700777001")
    attacker = APIClient()
    for i in range(6):
        # l'attaquant change d'« adresse » à gauche à chaque essai : sans effet, seule l'entrée du proxy compte
        r = attacker.post(LOGIN, {"username": f"cible{i}", "password": "faux"}, format="json",
                          REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=f"1.1.1.{i}, 203.0.113.5")
    assert r.status_code != 200
    # verrouillé : même avec le BON mot de passe, ce client n'entre plus (l'API répond comme pour un échec ordinaire)
    locked = attacker.post(LOGIN, {"username": "membre_ok", "password": "Secret-Ok-123"}, format="json",
                           REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.5")
    assert locked.status_code != 200 and "access" not in locked.json()
    honest = APIClient().post(LOGIN, {"username": "membre_ok", "password": "Secret-Ok-123"}, format="json",
                              REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR="198.51.100.7")
    assert honest.status_code == 200 and "access" in honest.json()              # un autre client n'est pas touché


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_liste_noire_non_contournable_par_en_tete_forge():
    IPBlacklist.objects.create(ip_address="9.9.9.9", is_active=True)
    c = APIClient()
    blocked = c.get("/handy/public/stats/", REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR="9.9.9.9")
    assert blocked.status_code == 403
    forged_innocent = c.get("/handy/public/stats/", REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR="1.1.1.1, 9.9.9.9")
    assert forged_innocent.status_code == 403                                   # écrire une autre adresse à gauche n'efface pas la vraie
    framed = c.get("/handy/public/stats/", REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR="9.9.9.9, 1.1.1.1")
    assert framed.status_code != 403                                            # et on ne peut pas faire bloquer un tiers en écrivant son IP à gauche
