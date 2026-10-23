"""Adresse IP réelle du client derrière le reverse proxy (Traefik).

Pourquoi : sans proxy de confiance déclaré, `REMOTE_ADDR` est l'adresse du PROXY. Axes (verrouillage après échecs de connexion) et la liste
noire d'IP comptaient alors TOUS les visiteurs comme une seule personne (5 échecs de n'importe qui = connexion bloquée pour tout le monde),
et lire l'en-tête `X-Forwarded-For` en entier permettait au client de choisir lui-même son adresse (contournement des limites).

Règle : `TRUSTED_PROXY_COUNT` reverse proxies de confiance (Traefik = 1) ajoutent chacun l'adresse de leur interlocuteur À LA FIN de
`X-Forwarded-For` ; seule l'entrée posée par notre dernier proxy est fiable, jamais celles écrites par le client (à gauche).
`TRUSTED_PROXY_COUNT=0` (poste de développement, accès direct) : on ignore `X-Forwarded-For` et on prend `REMOTE_ADDR`.
C'est la même règle que `NUM_PROXIES` de Django REST framework (limitation de débit)."""
import ipaddress

from django.conf import settings


def _valid(value: str):
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request) -> str:
    remote = (request.META.get("REMOTE_ADDR") or "").strip()
    count = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0) or 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if count <= 0 or not forwarded:
        return remote
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    if not hops:
        return remote
    return _valid(hops[-min(count, len(hops))]) or remote


# ---- Derrière Cloudflare (proxy « nuage orange ») ------------------------------------------------------------------------------
# Traefik réécrit X-Forwarded-For avec l'adresse de son interlocuteur : derrière Cloudflare, c'est un serveur de Cloudflare, et toutes
# les limites par IP (inscriptions, codes SMS, connexions, Axes, DRF) compteraient Cloudflare au lieu du visiteur. Cloudflare transmet
# l'adresse réelle dans `CF-Connecting-IP` : elle n'est crue QUE si la requête arrive effectivement d'une adresse de Cloudflare (sinon
# n'importe qui pourrait l'écrire en appelant le serveur directement). Activé par `CLOUDFLARE_PROXY=true`.
CLOUDFLARE_RANGES = (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18",
    "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
)   # https://www.cloudflare.com/ips/ (octobre 2026) ; remplaçable par CLOUDFLARE_IP_RANGES
_networks_cache = {}


def _cloudflare_networks():
    raw = tuple(getattr(settings, "CLOUDFLARE_IP_RANGES", None) or CLOUDFLARE_RANGES)
    if raw not in _networks_cache:
        nets = []
        for item in raw:
            try:
                nets.append(ipaddress.ip_network(str(item).strip(), strict=False))
            except ValueError:
                continue
        _networks_cache.clear()
        _networks_cache[raw] = nets
    return _networks_cache[raw]


def is_cloudflare(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False
    return any(addr in net for net in _cloudflare_networks())


class CloudflareClientIPMiddleware:
    """Remplace l'adresse « proxy de confiance » par celle du visiteur (`CF-Connecting-IP`) quand la requête vient de Cloudflare :
    `client_ip`, Axes et les limites de débit de DRF lisent alors la même adresse réelle. Sans effet si CLOUDFLARE_PROXY est faux."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "CLOUDFLARE_PROXY", False):
            visitor = _valid(request.META.get("HTTP_CF_CONNECTING_IP", "") or "")
            if visitor and is_cloudflare(client_ip(request)):
                request.META["HTTP_X_FORWARDED_FOR"] = visitor
                if int(getattr(settings, "TRUSTED_PROXY_COUNT", 0) or 0) <= 0:
                    request.META["REMOTE_ADDR"] = visitor
        return self.get_response(request)
