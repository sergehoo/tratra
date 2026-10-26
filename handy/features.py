"""Fonctions récentes qu'un message peut annoncer ou ouvrir (campagnes d'engagement, annonces) — et quels téléphones savent les afficher.

Le serveur et le site sont livrés ensemble : une fonction de ce registre est en ligne côté serveur et web dès que cette version est
déployée. L'application mobile, elle, n'est à jour que lorsque chaque utilisateur l'a mise à jour : elle annonce au serveur les
fonctions dont elle a l'écran (capacités de l'appareil, POST /devices/, mêmes codes qu'ici — lib/services/push_service.dart).

D'où deux règles, appliquées par le moteur des campagnes et par l'envoi des push :
 - un message qui conduit à une fonction ne vise que les comptes qui peuvent l'ouvrir : au moins un téléphone dont l'application la
   connaît, ou aucun téléphone (compte qui n'utilise que le site). Les autres l'attendent : ils le recevront après leur mise à jour ;
 - son push ne part que vers les téléphones à jour (jamais un bouton qui n'ouvre rien sur une ancienne version).

Toute nouvelle fonction annoncée s'ajoute ici ET dans l'application (tests : handy/test_features.py, test/push_test.dart)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set

MOBILE = ("android", "ios")


@dataclass(frozen=True)
class Feature:
    code: str
    label: str
    destinations: tuple = ()     # écrans du registre central (handy.destinations) qui relèvent de cette fonction


FEATURES = (
    Feature("flash", "« Trouvez-moi un professionnel » (Tratra Flash)", ("flash_order",)),
    Feature("favorites", "Professionnels favoris", ("favorites",)),
    Feature("tratra_id", "Badge Tratra ID", ("badge",)),
    Feature("engagements", "Engagements longue durée", ("engagements",)),
    Feature("panne", "« J'ai une panne »", ("panne",)),
    Feature("catalogue_families", "Familles de métiers", ()),
    Feature("service_modes", "Modes des offres (contrat au mois)", ()),
)
BY_CODE: Dict[str, Feature] = {f.code: f for f in FEATURES}
DESTINATION_FEATURE: Dict[str, str] = {d: f.code for f in FEATURES for d in f.destinations}


def label(code: str) -> str:
    feature = BY_CODE.get(code)
    return feature.label if feature else code


def for_destination(value: str) -> Set[str]:
    """Fonction dont relève l'écran ouvert par un lien (`panne`, `badge`, `flash_order`…) ; vide pour un écran de toujours."""
    key = (value or "").split("/", 1)[0]
    return {DESTINATION_FEATURE[key]} if key in DESTINATION_FEATURE else set()


def unknown(codes: Iterable[str]) -> List[str]:
    return sorted(c for c in codes if c and c not in BY_CODE)


def device_ready(capabilities, features: Iterable[str]) -> bool:
    return set(features) <= set(capabilities or [])


def reachable_user_ids(user_ids: Iterable[int], features: Iterable[str]) -> Set[int]:
    """Comptes qui peuvent ouvrir ces fonctions : un téléphone dont l'application les connaît toutes, ou aucun téléphone (site)."""
    ids, needed = set(user_ids), set(features)
    if not needed or not ids:
        return ids
    from handy.models import Device

    phones, ready = set(), set()
    for uid, caps in Device.objects.filter(user_id__in=ids, device_type__in=MOBILE).values_list("user_id", "capabilities"):
        phones.add(uid)
        if device_ready(caps, needed):
            ready.add(uid)
    return (ids - phones) | ready


def adoption(features: Iterable[str]) -> Dict[str, int]:
    """Téléphones enregistrés et, parmi eux, ceux dont l'application connaît ces fonctions (Back-Office)."""
    from handy.models import Device

    needed = sorted(set(features))
    phones = Device.objects.filter(device_type__in=MOBILE)
    total = phones.count()
    return {"phones": total, "ready": phones.filter(capabilities__contains=needed).count() if needed else total}
