"""Paiement en espèces d'une réservation : déclaré par une partie, confirmé par l'AUTRE, historique, justificatif facultatif.

Ce que ces tests verrouillent : jamais de confirmation par l'auteur, jamais d'accès pour un tiers, aucun gain retirable créé, rien de
présenté comme « vérifié par un prestataire », Back-Office en lecture seule, justificatifs privés et nettoyés."""
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from handy.models import Booking, CashDeclaration, Notification, Payment, User, artisan_available_earnings
from handy.test_eligibility import artisan, service

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


@pytest.fixture
def shop():
    client = User.objects.create_user("cash_client", "cc@x.test", "pass1234", user_type="client", is_verified=True, first_name="Awa")
    pro = artisan("cash_pro")
    pro.first_name = "Moussa"
    pro.save(update_fields=["first_name"])
    stranger = User.objects.create_user("cash_stranger", "cs@x.test", "pass1234", user_type="client", is_verified=True)
    booking = Booking.objects.create(client=client, handyman=pro, service=service(pro), address="Cocody", city="Abidjan", booking_date=timezone.now() + timedelta(days=1),
                                     status="in_progress", total_price=Decimal("10000.00"))
    return client, pro, stranger, booking


def url(name, pk):
    return reverse(name, kwargs={"pk": pk})


def declare(user, booking, **data):
    return api(user).post(url("cash-declare", booking.pk), {"amount": "10000", **data}, format="json")


def png():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 120, 60)).save(buf, "PNG")
    return SimpleUploadedFile("recu.png", buf.getvalue(), content_type="image/png")


def test_declaration_confirmation_by_the_other_party_and_history(shop):
    client, pro, stranger, booking = shop
    assert api(client).get(url("booking-payment", booking.pk)).json()["cash"]["state"] == "none"
    r = declare(pro, booking, note="Remis à la fin de l'intervention")
    assert r.status_code == 201, r.content
    body = r.json()
    d = body["declaration"]
    assert d["declared_by_role"] == "artisan" and d["mine"] and not d["can_respond"] and d["status"] == "declared"
    assert body["cash"]["state"] == "awaiting_confirmation" and body["cash"]["verification"] == "manual" and body["cash"]["declared"] == "10000.00"
    assert "pas un encaissement vérifié" in body["cash"]["note"]

    # L'auteur ne confirme jamais sa propre déclaration ; un tiers n'en voit même pas l'existence.
    assert api(pro).post(url("cash-respond", d["id"]), {"confirm": True}, format="json").status_code == 403
    assert api(stranger).post(url("cash-respond", d["id"]), {"confirm": True}, format="json").status_code == 404
    assert api().post(url("cash-respond", d["id"]), {"confirm": True}, format="json").status_code in (401, 403)

    # Le client voit ce qu'il doit faire, sa notification mène à la réservation.
    seen = api(client).get(url("booking-payment", booking.pk)).json()["cash"]
    assert seen["history"][0]["can_respond"] and seen["my_role"] == "client"
    note = Notification.objects.get(user=client, notification_type="cash_declared")
    assert note.category == "payment" and note.data == {"kind": "booking", "id": booking.pk, "audience": "client"}
    assert not Notification.objects.filter(user=pro, notification_type="cash_declared").exists()      # jamais l'auteur

    done = api(client).post(url("cash-respond", d["id"]), {"confirm": True}, format="json")
    assert done.status_code == 200 and done.json()["declaration"]["status"] == "confirmed"
    cash = done.json()["cash"]
    assert cash["state"] == "paid" and cash["confirmed"] == "10000.00" and cash["remaining"] == "0.00" and cash["can_declare"] is False
    assert api(client).post(url("cash-respond", d["id"]), {"confirm": False, "reason": "Erreur de ma part"}, format="json").status_code == 409     # déjà traité
    back = Notification.objects.get(user=pro, notification_type="cash_confirmed")
    assert back.data["kind"] == "mission" and "confirmée" in back.message
    assert declare(pro, booking).status_code == 409                                                    # déjà réglée


def test_confirmation_creates_no_withdrawable_earnings_and_never_looks_provider_verified(shop):
    client, pro, _, booking = shop
    payment = Payment.objects.create(booking=booking, amount=Decimal("10000"), platform_fee=Decimal("1100"), method="cash", status="pending")
    d = declare(client, booking).json()["declaration"]                                                  # le client déclare avoir remis
    api(pro).post(url("cash-respond", d["id"]), {"confirm": True}, format="json")
    payment.refresh_from_db()
    assert payment.status == "pending" and payment.is_paid is False and payment.provider_verified_at is None       # le séquestre n'est pas concerné
    assert artisan_available_earnings(pro) == Decimal("0.00")                                          # l'argent est déjà dans la main de l'artisan
    block = api(pro).get(url("booking-payment", booking.pk)).json()
    assert block["payment"]["method"] == "cash" and block["payment"]["verification"] == "manual" and block["cash"]["verification"] == "manual"
    assert block["payment"]["provider_verified_at"] is None and "provider_verified'" not in str(block)       # jamais présenté comme vérifié par un prestataire


