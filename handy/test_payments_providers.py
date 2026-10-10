"""Paiements par prestataire (Orange Money, MTN MoMo, carte) : initiation, vérification serveur-à-serveur, webhooks, réconciliation.

Le réseau est SIMULÉ au niveau HTTP (`requests.request`) : aucun appel réel, aucun identifiant réel. Les tests prouvent surtout
ce qui ne doit JAMAIS arriver : un encaissement reconnu sans vérification, sur la foi d'un webhook, d'un montant ou d'une
référence incohérents, ou d'une méthode non configurée."""
import hashlib
import hmac
import json
import re
import time
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from handy import tasks
from handy.models import Booking, Payment, PaymentLog, User
from handy.services import gateway, settlement
from handy.test_eligibility import artisan, service

pytestmark = pytest.mark.django_db

SECRETS = {"OM_CLIENT_SECRET": "om-secret-VALUE", "OM_MERCHANT_KEY": "om-merchant-VALUE", "MTN_MOMO_API_KEY": "mtn-key-VALUE",
           "MTN_MOMO_SUBSCRIPTION_KEY": "mtn-sub-VALUE", "STRIPE_SECRET_KEY": "sk_test_VALUE"}


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    @property
    def content(self):
        return b"" if self._body is None else json.dumps(self._body).encode()

    def json(self):
        return self._body


class FakeNet:
    """Simule les trois prestataires. `om`, `mtn`, `card` : statut courant de la transaction ; `tweak` : écarts à injecter."""

    def __init__(self):
        self.calls, self.om, self.mtn, self.card = [], "INITIATED", "PENDING", "requires_payment_method"
        self.tweak, self.down = {}, False
        self.mtn_tx, self.card_tx, self.om_amount = {}, {}, None
        self.charge_refunded = False

    def __call__(self, verb, url, **kw):
        self.calls.append((verb, url, kw))
        if self.down:
            raise gateway.requests.ConnectionError("réseau coupé")
        if url.endswith("/oauth/v3/token") or url.endswith("/collection/token/"):
            return Resp(200, {"access_token": "tok-VALUE", "expires_in": 3600})
        if url.endswith("/v1/webpayment"):
            self.om_amount = kw["json"]["amount"]
            return Resp(201, {"status": 201, "payment_url": "https://pay.om.example/p/abc", "pay_token": "PAYTOKEN-VALUE", "notif_token": "NOTIF-VALUE"})
        if url.endswith("/v1/transactionstatus"):
            return Resp(200, {"status": self.om, **self.tweak})
        if url.endswith("/v1_0/requesttopay") and verb == "POST":
            ref = kw["headers"]["X-Reference-Id"]
            self.mtn_tx[ref] = kw["json"]
            return Resp(202, None)
        if "/v1_0/requesttopay/" in url:
            tx = self.mtn_tx[url.rsplit("/", 1)[1]]
            return Resp(200, {"amount": tx["amount"], "currency": tx["currency"], "externalId": tx["externalId"], "status": self.mtn, **self.tweak})
        if url.endswith("/v1/payment_intents") and verb == "POST":
            self.card_tx = {"id": f"pi_{len(self.calls)}", **kw["data"]}
            return Resp(200, {"id": self.card_tx["id"], "client_secret": self.card_tx["id"] + "_secret_VALUE", "status": "requires_payment_method"})
        if "/v1/payment_intents/" in url:
            tx = self.card_tx
            return Resp(200, {"id": tx["id"], "status": self.card, "amount": tx["amount"], "amount_received": tx["amount"] if self.card == "succeeded" else 0,
                              "currency": tx["currency"], "client_secret": tx["id"] + "_secret_VALUE",
                              "metadata": {"tratra_ref": tx["metadata[tratra_ref]"], **self.tweak},
                              "latest_charge": {"refunded": self.charge_refunded}})
        if url.endswith("/v1/balance"):
            return Resp(200, {"object": "balance"})
        return Resp(404, {})

    def provider_calls(self, fragment):
        return [c for c in self.calls if fragment in c[1]]


