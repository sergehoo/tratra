"""Derrière Cloudflare : l'adresse réelle du visiteur (CF-Connecting-IP) n'est crue que si la requête arrive d'une adresse Cloudflare ;
sinon (appel direct du serveur) l'en-tête est ignoré. Limites par IP, Axes et DRF voient la même adresse."""
import pytest
from django.test import RequestFactory
from rest_framework.throttling import AnonRateThrottle
from rest_framework.request import Request

from handy.security import CloudflareClientIPMiddleware, client_ip, is_cloudflare


def _through(meta, settings):
    request = RequestFactory().get("/handy/catalog/", **meta)
    seen = {}

    def view(req):
        seen["ip"] = client_ip(req)
        seen["drf"] = AnonRateThrottle().get_ident(Request(req))
        return None
    CloudflareClientIPMiddleware(view)(request)
    return seen


@pytest.fixture
def behind_traefik(settings):
    settings.TRUSTED_PROXY_COUNT = 1
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    settings.CLOUDFLARE_PROXY = True
    return settings


def test_cloudflare_ranges():
    assert is_cloudflare("172.64.10.1") and is_cloudflare("2606:4700::1")
    assert not is_cloudflare("203.0.113.9") and not is_cloudflare("pas-une-ip")


def test_the_visitor_address_is_used_when_the_request_comes_from_cloudflare(behind_traefik):
    seen = _through({"REMOTE_ADDR": "10.0.0.2", "HTTP_X_FORWARDED_FOR": "172.64.10.1", "HTTP_CF_CONNECTING_IP": "196.47.1.20"},
                    behind_traefik)
    assert seen == {"ip": "196.47.1.20", "drf": "196.47.1.20"}


def test_a_forged_header_sent_directly_to_the_server_is_ignored(behind_traefik):
    seen = _through({"REMOTE_ADDR": "10.0.0.2", "HTTP_X_FORWARDED_FOR": "203.0.113.9", "HTTP_CF_CONNECTING_IP": "1.2.3.4"},
                    behind_traefik)
    assert seen["ip"] == "203.0.113.9"
    bad = _through({"REMOTE_ADDR": "10.0.0.2", "HTTP_X_FORWARDED_FOR": "172.64.10.1", "HTTP_CF_CONNECTING_IP": "<script>"}, behind_traefik)
    assert bad["ip"] == "172.64.10.1"


def test_disabled_by_default(settings):
    settings.TRUSTED_PROXY_COUNT = 1
    settings.CLOUDFLARE_PROXY = False
    seen = _through({"REMOTE_ADDR": "10.0.0.2", "HTTP_X_FORWARDED_FOR": "172.64.10.1", "HTTP_CF_CONNECTING_IP": "196.47.1.20"}, settings)
    assert seen["ip"] == "172.64.10.1"
