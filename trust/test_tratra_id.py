"""Tratra ID : identifiant unique, QR permanent vérifiable, QR de mission temporaire à usage unique, badge PDF."""
import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from handy.models import Booking, HandymanDocument, HandymanProfile
from handy.test_booking_regression import _client
from handy.test_eligibility import artisan, service
from trust import identity
from trust.models import AuditEvent, BookingPass, IdentityCheck, ProfessionalId

User = get_user_model()
pytestmark = pytest.mark.django_db


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


def mission(art, client, *, status="confirmed", in_hours=1):
    return Booking.objects.create(client=client, handyman=art, service=service(art, f"Dépannage {Booking.objects.count()}"),
                                  status=status, address="Rue 1", city="Abidjan",
                                  booking_date=timezone.now() + timedelta(hours=in_hours))


def token_of(response):
    return response.json()["token"]


# ---- Identifiant et QR permanent -----------------------------------------------------------------

def test_id_is_unique_stable_and_well_formed():
    a, b = artisan("id_a"), artisan("id_b")
    codes = set()
    for user in (a, b):
        first = api(user).get("/handy/me/tratra-id/").json()
        again = api(user).get("/handy/me/tratra-id/").json()
        assert re.fullmatch(r"TR-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}", first["tratra_id"])
        assert first["tratra_id"] == again["tratra_id"]  # permanent
        codes.add(first["tratra_id"])
    assert len(codes) == 2 and ProfessionalId.objects.count() == 2
    assert first["qr"].startswith("data:image/png;base64,")
    assert first["verify_url"].endswith(f"/verify/{first['tratra_id']}")
    assert first["valid"] is True and first["status"] == "active" and first["pdf_available"] is True


def test_code_normalisation_accepts_urls_and_rejects_garbage():
    assert identity.normalize_code("tr-abcd-efgh") == "TR-ABCD-EFGH"
    assert identity.normalize_code("https://tratra.test/verify/TR-ABCD-EFGH/") == "TR-ABCD-EFGH"
    for bad in ("", "TR-ABCD", "TR-ABCD-EFG0", "XX-ABCD-EFGH", "<script>"):
        assert identity.normalize_code(bad) is None


def test_public_verification_confirms_a_verified_professional_without_sensitive_data():
    art = artisan("id_pub")
    art.first_name, art.last_name, art.phone = "Awa", "Koné", "+2250700000222"
    art.save()
    code = api(art).get("/handy/me/tratra-id/").json()["tratra_id"]
    r = api().get(f"/handy/verify/id/{code}/")  # sans authentification
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True and body["status"] == "active" and body["tratra_id"] == code
    assert body["holder"]["display_name"] == "Awa K."
    raw = str(body).lower()
    for forbidden in (art.email.lower(), "+2250700000222", "kyc/", "id_card", "koné"):
        assert forbidden not in raw
    assert [b["code"] for b in body["holder"]["badges"]] == ["VERIFIE"]
    # l'URL complète du QR est acceptée telle quelle
    assert api().get(f"/handy/verify/id/{identity.verify_url(code)}/").status_code in (200, 404)


@pytest.mark.parametrize("breaker", ["suspended", "kyc_rejected", "kyc_deleted"])
def test_suspension_or_invalid_kyc_revokes_the_badge_immediately(breaker):
    art = artisan(f"id_rev_{breaker}")
    code = api(art).get("/handy/me/tratra-id/").json()["tratra_id"]
    assert api().get(f"/handy/verify/id/{code}/").json()["valid"] is True
    if breaker == "suspended":
        art.is_active = False
        art.save()
    elif breaker == "kyc_rejected":
        staff = User.objects.create_user("id_staff", "s@x.test", "pass1234", is_staff=True)
        HandymanDocument.objects.get(handyman__user=art, document_type="id_card").reject(by=staff, reason="Flou")
    else:
        HandymanDocument.objects.filter(handyman__user=art, document_type="id_card").delete()
    body = api().get(f"/handy/verify/id/{code}/").json()
    assert body["valid"] is False and body["status"] == "revoked"
    assert "holder" not in body and "n'est plus vérifié" in body["message"]
    # le propriétaire voit son badge suspendu et ne peut plus l'imprimer
    if breaker != "suspended":
        mine = api(art).get("/handy/me/tratra-id/").json()
        assert mine["status"] == "suspended" and mine["valid"] is False and mine["pdf_available"] is False
        assert api(art).get("/handy/me/tratra-id/badge.pdf").status_code == 409
    assert AuditEvent.objects.filter(action="tratra_id.suspended").exists()