@pytest.fixture(autouse=True)
def net(monkeypatch, settings):
    fake = FakeNet()
    monkeypatch.setattr(gateway.requests, "request", fake)
    gateway.reset_token_caches()
    settings.PAYMENT_OM_WEBHOOK_SECRET = "om-hook-secret"
    settings.PAYMENT_MTN_WEBHOOK_SECRET = "mtn-hook-secret"
    settings.PAYMENT_CARD_WEBHOOK_SECRET = "card-hook-secret"
    settings.DJSTRIPE_WEBHOOK_SECRET = "whsec_VALUE"
    return fake


@pytest.fixture
def configured(settings):
    settings.OM_CLIENT_ID, settings.OM_CLIENT_SECRET, settings.OM_MERCHANT_KEY = "om-id", SECRETS["OM_CLIENT_SECRET"], SECRETS["OM_MERCHANT_KEY"]
    settings.PAYMENT_RETURN_URL, settings.PAYMENT_CANCEL_URL = "https://app.example/retour", "https://app.example/annule"
    settings.PAYMENT_NOTIFY_BASE_URL = "https://api.example/handy"
    settings.MTN_MOMO_SUBSCRIPTION_KEY, settings.MTN_MOMO_API_USER, settings.MTN_MOMO_API_KEY = SECRETS["MTN_MOMO_SUBSCRIPTION_KEY"], "mtn-user", SECRETS["MTN_MOMO_API_KEY"]
    settings.STRIPE_SECRET_KEY = SECRETS["STRIPE_SECRET_KEY"]


@pytest.fixture
def shop():
    client = User.objects.create_user("pay_client", "pay_client@x.test", "pass1234", user_type="client", is_verified=True, phone="+2250700000011")
    pro = artisan("pay_pro")
    svc = service(pro)
    booking = Booking.objects.create(client=client, handyman=pro, service=svc, address="Cocody", city="Abidjan", booking_date=timezone.now() + timedelta(days=2))
    return client, pro, booking


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


def initiate(client, booking, method):
    return api(client).post(reverse("payment-initiate"), {"booking_id": booking.pk, "method": method, "minutes": 60}, format="json")


def hook(provider, ref, claimed="completed", secret=None, body=None):
    raw = json.dumps(body or {"provider_ref": ref, "status": claimed}).encode()
    sig = hmac.new((secret or f"{provider}-hook-secret").encode(), raw, hashlib.sha256).hexdigest()
    return APIClient().post(reverse("payment-webhook", kwargs={"provider": provider}), raw, content_type="application/json", HTTP_X_WEBHOOK_SIGNATURE=sig)


def stripe_hook(event_type, intent_id, *, secret="whsec_VALUE", stamp=None, obj="payment_intent", charge=False):
    payload = {"type": event_type, "data": {"object": ({"id": "ch_1", "object": "charge", "payment_intent": intent_id} if charge else {"id": intent_id, "object": obj})}}
    raw = json.dumps(payload).encode()
    stamp = str(int(stamp if stamp is not None else time.time()))
    sig = hmac.new(secret.encode(), f"{stamp}.".encode() + raw, hashlib.sha256).hexdigest()
    return APIClient().post(reverse("payment-webhook", kwargs={"provider": "card"}), raw, content_type="application/json", HTTP_STRIPE_SIGNATURE=f"t={stamp},v1={sig}")


# ── Disponibilité : sans configuration, rien ne se simule ──────────────────────────────────────────────────────────

def test_unconfigured_providers_are_unavailable_and_create_no_payment(shop):
    client, _, booking = shop
    assert [gateway.provider_for_method(m).is_available for m in ("om", "mtn", "card", "cash")] == [False, False, False, True]
    for method in ("om", "mtn", "card"):
        r = initiate(client, booking, method)
        assert r.status_code == 503 and r.json()["code"] == "payment_provider_unavailable"
    assert not Payment.objects.filter(booking=booking).exists()


def test_partially_configured_provider_stays_unavailable(settings):
    settings.OM_CLIENT_ID = "id-only"
    assert gateway.provider_for_method("om").is_available is False
    settings.MTN_MOMO_API_USER = "user-only"
    assert gateway.provider_for_method("mtn").is_available is False


