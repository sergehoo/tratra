"""Téléphone : libphonenumber côté serveur (E.164), pays transmis par les applications, compatibilité TOTALE avec les numéros déjà
enregistrés (connexion, récupération, profil), SMS/OTP inchangés, doublons détectés, pays proposé par défaut."""
import re
from io import StringIO

import pytest
from django.core.cache import cache
from django.core.management import call_command
from rest_framework.test import APIClient

from handy import phone, sms
from handy.models import CompanyProfile, User

pytestmark = pytest.mark.django_db


def old_normalize(raw):
    """Règle d'avant libphonenumber (référence de compatibilité)."""
    value = re.sub(r"[\s.\-()]", "", raw or "")
    if value.startswith("00"):
        value = "+" + value[2:]
    if not value.startswith("+"):
        value = "+" + ("225" if len(value) == 10 else "") + value
    return value if re.fullmatch(r"\+[1-9]\d{7,14}", value) else None


@pytest.fixture(autouse=True)
def _sms(settings):
    settings.SMS_BACKEND = "locmem"
    settings.PHONE_IP_COUNTRY_HEADER = ""
    cache.clear()
    sms.outbox.clear()


def signup(**extra):
    data = {"first_name": "Awa", "last_name": "Koné", "password": "Tr4tra!secure-2026", "accept_terms": True, **extra}
    return APIClient().post("/handy/users/", data, format="json")


# ═══ Normalisation ═══════════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,region,expected", [
    ("07 00 00 00 00", "CI", "+2250700000000"),
    ("0594977511", None, "+2250594977511"),            # pays par défaut : Côte d'Ivoire
    ("+225 05 94 97 75 11", None, "+2250594977511"),
    ("00225 05 94 97 75 11", "FR", "+2250594977511"),   # numéro international : le pays choisi ne change rien
    ("06 12 34 56 78", "FR", "+33612345678"),            # le 0 national français est retiré
    ("612345678", "FR", "+33612345678"),
    ("77 123 45 67", "SN", "+221771234567"),             # Sénégal : 9 chiffres, sans 0 national
])
def test_national_or_international_numbers_become_e164(raw, region, expected):
    assert phone.to_e164(raw, region) == expected


def test_invalid_numbers_get_a_clear_message_with_a_national_example():
    with pytest.raises(phone.PhoneError) as exc:
        phone.to_e164("07 00 00", "CI")
    assert "exemple" in str(exc.value) and "07" in str(exc.value)
    with pytest.raises(phone.PhoneError):
        phone.to_e164("06 12", "FR")
    with pytest.raises(phone.PhoneError):
        phone.to_e164("", "CI")


@pytest.mark.parametrize("raw", ["+2250700000001", "0700000001", "07 00 00 00 01", "002250700000001", "+22507123456", "22507123456",
                                 "+33612345678", "33612345678", "+14155550123", "(07) 00-00.00.01"])
def test_sms_normalization_accepts_everything_it_accepted_before_with_the_same_e164(raw):
    """OTP/SMS inchangés : même numéro E.164 qu'avant pour toute saisie déjà acceptée (y compris les anciens numéros à 8 chiffres)."""
    assert sms.normalize_msisdn(raw) == old_normalize(raw)


def test_sms_normalization_still_refuses_garbage():
    for raw in ("", "abc", "+0123", "12"):
        with pytest.raises(sms.SMSError):
            sms.normalize_msisdn(raw)


# ═══ Inscription, doublons ═══════════════════════════════════════════════════════════════════════════════════════════

def test_signup_with_country_and_national_number_stores_e164():
    r = signup(phone="06 12 34 56 78", phone_country="FR")
    assert r.status_code == 201, r.content
    assert User.objects.get(pk=r.json()["id"]).phone == "+33612345678"
    r = signup(phone="07 00 00 00 05", phone_country="CI")
    assert User.objects.get(pk=r.json()["id"]).phone == "+2250700000005"


def test_signup_rejects_an_invalid_number_with_a_readable_message():
    r = signup(phone="07 00 00", phone_country="CI")
    assert r.status_code == 400
    assert "invalide" in str(r.json()).lower() and "exemple" in str(r.json())


def test_the_same_line_typed_differently_is_a_duplicate():
    User.objects.create_user(username="first", email="first@x.test", password="x", phone="+2250700000009")
    for raw, region in (("07 00 00 00 09", "CI"), ("+225 07 00 00 00 09", None), ("00225 0700000009", "FR")):
        r = signup(phone=raw, phone_country=region or "")
        assert r.status_code == 400 and r.json()["code"] == "signup_unavailable", (raw, r.content)


# ═══ Comptes existants : connexion, profil, récupération ═════════════════════════════════════════════════════════════

def login(identifier, password="pass1234", country=None):
    data = {"phone": identifier, "password": password}
    if country:
        data["phone_country"] = country
    return APIClient().post("/handy/auth/login/", data, format="json")