def test_contestation_needs_a_reason_keeps_history_and_allows_a_new_declaration(shop):
    client, pro, _, booking = shop
    first = declare(pro, booking, amount="10000").json()["declaration"]
    r = api(client).post(url("cash-respond", first["id"]), {"confirm": False}, format="json")
    assert r.status_code == 400 and "reason" in r.json()["fields"]
    r = api(client).post(url("cash-respond", first["id"]), {"confirm": False, "reason": "Je n'ai remis que 6000"}, format="json")
    assert r.status_code == 200 and r.json()["cash"]["state"] == "contested"
    assert Notification.objects.get(user=pro, notification_type="cash_contested").message.endswith("Je n'ai remis que 6000.")
    second = declare(pro, booking, amount="6000").json()
    assert second["cash"]["state"] == "awaiting_confirmation"
    api(client).post(url("cash-respond", second["declaration"]["id"]), {"confirm": True}, format="json")
    cash = api(pro).get(url("booking-payment", booking.pk)).json()["cash"]
    assert cash["state"] == "partial" and cash["confirmed"] == "6000.00" and cash["remaining"] == "4000.00"
    assert [h["status"] for h in cash["history"]] == ["rejected", "confirmed"]                          # l'historique conserve la contestation
    assert cash["history"][0]["rejection_reason"] == "Je n'ai remis que 6000"
    assert declare(client, booking, amount="4000").status_code == 201                                  # le solde se déclare, par l'une ou l'autre partie


def test_declaration_rules_amount_date_status_and_duplicates(shop):
    client, pro, stranger, booking = shop
    assert declare(stranger, booking).status_code == 404 and api().post(url("cash-declare", booking.pk), {"amount": "5"}, format="json").status_code in (401, 403)
    assert declare(pro, booking, amount="10001").status_code == 400                                     # au-delà du solde
    assert declare(pro, booking, amount="0").status_code == 400 and declare(pro, booking, amount="abc").status_code == 400
    future = (timezone.localdate() + timedelta(days=2)).isoformat()
    assert "paid_on" in declare(pro, booking, paid_on=future).json()["fields"]
    assert declare(pro, booking, paid_on="pas-une-date").status_code == 400
    assert declare(pro, booking, note="x" * 201).status_code == 400
    assert declare(pro, booking, amount="3000").status_code == 201
    assert declare(pro, booking, amount="3000").status_code == 409                                      # doublon en attente
    Booking.objects.filter(pk=booking.pk).update(status="confirmed")                                     # prestation pas encore commencée
    assert declare(pro, booking, amount="1000").json()["code"] == "booking_not_ready"
    Booking.objects.filter(pk=booking.pk).update(status="cancelled")
    assert declare(pro, booking, amount="1000").status_code == 409
    # Montant par défaut = solde restant.
    Booking.objects.filter(pk=booking.pk).update(status="completed")
    assert api(pro).post(url("cash-declare", booking.pk), {}, format="json").json()["declaration"]["amount"] == "7000.00"


def test_a_provider_payment_is_not_settled_in_cash_and_the_block_hides_the_cash_card(shop):
    client, pro, _, booking = shop
    Payment.objects.create(booking=booking, amount=Decimal("10000"), platform_fee=Decimal("1100"), method="om", status="pending", transaction_id="TR-x")
    r = declare(pro, booking)
    assert r.status_code == 409 and r.json()["code"] == "not_cash"
    block = api(client).get(url("booking-payment", booking.pk)).json()
    assert block["cash"] is None and block["payment"]["method"] == "om" and block["payment"]["verification"] == "unverified"