def test_unknown_code_gets_a_uniform_404_and_leaks_nothing():
    for code in ("TR-ZZZZ-ZZZZ", "n'importe-quoi"):
        r = api().get(f"/handy/verify/id/{code}/")
        assert r.status_code == 404 and r.json()["valid"] is False and r.json()["status"] == "unknown"


def test_my_id_is_private_and_needs_a_professional_profile():
    assert api().get("/handy/me/tratra-id/").status_code == 401
    assert api(_client("id_client")).get("/handy/me/tratra-id/").status_code == 404
    assert api(_client("id_client2")).get("/handy/me/tratra-id/badge.pdf").status_code == 404


def test_printable_badge_pdf_for_an_active_professional():
    art = artisan("id_pdf")  # photo référencée mais fichier absent : repli sur les initiales
    r = api(art).get("/handy/me/tratra-id/badge.pdf")
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and len(r.content) > 20_000
    assert "attachment" in r["Content-Disposition"] and ".pdf" in r["Content-Disposition"]
    assert r["Cache-Control"] == "private, no-store"


# ---- QR de mission : émission -----------------------------------------------------------------------

def test_only_the_bookings_artisan_can_display_the_mission_qr():
    art, client, outsider = artisan("pass_art"), _client("pass_client"), _client("pass_out")
    b = mission(art, client)
    url = f"/handy/bookings/{b.id}/identity-pass/"
    assert api().post(url).status_code == 401
    assert api(outsider).post(url).status_code == 404       # tiers : la réservation n'existe pas pour lui
    assert api(client).post(url).status_code == 403          # le client ne délivre pas le QR
    r = api(art).post(url)
    assert r.status_code == 201
    body = r.json()
    assert body["qr"].startswith("data:image/png;base64,") and body["ttl_seconds"] == 900
    assert body["url"].endswith(f"/verify/pass/{body['token']}")
    row = BookingPass.objects.get(booking=b)
    assert row.token_hash != body["token"] and len(row.token_hash) == 64  # seule l'empreinte est conservée
    assert (row.expires_at - row.created_at) <= timedelta(minutes=15, seconds=2)


@pytest.mark.parametrize("status", ["pending", "completed", "cancelled"])
def test_mission_qr_needs_a_confirmed_or_ongoing_booking(status):
    art, client = artisan(f"pass_st_{status}"), _client(f"pass_cl_{status}")
    b = mission(art, client, status=status)
    r = api(art).post(f"/handy/bookings/{b.id}/identity-pass/")
    assert r.status_code == 400 and r.json()["code"] == "booking_not_active"


def test_mission_qr_is_only_available_around_the_planned_time():
    art, client = artisan("pass_win"), _client("pass_win_c")
    far = mission(art, client, in_hours=48)
    assert api(art).post(f"/handy/bookings/{far.id}/identity-pass/").json()["code"] == "outside_window"
    old = mission(art, client, in_hours=-20)
    assert api(art).post(f"/handy/bookings/{old.id}/identity-pass/").json()["code"] == "outside_window"


def test_an_unverified_artisan_gets_no_mission_qr():
    art, client = artisan("pass_unv"), _client("pass_unv_c")
    b = mission(art, client)
    art.is_active = False
    art.save()
    r = api(art).post(f"/handy/bookings/{b.id}/identity-pass/")
    assert r.status_code == 409 and r.json()["code"] == "not_verified"


# ---- QR de mission : vérification par le client ---------------------------------------------------------