# ── Orange Money ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_orange_money_flow_only_a_verified_provider_answer_places_funds_in_escrow(shop, net, configured):
    client, _, booking = shop
    r = initiate(client, booking, "om")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["redirect_url"] == "https://pay.om.example/p/abc" and body["provider_ref"].startswith("TR-")
    assert "PAYTOKEN" not in r.content.decode() and "NOTIF-VALUE" not in r.content.decode() and "session" not in body          # session jamais renvoyée
    p = Payment.objects.get(booking=booking)
    assert p.status == "pending" and p.transaction_id == body["provider_ref"] and p.provider_session["pay_token"] == "PAYTOKEN-VALUE"
    assert net.om_amount == int(p.amount) and not p.provider_verified_at

    # Le webhook (même correctement signé) annonce « completed » alors que le prestataire dit « INITIATED » : rien ne change.
    assert hook("om", p.transaction_id).status_code == 200
    p.refresh_from_db()
    assert p.status == "pending" and p.provider_verified_at is None and p.is_paid is False

    net.om = "SUCCESS"
    r = hook("om", p.transaction_id)
    assert r.status_code == 200 and r.json() == {"ok": True, "status": "held", "verified": True}
    p.refresh_from_db()
    assert p.status == "held" and p.is_paid and p.provider_verified_at and p.provider_status == "SUCCESS"
    # Rejeu : sans effet double.
    assert hook("om", p.transaction_id).json()["status"] == "held"
    assert PaymentLog.objects.filter(payment=p, new_status="held").count() == 1


def test_a_forged_or_unsigned_webhook_never_reaches_the_provider_nor_the_payment(shop, net, configured):
    client, _, booking = shop
    initiate(client, booking, "om")
    p = Payment.objects.get(booking=booking)
    net.calls.clear()
    assert hook("om", p.transaction_id, secret="mauvais-secret").status_code == 401
    assert APIClient().post(reverse("payment-webhook", kwargs={"provider": "om"}), {"provider_ref": p.transaction_id, "status": "completed"}, format="json").status_code == 401
    assert hook("mtn", p.transaction_id).status_code == 400                       # signé pour mtn, mais le paiement est « om »
    assert hook("om", "TR-inconnue").status_code == 404
    assert hook("om", p.transaction_id, claimed="gratuit").status_code == 400
    assert net.calls == []
    p.refresh_from_db()
    assert p.status == "pending" and not p.provider_verified_at


def test_webhook_without_a_configured_or_reachable_provider_changes_nothing(shop, net, configured, settings):
    client, _, booking = shop
    initiate(client, booking, "om")
    p = Payment.objects.get(booking=booking)
    net.om, net.down = "SUCCESS", True
    r = hook("om", p.transaction_id)                                               # prestataire injoignable
    assert r.status_code == 503 and r.json()["code"] == "payment_provider_error"
    net.down = False
    settings.OM_CLIENT_ID = ""                                                       # prestataire déconfiguré
    r = hook("om", p.transaction_id)
    assert r.status_code == 503 and r.json()["code"] == "payment_provider_unavailable"
    p.refresh_from_db()
    assert p.status == "pending" and p.is_paid is False


@pytest.mark.parametrize("tweak,problem", [({"amount": 1}, "montant"), ({"currency": "EUR"}, "devise"), ({"order_id": "TR-autre-commande"}, "référence")])
def test_an_inconsistent_provider_answer_is_not_a_payment(shop, net, configured, tweak, problem):
    client, _, booking = shop
    initiate(client, booking, "om")
    p = Payment.objects.get(booking=booking)
    net.om, net.tweak = "SUCCESS", tweak
    r = hook("om", p.transaction_id)
    assert r.status_code == 200 and r.json()["status"] == "pending" and r.json()["verified"] is False
    p.refresh_from_db()
    assert p.status == "pending" and not p.provider_verified_at and p.provider_status == "mismatch"
    assert problem in PaymentLog.objects.filter(payment=p).latest("id").notes


