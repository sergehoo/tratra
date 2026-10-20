"""Numéros de téléphone : normalisation et validation E.164 avec libphonenumber (`phonenumbers`), source unique côté serveur.

Les applications envoient le pays choisi (ISO 3166, ex. « CI ») et le numéro NATIONAL, ou directement un E.164 ; le serveur revalide
toujours. Règles :

- `to_e164(raw, region)` : numéro VALIDE pour son pays (inscription, changement de numéro, entreprise) → « +2250700000000 » ;
- `lookup_candidates(raw, region)` : formes sous lesquelles un numéro DÉJÀ enregistré peut figurer (connexion, récupération) —
  la forme libphonenumber, et la forme historique (ancienne règle : 10 chiffres → +225, sinon « + » ajouté), pour ne perdre aucun compte
  créé avant libphonenumber (ex. anciens numéros ivoiriens à 8 chiffres) ;
- `display(e164)` : « +225 07 00 00 0000 » pour l'affichage.

Le fonctionnement OTP/SMS est inchangé : `handy.sms.normalize_msisdn` accepte toujours ce qu'il acceptait (forme historique en repli).
"""
import re
from typing import List, Optional

import phonenumbers
from django.conf import settings
from phonenumbers import NumberParseException, PhoneNumberFormat

INVALID = "Numéro de téléphone invalide."
# Exemples affichés tels que les utilisateurs écrivent leur numéro (libphonenumber groupe le numéro ivoirien en « 01 23 45 6789 »).
EXAMPLES = {"CI": "07 00 00 00 00"}


class PhoneError(ValueError):
    pass


def default_region() -> str:
    return str(getattr(settings, "PHONE_DEFAULT_REGION", "CI") or "CI").upper()


def ip_region(request) -> Optional[str]:
    """Pays déduit de l'adresse IP UNIQUEMENT si le proxy le fournit déjà (en-tête `PHONE_IP_COUNTRY_HEADER`, ex. Cloudflare
    « CF-IPCountry ») : aucune base de géolocalisation n'est interrogée."""
    header = str(getattr(settings, "PHONE_IP_COUNTRY_HEADER", "") or "").strip()
    if not header or request is None:
        return None
    value = str(request.META.get("HTTP_" + header.upper().replace("-", "_"), "") or "").strip().upper()
    return value if value in phonenumbers.SUPPORTED_REGIONS else None


def _clean(raw) -> str:
    value = re.sub(r"[\s.\-()/]", "", str(raw or "").strip())
    return "+" + value[2:] if value.startswith("00") else value


def _region(region: Optional[str]) -> str:
    r = (region or "").strip().upper()
    return r if r in phonenumbers.SUPPORTED_REGIONS else default_region()


def parse(raw, region: Optional[str] = None) -> phonenumbers.PhoneNumber:
    value = _clean(raw)
    if not value:
        raise PhoneError(INVALID)
    try:
        return phonenumbers.parse(value, None if value.startswith("+") else _region(region))
    except NumberParseException as exc:
        raise PhoneError(INVALID) from exc


def to_e164(raw, region: Optional[str] = None, *, strict: bool = True) -> str:
    """E.164 d'un numéro saisi (national avec `region`, ou international) ; `strict` exige un numéro valide pour son pays,
    sinon un numéro seulement « possible » (bonne longueur) suffit."""
    num = parse(raw, region)
    ok = phonenumbers.is_valid_number(num) if strict else phonenumbers.is_possible_number(num)
    if not ok:
        raise PhoneError(error_message(num))
    return phonenumbers.format_number(num, PhoneNumberFormat.E164)


def error_message(num: Optional[phonenumbers.PhoneNumber] = None) -> str:
    """Message clair : pays concerné et exemple de numéro national attendu."""
    if num is None:
        return INVALID
    region = phonenumbers.region_code_for_country_code(num.country_code)
    if region in EXAMPLES:
        return f"{INVALID} Vérifiez le nombre de chiffres (exemple : {EXAMPLES[region]})."
    example = phonenumbers.example_number_for_type(region, phonenumbers.PhoneNumberType.MOBILE) if region and region != "ZZ" else None
    if example is None:
        return f"{INVALID} Vérifiez l’indicatif et le nombre de chiffres."
    national = phonenumbers.format_number(example, PhoneNumberFormat.NATIONAL)
    return f"{INVALID} Vérifiez le nombre de chiffres (exemple : {national})."


def legacy_e164(raw) -> Optional[str]:
    """Ancienne règle (avant libphonenumber) : 10 chiffres nationaux → indicatif par défaut (`SMS_DEFAULT_COUNTRY_CODE`, 225) ;
    sinon le numéro est supposé commencer par son indicatif."""
    value = _clean(raw)
    if not value.startswith("+"):
        from handy.sms import _setting

        value = "+" + (_setting("SMS_DEFAULT_COUNTRY_CODE", "225") if len(value) == 10 else "") + value
    return value if re.fullmatch(r"\+[1-9]\d{7,14}", value) else None


def lookup_candidates(raw, region: Optional[str] = None) -> List[str]:
    """Formes possibles d'un numéro déjà enregistré, pour retrouver un compte sans en perdre aucun."""
    out = []
    try:
        out.append(to_e164(raw, region, strict=False))
    except PhoneError:
        pass
    legacy = legacy_e164(raw)
    if legacy:
        out.append(legacy)
    return list(dict.fromkeys(out))


def display(e164: Optional[str]) -> str:
    if not e164:
        return ""
    try:
        return phonenumbers.format_number(phonenumbers.parse(e164, None), PhoneNumberFormat.INTERNATIONAL)
    except NumberParseException:
        return e164


def region_of(e164: Optional[str]) -> Optional[str]:
    try:
        r = phonenumbers.region_code_for_number(phonenumbers.parse(e164 or "", None))
    except NumberParseException:
        return None
    return r if r and r != "ZZ" else None
