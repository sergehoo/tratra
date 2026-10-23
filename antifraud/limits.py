"""Compteurs ATOMIQUES à fenêtre fixe (limites de débit et quotas), sur le cache partagé (Redis en production).

`cache.add` (SET NX) crée le compteur de la fenêtre, `cache.incr` (INCRBY) l'augmente atomiquement : deux requêtes simultanées ne
peuvent jamais lire la même valeur, quel que soit le nombre de processus ou de serveurs. Un cache local par processus (LocMem) ne
protège qu'un seul processus : la production exige Redis (tratra/settings/prod.py).

`fail_open` : si le cache est injoignable, la limite laisse passer (inscription) ou refuse (envoi de SMS : jamais de dépense sans
compteur fiable)."""
from __future__ import annotations

import hashlib
import logging
import time

from django.core.cache import cache

logger = logging.getLogger(__name__)


class LimitUnavailable(Exception):
    """Cache injoignable : aucune limite ne peut être garantie."""


def digest(value: str) -> str:
    """Empreinte courte d'une valeur personnelle (numéro, IP) pour les clés du cache : jamais la valeur en clair."""
    return hashlib.sha256((value or "").encode()).hexdigest()[:24]


def _key(name: str, window: int, now: float) -> str:
    return f"rl:{name}:{window}:{int(now // window)}"


def hit(name: str, limit: int, window: int, *, cost: int = 1, now: float | None = None) -> tuple[bool, int]:
    """Compte `cost` pour `name` dans la fenêtre courante de `window` secondes. Renvoie (autorisé, total de la fenêtre).
    `limit` <= 0 : aucune limite (rien n'est compté). Lève LimitUnavailable si le cache ne répond pas."""
    if limit <= 0:
        return True, 0
    now = time.time() if now is None else now
    key = _key(name, window, now)
    try:
        cache.add(key, 0, timeout=window + 60)
        try:
            total = cache.incr(key, cost)
        except ValueError:                       # expiré entre add et incr : on repart de cette requête
            cache.add(key, 0, timeout=window + 60)
            total = cache.incr(key, cost)
    except Exception as exc:  # noqa: BLE001 - Redis indisponible
        logger.error("Compteur %s indisponible (%s).", name.split(":")[0], type(exc).__name__)
        raise LimitUnavailable(str(type(exc).__name__)) from None
    return total <= limit, total


def peek(name: str, window: int, *, now: float | None = None) -> int:
    now = time.time() if now is None else now
    try:
        return int(cache.get(_key(name, window, now)) or 0)
    except Exception:  # noqa: BLE001
        return 0


def retry_after(window: int, *, now: float | None = None) -> int:
    """Secondes avant la fenêtre suivante."""
    now = time.time() if now is None else now
    return max(1, int(window - (now % window)))


def attempt(key: str, window: int) -> int:
    """Compte UNE tentative (ex. saisie de code) et renvoie son rang dans la fenêtre glissante de `window` secondes depuis la
    première : à appeler AVANT de vérifier quoi que ce soit, si bien que des essais simultanés ne peuvent jamais dépasser la limite.
    Lève LimitUnavailable si le cache ne répond pas."""
    try:
        cache.add(key, 0, timeout=window)
        try:
            return int(cache.incr(key))
        except ValueError:
            cache.add(key, 0, timeout=window)
            return int(cache.incr(key))
    except Exception as exc:  # noqa: BLE001
        raise LimitUnavailable(type(exc).__name__) from None


def reset(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:  # noqa: BLE001
        pass