def test_provider_failure_marks_the_payment_failed_and_a_new_attempt_reuses_the_row(shop, net, configured):
    client, _, booking = shop
    first_ref = initiate(client, booking, "om").json()["provider_ref"]
    p = Payment.objects.get(booking=booking)
    net.om = "EXPIRED"
    assert hook("om", first_ref).json()["status"] == "failed"
    assert initiate(client, booking, "om").status_code == 201
    p.refresh_from_db()
    assert p.status == "pending" and p.transaction_id != first_ref and Payment.objects.filter(booking=booking).count() == 1
    assert list(PaymentLog.objects.filter(payment=p).order_by("id").values_list("previous_status", "new_status"))[-2:] == [("pending", "failed"), ("failed", "pending")]
    # L'ancienne référence ne peut plus rien valider.
    net.om = "SUCCESS"
    assert hook("om", first_ref).status_code == 404


def test_resuming_a_pending_attempt_returns_the_stored_link_without_a_second_transaction(shop, net, configured):
    client, _, booking = shop
    first = initiate(client, booking, "om").json()
    n = len(net.provider_calls("/webpayment"))
    again = initiate(client, booking, "om")
    assert again.status_code == 201 and again.json()["already_initiated"] and again.json()["redirect_url"] == first["redirect_url"]
    assert len(net.provider_calls("/webpayment")) == n


def test_provider_outage_on_creation_returns_502_and_leaves_no_payment(shop, net, configured):
    client, _, booking = shop
    net.down = True
    r = initiate(client, booking, "om")
    assert r.status_code == 502 and r.json()["code"] == "payment_provider_error"
    assert not Payment.objects.filter(booking=booking).exists()


# ── MTN MoMo ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_mtn_request_to_pay_then_verified_success(shop, net, configured):
    client, _, booking = shop
    r = initiate(client, booking, "mtn")
    assert r.status_code == 201, r.content
    ref = r.json()["provider_ref"]
    assert re.fullmatch(r"[0-9a-f-]{36}", ref) and "externalId" not in r.json()
    create = net.provider_calls("/requesttopay")[0]
    assert create[2]["json"]["payer"] == {"partyIdType": "MSISDN", "partyId": "2250700000011"} and create[2]["headers"]["X-Callback-Url"] == "https://api.example/handy/payments/webhook/mtn/"
    p = Payment.objects.get(booking=booking)
    assert hook("mtn", ref).json()["status"] == "pending"                          # PENDING côté MTN
    net.mtn = "SUCCESSFUL"
    assert hook("mtn", ref).json() == {"ok": True, "status": "held", "verified": True}
    p.refresh_from_db()
    assert p.provider_verified_at and p.status == "held"


def test_mtn_needs_a_phone_number_and_rejection_is_a_failure(shop, net, configured):
    client, _, booking = shop
    User.objects.filter(pk=client.pk).update(phone=None)
    assert initiate(client, booking, "mtn").status_code == 502 and not Payment.objects.exists()
    User.objects.filter(pk=client.pk).update(phone="+2250700000011")
    ref = initiate(client, booking, "mtn").json()["provider_ref"]
    net.mtn = "REJECTED"
    assert hook("mtn", ref).json()["status"] == "failed"


# ── Carte (Stripe) ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_card_intent_zero_decimal_amount_and_signed_stripe_event(shop, net, configured):
    client, _, booking = shop
    r = initiate(client, booking, "card")
    assert r.status_code == 201, r.content
    assert r.json()["client_secret"].endswith("_secret_VALUE") and r.json()["provider_ref"].startswith("pi_")
    p = Payment.objects.get(booking=booking)
    assert net.card_tx["currency"] == "xof" and int(net.card_tx["amount"]) == int(p.amount)            # XOF : sans centimes
    assert stripe_hook("payment_intent.succeeded", p.transaction_id, secret="whsec_autre").status_code == 401
    assert stripe_hook("payment_intent.succeeded", p.transaction_id, stamp=time.time() - 3600).status_code == 401     # rejeu trop ancien
    p.refresh_from_db()
    assert p.status == "pending"
    net.calls.clear()
    assert stripe_hook("customer.created", p.transaction_id).json() == {"ok": True, "ignored": True} and net.calls == []
    # Événement authentique mais le prestataire dit encore « requires_payment_method » : rien ne change.
    assert stripe_hook("payment_intent.succeeded", p.transaction_id).json()["status"] == "pending"
    net.card = "succeeded"
    assert stripe_hook("payment_intent.succeeded", p.transaction_id).json() == {"ok": True, "status": "held", "verified": True}
    # Remboursement : pris en compte seulement si Stripe l'indique.
    assert stripe_hook("charge.refunded", p.transaction_id, charge=True).json()["status"] == "held"
    net.charge_refunded = True
    assert stripe_hook("charge.refunded", p.transaction_id, charge=True).json()["status"] == "refunded"
    p.refresh_from_db()
    assert p.status == "refunded" and p.refunded_amount == p.amount


