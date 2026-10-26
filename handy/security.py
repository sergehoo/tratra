"""Adresse IP réelle du client derrière le reverse proxy (Traefik).

Pourquoi : sans proxy de confiance déclaré, `REMOTE_ADDR` est l'adresse du PROXY. Axes (verrouillage après échecs de connexion) et la liste
noire d'IP comptaient alors TOUS les visiteurs comme une seule personne (5 échecs de n'importe qui = connexion bloquée pour tout le monde),
et lire l'en-tête `X-Forwarded-For` en entier permettait au client de choisir lui-même son adresse (contournement des limites).

Règle : `TRUSTED_PROXY_COUNT` reverse proxies de confiance (Traefik = 1) ajoutent chacun l'adresse de leur interlocuteur À LA FIN de
`X-Forwarded-For` ; seule l'entrée posée par notre dernier proxy est fiable, jamais celles écrites par le client (à gauche).
`TRUSTED_PROXY_COUNT=0` (poste de développement, accès direct) : on ignore `X-Forwarded-For` et on prend `REMOTE_ADDR`.
C'est la même règle que `NUM_PROXIES` de Django REST framework (limitation de débit)."""
import ipaddress
import re

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import JsonResponse


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


# ---- Hôte d'envoi direct des fichiers de l'application (UPLOAD_HOST) ----------------------------------------------------------
# Sur certains réseaux (Wi-Fi d'entreprise), les envois de fichiers d'un téléphone vers Cloudflare sont coupés au bout de 15 s alors que
# le même envoi passe en direct vers le serveur (mesuré le 26 oct. 2026 sur un Galaxy S10+ : 0 envoi sur 3 par Cloudflare, 3 sur 3 en
# direct, corps lu en entier). L'application envoie donc ses fichiers par un hôte en « DNS seulement » qui sert la même API. Cet hôte
# échappe aux règles de Cloudflare : il n'accepte QUE les envois de fichiers de l'application (multipart, chemins ci-dessous, mêmes
# authentification et contrôles que d'habitude) ; connexion, codes SMS et tout le reste y répondent 404 et restent derrière Cloudflare.
# Un nouvel envoi de fichier de l'application s'ajoute ici (test : handy/test_upload_host.py).
UPLOAD_PATHS = tuple(re.compile(p) for p in (
    r"^/handy/statuses/$",                                         # statut photo ou vidéo
    r"^/handy/me/conversations/\d+/send/$",                        # pièce jointe d'un message
    r"^/handy/me/kyc/capture/$",                                   # photo de pièce d'identité
    r"^/handy/kyc/biometric/sessions/\d+/captures/$",              # vérification faciale
    r"^/handy/handyman-docs/$",                                    # justificatif professionnel
    r"^/handy/bookings/\d+/payment/cash/$",                        # reçu d'un paiement en espèces
    r"^/handy/reviews/\d+/photos/$",                               # photo d'un avis
    r"^/handy/users/\d+/$",                                        # photo de profil
    r"^/handy/handymen/\d+/$",                                     # photo du professionnel
    r"^/handy/engagements/installments/\d+/(payments|lines)/$",    # justificatif d'un engagement
))
UPLOAD_METHODS = ("POST", "PATCH", "PUT")


def _request_host(request) -> str:
    try:
        return request.get_host().rsplit(":", 1)[0].lower()
    except DisallowedHost:
        return ""                         # hôte inconnu : Django le refusera lui-même plus loin


def is_upload_request(request) -> bool:
    if request.method == "GET" and request.path_info == "/healthz":
        return True                       # vérification de la route d'envoi (Traefik, certificat)
    content_type = (request.META.get("CONTENT_TYPE") or "").lower()
    return (request.method in UPLOAD_METHODS and content_type.startswith("multipart/form-data")
            and any(p.match(request.path_info) for p in UPLOAD_PATHS))


class UploadHostMiddleware:
    """Sur l'hôte d'envoi direct : envois de fichiers de l'application seulement (404 sinon). Une requête admise est ensuite traitée sous
    l'hôte public de l'API (API_PUBLIC_HOST), pour que les liens absolus des réponses ne pointent jamais vers l'hôte d'envoi."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        upload_host = getattr(settings, "UPLOAD_HOST", "")
        if upload_host and _request_host(request) == upload_host:
            if not is_upload_request(request):
                refused = JsonResponse({"detail": "Adresse réservée aux envois de fichiers de l'application.", "code": "upload_host_only"},
                                       status=404)
                refused["X-Upload-Host"] = "refused"     # l'application repasse alors par l'API habituelle
                return refused
            api_host = getattr(settings, "API_PUBLIC_HOST", "")
            if api_host and api_host in settings.ALLOWED_HOSTS:
                request.META["HTTP_HOST"] = api_host
                request.META.pop("HTTP_X_FORWARDED_HOST", None)
        return self.get_response(request)
