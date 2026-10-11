"""Adresses d'un compte : validation, adresse principale unique, miroir vers les champs historiques du compte.

Règles : la première adresse devient principale ; supprimer la principale promeut la plus récente ; les coordonnées issues de la position
de l'appareil exigent un consentement explicite ; 10 adresses au maximum ; jamais de donnée d'un autre compte."""
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

from django.db import transaction
from django.utils import timezone

from handy.models import User, UserAddress

TEXT_FIELDS = {"label": 60, "country": 80, "city": 100, "commune": 100, "street": 255, "complement": 255}


class AddressError(ValueError):
    def __init__(self, errors: Dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def _coord(raw, low: float, high: float, name: str, errors: Dict[str, str]) -> Optional[Decimal]:
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError):
        errors[name] = "Coordonnée invalide."
        return None
    if not (Decimal(str(low)) <= value <= Decimal(str(high))):
        errors[name] = "Coordonnée hors limites."
        return None
    return value


def clean(data: Dict, *, partial: bool = False) -> Dict:
    """Valide et normalise une adresse ; lève `AddressError` avec un message par champ."""
    errors: Dict[str, str] = {}
    out: Dict = {}
    for name, size in TEXT_FIELDS.items():
        if name in data:
            value = str(data.get(name) or "").strip()
            if len(value) > size:
                errors[name] = f"{size} caractères maximum."
            out[name] = value
    if "country" in out and not out["country"]:
        out["country"] = "Côte d'Ivoire"
    if not partial:
        out.setdefault("country", "Côte d'Ivoire")
        if not out.get("city"):
            errors["city"] = "La ville est obligatoire."
        if not (out.get("street") or out.get("commune")):
            errors["street"] = "Indiquez la rue ou le quartier."
    elif "city" in out and not out["city"]:
        errors["city"] = "La ville est obligatoire."
    if "latitude" in data or "longitude" in data:
        lat = _coord(data.get("latitude"), -90, 90, "latitude", errors)
        lng = _coord(data.get("longitude"), -180, 180, "longitude", errors)
        if (lat is None) != (lng is None) and not errors:
            errors["latitude"] = "Latitude et longitude vont ensemble."
        out["latitude"], out["longitude"] = lat, lng
        source = str(data.get("coords_source") or ("manual" if lat is not None else "")).strip()
        if lat is None:
            source = ""
        if source not in {c for c, _ in UserAddress.SOURCE_CHOICES} | {""}:
            errors["coords_source"] = "Origine des coordonnées inconnue."
        if source == "device":
            if data.get("location_consent") is not True:
                errors["location_consent"] = "La position de l’appareil n’est utilisée qu’avec votre consentement explicite."
            else:
                out["location_consent_at"] = timezone.now()
        out["coords_source"] = source
    for flag in ("is_favorite",):
        if flag in data:
            if not isinstance(data[flag], bool):
                errors[flag] = "true ou false attendu."
            else:
                out[flag] = data[flag]
    if errors:
        raise AddressError(errors)
    return out


def sync_legacy(user: User) -> None:
    """Les champs historiques du compte (adresse, ville, pays, coordonnées) reflètent l'adresse principale : les écrans existants
    (suggestions de proximité, fiches) continuent de fonctionner sans changement."""
    primary = UserAddress.objects.filter(user=user, is_primary=True).first()
    user.address = (", ".join(x for x in (primary.street, primary.commune) if x) or None) if primary else None
    user.city = primary.city if primary else None
    user.country = primary.country if primary else None
    user.latitude = primary.latitude if primary else None
    user.longitude = primary.longitude if primary else None
    user.save(update_fields=["address", "city", "country", "latitude", "longitude"])


@transaction.atomic
def create(user: User, data: Dict, *, make_primary: bool = False) -> UserAddress:
    fields = clean(data)
    if UserAddress.objects.filter(user=user).count() >= UserAddress.MAX_PER_USER:
        raise AddressError({"detail": f"{UserAddress.MAX_PER_USER} adresses au maximum."})
    first = not UserAddress.objects.select_for_update().filter(user=user).exists()
    primary = first or make_primary
    if primary:
        UserAddress.objects.filter(user=user, is_primary=True).update(is_primary=False)
    address = UserAddress.objects.create(user=user, is_primary=primary, **fields)
    if primary:
        sync_legacy(user)
    return address


@transaction.atomic
def update(address: UserAddress, data: Dict) -> UserAddress:
    fields = clean(data, partial=True)
    for k, v in fields.items():
        setattr(address, k, v)
    address.save()
    if address.is_primary:
        sync_legacy(address.user)
    return address


@transaction.atomic
def set_primary(address: UserAddress) -> UserAddress:
    UserAddress.objects.filter(user=address.user, is_primary=True).exclude(pk=address.pk).update(is_primary=False)
    address.is_primary = True
    address.save(update_fields=["is_primary", "updated_at"])
    sync_legacy(address.user)
    return address


@transaction.atomic
def delete(address: UserAddress) -> None:
    user, was_primary = address.user, address.is_primary
    address.delete()
    if was_primary:
        successor = UserAddress.objects.filter(user=user).order_by("-id").first()
        if successor:
            UserAddress.objects.filter(pk=successor.pk).update(is_primary=True)
        sync_legacy(user)


def is_complete(user: User) -> bool:
    """Adresse principale complète (ville + rue ou quartier) : demandée au moment d'une demande ou d'une prestation, jamais à l'inscription."""
    a = UserAddress.objects.filter(user=user, is_primary=True).first()
    return bool(a and a.city and (a.street or a.commune))


def serialize(a: UserAddress) -> Dict:
    return {
        "id": a.pk, "label": a.label, "country": a.country, "city": a.city, "commune": a.commune, "street": a.street, "complement": a.complement,
        "latitude": float(a.latitude) if a.latitude is not None else None, "longitude": float(a.longitude) if a.longitude is not None else None,
        "coords_source": a.coords_source, "is_primary": a.is_primary, "is_favorite": a.is_favorite,
    }