def test_card_signed_hmac_header_is_still_accepted_but_only_as_a_trigger(shop, net, configured):
    client, _, booking = shop
    ref = initiate(client, booking, "card").json()["provider_ref"]
    assert hook("card", ref).json()["status"] == "pending"


# ── Retour du client : « vérifier mon paiement » ───────────────────────────────────────────────────────────────────

def test_client_refresh_verifies_server_side_and_is_scoped_to_the_owner(shop, net, configured):
    client, pro, booking = shop
    initiate(client, booking, "om")
    p = Payment.objects.get(booking=booking)
    url = reverse("payments-refresh", kwargs={"pk": p.pk})
    stranger = User.objects.create_user("pay_stranger", "ps@x.test", "pass1234", user_type="client", is_verified=True)
    assert api().post(url).status_code in (401, 403) and api(stranger).post(url).status_code == 404
    r = api(client).post(url)
    assert r.status_code == 200 and r.json()["status"] == "pending" and r.json()["verification"] == "unverified"
    net.om = "SUCCESS"
    r = api(pro).post(url)                                                          # l'artisan concerné peut aussi vérifier
    assert r.status_code == 200 and r.json()["status"] == "held" and r.json()["verification"] == "provider_verified" and r.json()["provider_verified_at"]
    assert "provider_session" not in r.content.decode() and "PAYTOKEN" not in r.content.decode()
    net.down = True
    assert api(client).post(url).status_code == 200                                 # déjà réglé : plus d'appel au prestataire


def test_client_refresh_reports_an_unreachable_provider_and_refuses_cash(shop, net, configured):
    client, _, booking = shop
    initiate(client, booking, "om")
    p = Payment.objects.get(booking=booking)
    net.down = True
    assert api(client).post(reverse("payments-refresh", kwargs={"pk": p.pk})).status_code == 503
    p.refresh_from_db()
    assert p.status == "pending"
    cash_booking = Booking.objects.create(client=client, handyman=booking.handyman, service=booking.service, address="x", city="x", booking_date=timezone.now() + timedelta(days=3))
    cash = initiate(client, cash_booking, "cash")
    assert cash.status_code == 201 and cash.json()["status"] == "pending"
    assert api(client).post(reverse("payments-refresh", kwargs={"pk": cash.json()["payment_id"]})).status_code == 400


# ── Réconciliation (Celery) ────────────────────────────────────────────────────────────────────────────────────────

def test_reconcile_settles_old_pending_payments_and_tolerates_outages(shop, net, configured):
    client, _, booking = shop
    initiate(client, booking, "om")
    p = Payment.objects.get(booking=booking)
    net.om = "SUCCESS"
    assert tasks.reconcile_provider_payments() == {"checked": 0, "settled": 0, "unavailable": 0}          # trop récent : le client paie encore
    Payment.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(minutes=5))
    net.down = True
    assert tasks.reconcile_provider_payments()["unavailable"] == 1
    p.refresh_from_db()
    assert p.status == "pending"
    net.down = False
    assert tasks.reconcile_provider_payments() == {"checked": 1, "settled": 1, "unavailable": 0}
    p.refresh_from_db()
    assert p.status == "held" and p.provider_verified_at
    assert tasks.reconcile_provider_payments()["checked"] == 0                       # plus rien en attente
    assert "payments-reconcile" in __import__("django.conf", fromlist=["settings"]).settings.CELERY_BEAT_SCHEDULE


def test_reconcile_leaves_abandoned_payments_to_staff_after_72_hours(shop, net, configured):
    client, _, booking = shop
    initiate(client, booking, "om")
    p = Payment.objects.get(booking=booking)
    net.om = "SUCCESS"
    Payment.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(hours=80))
    assert tasks.reconcile_provider_payments()["checked"] == 0
    p.refresh_from_db()
    assert p.status == "pending"