def test_login_with_national_number_and_country():
    User.objects.create_user(username="fr", password="pass1234", phone="+33612345678")
    assert login("06 12 34 56 78", country="FR").status_code == 200
    assert login("+33 6 12 34 56 78").status_code == 200


def test_accounts_created_before_libphonenumber_still_log_in_and_recover():
    old = User.objects.create_user(username="old", password="pass1234", phone="+22507123456")   # ancien numéro ivoirien à 8 chiffres
    assert login("+22507123456").status_code == 200
    assert login("22507123456").status_code == 200
    r = APIClient().post("/handy/auth/password-reset/request/", {"phone": "+22507123456"}, format="json")
    assert r.status_code == 202
    assert sms.outbox and sms.outbox[-1][0] == old.phone


def test_recovery_with_national_number_and_country(settings):
    u = User.objects.create_user(username="rec", password="pass1234", phone="+33612345678")
    # Destinations SMS restreintes (anti « SMS pumping ») : la France doit être autorisée explicitement.
    r = APIClient().post("/handy/auth/password-reset/request/", {"phone": "06 12 34 56 78", "phone_country": "FR"}, format="json")
    assert r.status_code == 400 and not sms.outbox
    settings.SMS_ALLOWED_COUNTRY_CODES = "225,33"
    from django.core.cache import cache

    cache.clear()
    r = APIClient().post("/handy/auth/password-reset/request/", {"phone": "06 12 34 56 78", "phone_country": "FR"}, format="json")
    assert r.status_code == 202 and sms.outbox[-1][0] == u.phone


def test_profile_with_a_historical_number_can_still_be_saved_and_a_new_number_must_be_valid():
    u = User.objects.create_user(username="hist", password="pass1234", phone="+22507123456", first_name="A", is_verified=True)
    c = APIClient()
    c.force_authenticate(u)
    r = c.patch(f"/handy/users/{u.pk}/", {"phone": "+22507123456", "first_name": "Awa"}, format="json")
    assert r.status_code == 200, r.content
    u.refresh_from_db()
    assert u.phone == "+22507123456" and u.is_verified is True                # inchangé : toujours vérifié
    assert c.patch(f"/handy/users/{u.pk}/", {"phone": "07 00", "phone_country": "CI"}, format="json").status_code == 400
    r = c.patch(f"/handy/users/{u.pk}/", {"phone": "07 00 00 00 21", "phone_country": "CI"}, format="json")
    assert r.status_code == 200
    u.refresh_from_db()
    assert u.phone == "+2250700000021" and u.is_verified is False             # nouveau numéro : à vérifier par OTP (inchangé)


def test_company_phone_is_normalized():
    u = User.objects.create_user(username="co", password="pass1234")
    c = APIClient()
    c.force_authenticate(u)
    r = c.post("/handy/companies/me/", {"company_name": "Sotra", "phone": "27 22 44 55 66", "phone_country": "CI"}, format="json")
    if r.status_code == 405:
        r = c.put("/handy/companies/me/", {"company_name": "Sotra", "phone": "27 22 44 55 66", "phone_country": "CI"}, format="json")
    assert r.status_code in (200, 201), r.content
    assert CompanyProfile.objects.get(user=u).phone == "+2252722445566"


# ═══ Pays proposé ═════════════════════════════════════════════════════════════════════════════════════════════════════

def test_phone_defaults_only_use_an_ip_country_already_provided_by_the_proxy(settings):
    r = APIClient().get("/handy/phone/defaults/")
    assert r.json() == {"default_region": "CI", "ip_region": None}
    settings.PHONE_IP_COUNTRY_HEADER = "CF-IPCountry"
    assert APIClient().get("/handy/phone/defaults/", HTTP_CF_IPCOUNTRY="sn").json()["ip_region"] == "SN"
    assert APIClient().get("/handy/phone/defaults/", HTTP_CF_IPCOUNTRY="XX").json()["ip_region"] is None


# ═══ Audit en lecture seule ═══════════════════════════════════════════════════════════════════════════════════════════

def test_phone_audit_reports_without_changing_anything():
    User.objects.create_user(username="a1", email="a1@x.test", password="x", phone="+2250700000031")
    User.objects.create_user(username="a2", email="a2@x.test", password="x", phone="+22507123456")
    User.objects.create_user(username="a3", email="a3@x.test", password="x", phone="+4407911123456")                  # 0 national conservé
    User.objects.create_user(username="a4", email="a4@x.test", password="x", phone="+447911123456")                   # même ligne, autre compte
    before = list(User.objects.order_by("pk").values_list("phone", flat=True))
    out = StringIO()
    call_command("phone_audit", "--details", stdout=out)
    text = out.getvalue()
    assert "canoniques (E.164 libphonenumber) : 2" in text and "historiques" in text and "doublons potentiels (même ligne, comptes distincts) : 1" in text
    assert "+2250700000031" not in text                                                            # numéros masqués
    assert list(User.objects.order_by("pk").values_list("phone", flat=True)) == before