def test_client_scan_confirms_identity_once_and_records_the_check():
    art, client = artisan("scan_art"), _client("scan_client")
    b = mission(art, client)
    tok = token_of(api(art).post(f"/handy/bookings/{b.id}/identity-pass/"))
    assert api(client).get(f"/handy/bookings/{b.id}/identity/").json()["verified"] is False
    r = api(client).post("/handy/verify/pass/", {"token": tok}, format="json")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["valid"] is True and body["matches_booking"] is True and body["booking_id"] == b.id
    assert body["tratra_id"] == ProfessionalId.objects.get(profile__user=art).code
    assert body["holder"]["display_name"] and "email" not in str(body).lower()
    assert IdentityCheck.objects.filter(booking=b, checked_by=client).count() == 1
    assert AuditEvent.objects.filter(action="identity.verified").exists()
    # non réutilisable
    again = api(client).post("/handy/verify/pass/", {"token": tok}, format="json")
    assert again.status_code == 409 and again.json()["code"] == "used"
    # état visible par les deux participants
    for who in (client, art):
        state = api(who).get(f"/handy/bookings/{b.id}/identity/").json()
        assert state["verified"] is True and state["verified_at"]
    assert api(_client("scan_out")).get(f"/handy/bookings/{b.id}/identity/").status_code == 404


def test_only_the_booking_client_can_consume_the_qr_and_others_learn_nothing():
    art, client, outsider = artisan("sc_art2"), _client("sc_cl2"), _client("sc_out2")
    b = mission(art, client)
    tok = token_of(api(art).post(f"/handy/bookings/{b.id}/identity-pass/"))
    for user in (outsider, art):  # un tiers ET l'artisan lui-même : même réponse qu'un QR inconnu
        r = api(user).post("/handy/verify/pass/", {"token": tok}, format="json")
        assert r.status_code == 404 and r.json()["code"] == "unknown"
    assert api().post("/handy/verify/pass/", {"token": tok}, format="json").status_code == 401
    assert api(client).post("/handy/verify/pass/", {"token": "faux"}, format="json").status_code == 404
    assert BookingPass.objects.get(booking=b).used_at is None  # rien n'a été consommé


def test_expired_and_replaced_qr_are_refused():
    art, client = artisan("sc_art3"), _client("sc_cl3")
    b = mission(art, client)
    old = token_of(api(art).post(f"/handy/bookings/{b.id}/identity-pass/"))
    fresh = token_of(api(art).post(f"/handy/bookings/{b.id}/identity-pass/"))
    r = api(client).post("/handy/verify/pass/", {"token": old}, format="json")
    assert r.status_code == 410 and r.json()["code"] == "replaced"
    BookingPass.objects.filter(booking=b, revoked_at__isnull=True).update(expires_at=timezone.now() - timedelta(seconds=1))
    r = api(client).post("/handy/verify/pass/", {"token": fresh}, format="json")
    assert r.status_code == 410 and r.json()["code"] == "expired"
    assert not IdentityCheck.objects.exists()


def test_scan_fails_if_the_artisan_lost_verification_after_the_qr_was_shown():
    art, client = artisan("sc_art4"), _client("sc_cl4")
    b = mission(art, client)
    tok = token_of(api(art).post(f"/handy/bookings/{b.id}/identity-pass/"))
    art.is_active = False
    art.save()
    r = api(client).post("/handy/verify/pass/", {"token": tok}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "revoked" and "holder" not in r.json()
    assert not IdentityCheck.objects.exists()


def test_scan_refuses_a_booking_that_is_no_longer_active():
    art, client = artisan("sc_art5"), _client("sc_cl5")
    b = mission(art, client)
    tok = token_of(api(art).post(f"/handy/bookings/{b.id}/identity-pass/"))
    Booking.objects.filter(pk=b.pk).update(status="cancelled")
    r = api(client).post("/handy/verify/pass/", {"token": tok}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "booking_not_active"


def test_qr_for_another_booking_of_the_same_client_does_not_match_this_artisans_other_booking():
    """Le QR est lié à UNE réservation : il confirme l'artisan de CETTE réservation uniquement."""
    art, other_art, client = artisan("sc_art6"), artisan("sc_art6b"), _client("sc_cl6")
    b1, b2 = mission(art, client), mission(other_art, client)
    tok = token_of(api(other_art).post(f"/handy/bookings/{b2.id}/identity-pass/"))
    body = api(client).post("/handy/verify/pass/", {"token": tok}, format="json").json()
    assert body["booking_id"] == b2.id and body["booking_id"] != b1.id
    assert IdentityCheck.objects.filter(booking=b1).count() == 0