def test_receipt_is_optional_private_and_cleaned(shop, settings):
    client, pro, stranger, booking = shop
    plain = declare(pro, booking, amount="2000").json()["declaration"]
    assert plain["receipt"] is None
    with_image = api(pro).post(url("cash-declare", booking.pk), {"amount": "3000", "receipt": png()}, format="multipart").json()["declaration"]
    assert with_image["receipt"]["url"].endswith(f"/payments/cash/{with_image['id']}/receipt/")
    pdf = api(pro).post(url("cash-declare", booking.pk), {"amount": "1000", "receipt": SimpleUploadedFile("r.pdf", PDF, content_type="application/pdf")}, format="multipart")
    assert pdf.status_code == 201
    # Lecture : les deux parties seulement, jamais en cache, jamais interprété par le navigateur.
    for who in (pro, client):
        r = api(who).get(with_image["receipt"]["url"])
        assert r.status_code == 200 and r["Cache-Control"] == "private, no-store" and r["X-Content-Type-Options"] == "nosniff" and "sandbox" in r["Content-Security-Policy"]
        assert b"".join(r.streaming_content).startswith(b"\xff\xd8\xff")                                   # image RÉENCODÉE par le serveur (PNG opaque → JPEG sans métadonnées)
    assert api(stranger).get(with_image["receipt"]["url"]).status_code == 404 and api().get(with_image["receipt"]["url"]).status_code in (401, 403)
    assert api(pro).get(url("cash-receipt", plain["id"])).status_code == 404                              # pas de justificatif
    # Refus : PDF actif, faux fichier, trop lourd.
    for name, content in (("a.pdf", PDF.replace(b"/Type", b"/OpenAction<</S/JavaScript>>/Type")), ("b.pdf", b"<html>pas un pdf</html>")):
        bad = api(pro).post(url("cash-declare", booking.pk), {"amount": "500", "receipt": SimpleUploadedFile(name, content)}, format="multipart")
        assert bad.status_code == 400 and "receipt" in bad.json()["fields"], name
    assert CashDeclaration.objects.filter(booking=booking).count() == 3                                  # rien d'enregistré pour les refus


def test_idempotency_key_replays_the_same_declaration_without_a_duplicate(shop):
    client, pro, _, booking = shop
    c = api(pro)
    first = c.post(url("cash-declare", booking.pk), {"amount": "2500"}, format="json", HTTP_IDEMPOTENCY_KEY="cash-key-0001")
    again = c.post(url("cash-declare", booking.pk), {"amount": "2500"}, format="json", HTTP_IDEMPOTENCY_KEY="cash-key-0001")
    assert first.status_code == 201 and again.status_code == 201 and again["Idempotent-Replay"] == "true"
    assert first.json()["declaration"]["id"] == again.json()["declaration"]["id"] and CashDeclaration.objects.count() == 1
    assert c.post(url("cash-declare", booking.pk), {"amount": "3500"}, format="json", HTTP_IDEMPOTENCY_KEY="cash-key-0001").status_code == 422


def test_only_the_two_parties_read_the_payment_block_and_staff_gets_no_shortcut(shop):
    client, pro, stranger, booking = shop
    assert api(stranger).get(url("booking-payment", booking.pk)).status_code == 404
    assert api().get(url("booking-payment", booking.pk)).status_code in (401, 403)
    root = User.objects.create_user("cash_root", "cr@x.test", "pass1234", is_staff=True, is_superuser=True)
    assert api(root).get(url("booking-payment", booking.pk)).status_code == 404                         # le personnel passe par le Back-Office (lecture seule)
    d = declare(pro, booking).json()["declaration"]
    assert api(root).post(url("cash-respond", d["id"]), {"confirm": True}, format="json").status_code == 404      # le Back-Office ne confirme jamais un paiement
    assert api(client).get(url("booking-payment", 999999)).status_code == 404


def test_cash_notification_types_are_known_to_the_notification_center():
    from handy.notifications import CATEGORY_BY_TYPE
    for t in ("cash_declared", "cash_confirmed", "cash_contested"):
        assert CATEGORY_BY_TYPE[t] == "payment" and t in dict(Notification.TYPES)


def test_back_office_sees_cash_read_only_without_receipts_and_by_right(shop):
    from backoffice import rbac
    from django.contrib.auth.models import Group

    client, pro, _, booking = shop
    Payment.objects.create(booking=booking, amount=Decimal("10000"), platform_fee=Decimal("1100"), method="cash", status="pending")
    d = api(pro).post(url("cash-declare", booking.pk), {"amount": "10000", "receipt": png()}, format="multipart").json()["declaration"]
    api(client).post(url("cash-respond", d["id"]), {"confirm": True}, format="json")
    rbac.ensure_roles()

    def staff(name, role):
        u = User.objects.create_user(name, f"{name}@x.test", "pass1234", is_staff=True)
        u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
        return u

    finance, support = staff("cash_fin", "finance"), staff("cash_sup", "support")
    payment = Payment.objects.get(booking=booking)
    r = api(finance).get(f"/handy/backoffice/finance/payments/{payment.pk}/")
    assert r.status_code == 200, r.content
    cash = r.json()["cash"]
    assert cash["state"] == "paid" and cash["verification"] == "manual" and cash["can_declare"] is False and cash["my_role"] is None
    assert all(h["receipt"] is None and not h["can_respond"] and not h["mine"] for h in cash["history"])        # lecture seule, justificatif privé
    assert api(finance).post(url("cash-respond", d["id"]), {"confirm": True}, format="json").status_code == 404
    booking_view = api(finance).get(f"/handy/backoffice/bookings/{booking.pk}/").json()
    assert booking_view["cash"]["state"] == "paid"
    assert api(support).get(f"/handy/backoffice/bookings/{booking.pk}/").json()["cash"] is None                # pas de droit « finance » : pas de montants
