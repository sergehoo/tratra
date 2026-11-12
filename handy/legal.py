"""Conditions d'utilisation : version en vigueur et acceptation EXPLICITE, enregistrée côté serveur.

Source unique côté serveur de la version en vigueur. La page publique `/conditions-utilisation` du site affiche la même version
(`frontend/src/lib/legal.ts`) : `handy/test_terms.py` vérifie que les deux concordent. Publier de nouvelles conditions = changer
`TERMS_VERSION` et `TERMS_UPDATED_ON` ici ET dans `legal.ts`, dans le même commit.

Garanties :
- une version n'est enregistrée sur un compte que si la personne a coché la case (inscription) ou appuyé sur « J'accepte » (compte
  existant) ET que l'application ou le site a annoncé CETTE version précise : jamais d'acceptation déduite, rétroactive ou par défaut ;
- une inscription qui annonce une version périmée est refusée (`terms_outdated`) : la personne relit les nouvelles conditions et recoche ;
- les comptes antérieurs gardent leur date d'acceptation d'origine et une version vide (« acceptées avant le versionnage ») ; une
  nouvelle version ne bloque aucun compte existant, elle leur est proposée (voir `status`) ;
- chaque acceptation est journalisée (audit `account.terms_accepted` : version, origine).
"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

TERMS_VERSION = "2026-11-12"
TERMS_UPDATED_ON = "2026-11-12"
TERMS_PATH = "/conditions-utilisation"


class TermsOutdated(Exception):
    """La version annoncée par le client n'est pas (ou plus) celle en vigueur."""


def current() -> dict:
    return {"version": TERMS_VERSION, "updated_on": TERMS_UPDATED_ON,
            "url": f"{getattr(settings, 'PUBLIC_WEB_URL', '').rstrip('/')}{TERMS_PATH}", "path": TERMS_PATH}


def status(user) -> dict:
    """Version acceptée par le compte et version en vigueur. `needs_acceptance` : à proposer à la personne, jamais bloquant."""
    accepted = user.terms_version or None
    return {"current": current(), "accepted_version": accepted, "accepted_at": user.terms_accepted_at,
            "up_to_date": accepted == TERMS_VERSION, "needs_acceptance": accepted != TERMS_VERSION}


def check_announced(version) -> str:
    """Version annoncée par le client (texte affiché à la personne). Vide = client antérieur au versionnage (aucune version enregistrée)."""
    version = str(version or "").strip()
    if version and version != TERMS_VERSION:
        raise TermsOutdated(version)
    return version


@transaction.atomic
def record_acceptance(user, version, *, source: str) -> bool:
    """Acceptation explicite de la version en vigueur par un compte existant. Rejouée sur la même version : rien ne change (la
    date d'origine est conservée). Retourne vrai si une nouvelle acceptation a été enregistrée."""
    from trust.models import audit

    if check_announced(version) != TERMS_VERSION:
        raise TermsOutdated(version)
    locked = type(user).objects.select_for_update().get(pk=user.pk)
    if locked.terms_version == TERMS_VERSION:
        user.terms_version, user.terms_accepted_at = locked.terms_version, locked.terms_accepted_at
        return False
    now = timezone.now()
    type(user).objects.filter(pk=user.pk).update(terms_version=TERMS_VERSION, terms_accepted_at=now)
    user.terms_version, user.terms_accepted_at = TERMS_VERSION, now
    audit("account.terms_accepted", actor=user, target=user, version=TERMS_VERSION, source=source,
          previous_version=locked.terms_version or None,
          previous_accepted_at=locked.terms_accepted_at.isoformat() if locked.terms_accepted_at else None)
    return True