# ── Garde-fous structurels ─────────────────────────────────────────────────────────────────────────────────────────

def test_mark_held_refuses_an_unverified_provider_payment_whatever_the_caller(shop):
    client, pro, booking = shop
    for method in ("om", "mtn", "card", "moov", "wave"):
        p = Payment(booking=booking, amount=5000, platform_fee=500, method=method, status="pending", transaction_id=f"ref-{method}")
        p.save()
        with pytest.raises(ValidationError):
            p.mark_held()
        p.refresh_from_db()
        assert p.status == "pending" and p.is_paid is False
        p.delete()
    cash = Payment.objects.create(booking=booking, amount=5000, platform_fee=500, method="cash", status="pending")
    assert cash.method not in Payment.PROVIDER_VERIFIED_METHODS                    # espèces : confirmation manuelle (hors prestataire)


def test_only_the_settlement_service_places_funds_in_escrow_in_application_code():
    """« Ne jamais simuler un paiement réussi » : aucun chemin applicatif (vue, tâche, commande, admin) ne place un paiement
    sous séquestre en dehors de `settlement.apply`, qui n'agit qu'après vérification. Les jeux de données de développement
    (commandes `create_fake_data`, `seed_e2e`) sont les seules exceptions : ils n'existent pas en production."""
    root = Path(__file__).resolve().parents[1]
    dev_seeds = {"handy/management/commands/create_fake_data.py", "handy/management/commands/seed_e2e.py"}
    patterns = [re.compile(r"\.mark_held\("), re.compile(r"_set_status\(\s*['\"]held['\"]"),
                re.compile(r"Payment\.objects\.(?:create|update_or_create|get_or_create|bulk_create)\([^)]*status\s*=\s*['\"](?:held|released|completed)['\"]"),
                re.compile(r"payment\w*\.status\s*=\s*['\"](?:held|released|completed)['\"]")]
    allowed = {"handy/services/settlement.py", "handy/models.py"} | dev_seeds
    offenders = []
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if parts[0] in ("venv", ".venv", "node_modules", "frontend", "staticfiles") or "migrations" in parts or "tests" in parts or path.name.startswith("test_") or path.name == "conftest.py":
            continue
        rel = "/".join(parts)
        if rel in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if any(p.search(text) for p in patterns):
            offenders.append(rel)
    assert offenders == []


def test_no_provider_secret_or_session_token_leaks_in_logs_or_api_output(shop, net, configured, caplog):
    client, _, booking = shop
    caplog.set_level("DEBUG")
    net.down = True
    initiate(client, booking, "om")
    net.down = False
    initiate(client, booking, "om")
    initiate(client, booking, "mtn")
    seen = caplog.text
    r = api(client).get(reverse("payments-list"))
    for value in list(SECRETS.values()) + ["PAYTOKEN-VALUE", "NOTIF-VALUE", "tok-VALUE", "_secret_VALUE"]:
        assert value not in seen and value not in r.content.decode(), value


def test_payments_check_command_reports_configuration_without_secrets(configured, net, capsys):
    call_command("payments_check", "--ping")
    out = capsys.readouterr().out
    assert out.count("DISPONIBLE") == 4 and "ping : jeton obtenu" in out and "ping : clé acceptée" in out
    for value in SECRETS.values():
        assert value not in out
    assert "bac à sable" not in out.split("Orange Money")[1].split("\n")[0]          # devise XOF par défaut : production
    gateway.reset_token_caches()


def test_payments_check_command_says_unavailable_without_configuration(capsys):
    call_command("payments_check")
    out = capsys.readouterr().out
    assert out.count("indisponible") == 3 and "Espèces" in out and "DISPONIBLE" in out


def test_deploy_check_warns_about_a_sandbox_currency_in_production(configured, settings):
    from backoffice import checks

    settings.DEBUG = False
    settings.OM_CURRENCY = "OUV"
    assert [w.id for w in checks.payment_providers(None)] == ["tratra.W003"]
    settings.OM_CURRENCY = "XOF"
    assert checks.payment_providers(None) == []
