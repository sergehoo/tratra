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
