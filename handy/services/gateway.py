# handy/services/gateway.py
"""Prestataires de paiement : Orange Money, MTN MoMo, carte (Stripe) et espèces.

Règles (voir docs/paiements.md) :
  * un adaptateur n'est DISPONIBLE que si tous ses identifiants sont configurés ; sinon `create` lève
    `PaymentProviderUnavailable` (aucune ligne `pending` fictive, aucune référence prévisible) ;
  * l'argent n'est reconnu qu'après `verify` : un appel serveur-à-serveur auprès du prestataire qui rend le statut, le montant
    et la devise RÉELS de la transaction (jamais le contenu d'un webhook ou d'une redirection) ;
  * aucun secret n'est journalisé ni renvoyé : les erreurs du prestataire sont ramenées à un message neutre.
"""
import base64
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PROVIDER_METHODS = ("om", "mtn", "card")


class PaymentProviderUnavailable(RuntimeError):
    """Raised when a payment method has no real, configured provider adapter."""

    code = "payment_provider_unavailable"

    def __init__(self, method, message=None):
        self.method = method
        super().__init__(message or f"Le prestataire de paiement « {method} » n'est pas configuré.")


class PaymentProviderError(RuntimeError):
    """Le prestataire est configuré mais n'a pas pu répondre (réseau, refus, réponse illisible). Transitoire par défaut :
    l'appelant ne change AUCUN état et réessaiera."""

    code = "payment_provider_error"

    def __init__(self, method, message="Le prestataire de paiement n'a pas répondu correctement."):
        self.method = method
        super().__init__(message)


@dataclass(frozen=True)
class Verification:
    """Résultat d'une vérification serveur-à-serveur.

    state : « completed » (encaissé), « pending » (en cours / en attente du client), « failed » (refusé, expiré, annulé),
    « refunded » (remboursé auprès du prestataire). `amount`/`currency`/`reference` sont ceux du PRESTATAIRE."""

    state: str
    amount: Optional[Decimal]
    currency: str
    reference: str
    raw_status: str


def _cfg(name: str) -> str:
    return (getattr(settings, name, "") or "").strip()


def _decimal(value) -> Optional[Decimal]:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _call(method: str, verb: str, url: str, **kw):
    """Appel HTTP vers un prestataire : délai borné, aucune trace du contenu (clés, jetons, numéros)."""
    kw.setdefault("timeout", int(getattr(settings, "PAYMENT_HTTP_TIMEOUT", 10)))
    try:
        return requests.request(verb, url, **kw)
    except requests.RequestException:
        logger.warning("Paiement %s : prestataire injoignable (%s).", method, verb)
        raise PaymentProviderError(method, "Le prestataire de paiement est injoignable.")


def _json(method: str, response, ok=(200, 201, 202)) -> dict:
    if response.status_code not in ok:
        logger.warning("Paiement %s : refus du prestataire (HTTP %s).", method, response.status_code)
        raise PaymentProviderError(method)
    try:
        data = response.json() if response.content else {}
    except ValueError:
        raise PaymentProviderError(method, "Réponse illisible du prestataire.")
    return data if isinstance(data, dict) else {}


class _TokenCache:
    """Jeton d'accès OAuth mémorisé jusqu'à son expiration (un par prestataire)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._value, self._exp = None, 0.0

    def get(self, fetch):
        with self._lock:
            if self._value and self._exp - 30 > time.time():
                return self._value
            value, ttl = fetch()
            self._value, self._exp = value, time.time() + max(int(ttl), 60)
            return value

    def reset(self):
        with self._lock:
            self._value, self._exp = None, 0.0


def new_order_ref(prefix: str, booking) -> str:
    """Référence de commande imprévisible (ni numéro de réservation seul, ni compteur)."""
    return f"{prefix}-{booking.pk}-{uuid.uuid4().hex[:16]}"


def _notify_url(provider: str) -> str:
    base = _cfg("PAYMENT_NOTIFY_BASE_URL").rstrip("/")
    return f"{base}/payments/webhook/{provider}/" if base else ""


class Provider(ABC):
    """Interface des fournisseurs de paiement.

    `create` initialise la transaction chez le prestataire ; `verify` en lit l'état RÉEL. `capture`/`refund` ont une
    implémentation par défaut « non supportée » afin qu'un provider puisse être instancié même s'il ne les gère pas encore."""

    method = ""
    is_available = False
    # Devise dans laquelle la demande est envoyée au prestataire (XOF en production ; EUR/OUV possibles en bac à sable).
    currency = "XOF"
    # Données de session du prestataire à conserver pour la vérification (jamais exposées par l'API).
    session_keys = ()

    @abstractmethod
    def create(self, booking, amount_xof: int) -> dict: ...

    def verify(self, payment) -> Verification:
        raise PaymentProviderUnavailable(self.method or type(self).__name__)

    def resume(self, payment) -> dict:
        """Données utiles au client pour REPRENDRE une tentative déjà initiée (lien de paiement, secret client…)."""
        return {}

    def capture(self, provider_ref: str) -> dict:
        raise NotImplementedError(f"{type(self).__name__}.capture non implémenté")

    def refund(self, provider_ref: str, amount_xof: int) -> dict:
        raise NotImplementedError(f"{type(self).__name__}.refund non implémenté")

    def ping(self) -> str:
        """Contrôle de configuration (`manage.py payments_check --ping`) : obtient un jeton, sans créer de transaction."""
        raise PaymentProviderUnavailable(self.method)


# ── Orange Money (Web Payment) ──────────────────────────────────────────────────────────────────────────────────────

_om_token = _TokenCache()


class OrangeMoney(Provider):
    method = "om"

    @property
    def currency(self):
        return (_cfg("OM_CURRENCY") or "XOF").upper()

    @property
    def is_available(self):
        return all(_cfg(k) for k in ("OM_CLIENT_ID", "OM_CLIENT_SECRET", "OM_MERCHANT_KEY", "PAYMENT_RETURN_URL", "PAYMENT_CANCEL_URL", "PAYMENT_NOTIFY_BASE_URL"))

    def _base(self):
        return _cfg("OM_API_BASE").rstrip("/")

    def _access_token(self):
        def fetch():
            basic = base64.b64encode(f"{_cfg('OM_CLIENT_ID')}:{_cfg('OM_CLIENT_SECRET')}".encode()).decode()
            data = _json("om", _call("om", "POST", f"{self._base()}/oauth/v3/token", data={"grant_type": "client_credentials"},
                                     headers={"Authorization": f"Basic {basic}", "Accept": "application/json"}), ok=(200,))
            if not data.get("access_token"):
                raise PaymentProviderError("om")
            return data["access_token"], data.get("expires_in", 3600)

        return _om_token.get(fetch)

    def _headers(self):
        return {"Authorization": f"Bearer {self._access_token()}", "Accept": "application/json", "Content-Type": "application/json"}

    def ping(self):
        if not self.is_available:
            raise PaymentProviderUnavailable("om")
        _om_token.reset()
        self._access_token()
        return "jeton obtenu"

    def create(self, booking, amount_xof):
        if not self.is_available:
            raise PaymentProviderUnavailable("om")
        order_id = new_order_ref("TR", booking)
        body = {"merchant_key": _cfg("OM_MERCHANT_KEY"), "currency": self.currency, "order_id": order_id, "amount": int(amount_xof),
                "return_url": _cfg("PAYMENT_RETURN_URL"), "cancel_url": _cfg("PAYMENT_CANCEL_URL"), "notif_url": _notify_url("om"),
                "lang": "fr", "reference": f"Tratra réservation {booking.pk}"}
        data = _json("om", _call("om", "POST", f"{self._base()}/orange-money-webpay/{_cfg('OM_COUNTRY') or 'ci'}/v1/webpayment", json=body, headers=self._headers()))
        if not data.get("payment_url") or not data.get("pay_token"):
            raise PaymentProviderError("om", "Le prestataire n'a pas retourné de lien de paiement.")
        return {"provider": "om", "provider_ref": order_id, "redirect_url": data["payment_url"], "status": "pending", "requires_customer_action": True,
                "session": {"pay_token": data["pay_token"], "notif_token": data.get("notif_token", "")}}

    def resume(self, payment):
        url = (payment.provider_session or {}).get("redirect_url")
        return {"redirect_url": url} if url else {}

    def verify(self, payment) -> Verification:
        if not self.is_available:
            raise PaymentProviderUnavailable("om")
        pay_token = (payment.provider_session or {}).get("pay_token", "")
        if not pay_token or not payment.transaction_id:
            raise PaymentProviderError("om", "Session de paiement introuvable.")
        body = {"order_id": payment.transaction_id, "amount": int(payment.amount), "pay_token": pay_token}
        data = _json("om", _call("om", "POST", f"{self._base()}/orange-money-webpay/{_cfg('OM_COUNTRY') or 'ci'}/v1/transactionstatus", json=body, headers=self._headers()))
        raw = str(data.get("status", "")).upper()
        state = {"SUCCESS": "completed", "FAILED": "failed", "EXPIRED": "failed", "CANCELLED": "failed", "INITIATED": "pending", "PENDING": "pending"}.get(raw)
        if state is None:
            raise PaymentProviderError("om", "Statut de transaction inconnu.")
        # La réponse Orange ne rappelle pas toujours le montant ni la devise : à défaut, ce sont ceux de la REQUÊTE de statut
        # (order_id + amount + pay_token, que le prestataire lie à la transaction : un montant différent n'est pas « SUCCESS »).
        # À valider en bac à sable (docs/paiements.md, étape « montant erroné »).
        return Verification(state, _decimal(data.get("amount", payment.amount)), str(data.get("currency") or self.currency).upper(),
                            str(data.get("order_id", payment.transaction_id)), raw)


# ── MTN MoMo (Collection) ───────────────────────────────────────────────────────────────────────────────────────────

_mtn_token = _TokenCache()


class MTNMoney(Provider):
    method = "mtn"

    @property
    def currency(self):
        return (_cfg("MTN_MOMO_CURRENCY") or "XOF").upper()

    @property
    def is_available(self):
        return all(_cfg(k) for k in ("MTN_MOMO_SUBSCRIPTION_KEY", "MTN_MOMO_API_USER", "MTN_MOMO_API_KEY"))

    def _base(self):
        return _cfg("MTN_MOMO_BASE_URL").rstrip("/")

    def _access_token(self):
        def fetch():
            basic = base64.b64encode(f"{_cfg('MTN_MOMO_API_USER')}:{_cfg('MTN_MOMO_API_KEY')}".encode()).decode()
            data = _json("mtn", _call("mtn", "POST", f"{self._base()}/collection/token/",
                                      headers={"Authorization": f"Basic {basic}", "Ocp-Apim-Subscription-Key": _cfg("MTN_MOMO_SUBSCRIPTION_KEY")}), ok=(200,))
            if not data.get("access_token"):
                raise PaymentProviderError("mtn")
            return data["access_token"], data.get("expires_in", 3600)

        return _mtn_token.get(fetch)

    def _headers(self, **extra):
        return {"Authorization": f"Bearer {self._access_token()}", "X-Target-Environment": _cfg("MTN_MOMO_TARGET_ENV") or "sandbox",
                "Ocp-Apim-Subscription-Key": _cfg("MTN_MOMO_SUBSCRIPTION_KEY"), **extra}

    def ping(self):
        if not self.is_available:
            raise PaymentProviderUnavailable("mtn")
        _mtn_token.reset()
        self._access_token()
        return "jeton obtenu"

    @staticmethod
    def _msisdn(booking) -> str:
        digits = "".join(ch for ch in str(getattr(booking.client, "phone", "") or "") if ch.isdigit())
        return digits

    def create(self, booking, amount_xof):
        if not self.is_available:
            raise PaymentProviderUnavailable("mtn")
        msisdn = self._msisdn(booking)
        if len(msisdn) < 8:
            raise PaymentProviderError("mtn", "Un numéro de téléphone MTN valide est requis sur le compte du client.")
        ref = str(uuid.uuid4())
        callback = _notify_url("mtn")
        headers = self._headers(**{"X-Reference-Id": ref, "Content-Type": "application/json"}, **({"X-Callback-Url": callback} if callback.startswith("https://") else {}))
        body = {"amount": str(int(amount_xof)), "currency": self.currency, "externalId": f"TR-{booking.pk}-{ref[:8]}",
                "payer": {"partyIdType": "MSISDN", "partyId": msisdn}, "payerMessage": "Tratra", "payeeNote": f"Réservation {booking.pk}"}
        _json("mtn", _call("mtn", "POST", f"{self._base()}/collection/v1_0/requesttopay", json=body, headers=headers), ok=(202,))
        return {"provider": "mtn", "provider_ref": ref, "status": "pending", "requires_customer_action": True,
                "instructions": "Validez la demande de paiement MTN MoMo sur votre téléphone.", "session": {"external_id": body["externalId"]}}

    def resume(self, payment):
        return {"instructions": "Validez la demande de paiement MTN MoMo sur votre téléphone."}

    def verify(self, payment) -> Verification:
        if not self.is_available:
            raise PaymentProviderUnavailable("mtn")
        if not payment.transaction_id:
            raise PaymentProviderError("mtn", "Référence de transaction introuvable.")
        data = _json("mtn", _call("mtn", "GET", f"{self._base()}/collection/v1_0/requesttopay/{payment.transaction_id}", headers=self._headers()), ok=(200,))
        raw = str(data.get("status", "")).upper()
        state = {"SUCCESSFUL": "completed", "FAILED": "failed", "REJECTED": "failed", "TIMEOUT": "failed", "PENDING": "pending"}.get(raw)
        if state is None:
            raise PaymentProviderError("mtn", "Statut de transaction inconnu.")
        return Verification(state, _decimal(data.get("amount")), str(data.get("currency", "")).upper(), str(data.get("externalId", "")), raw)


# ── Carte (Stripe) ──────────────────────────────────────────────────────────────────────────────────────────────────

ZERO_DECIMAL = {"xof", "xaf", "xpf", "jpy", "krw", "clp", "vnd", "ugx", "rwf", "pyg", "kmf", "gnf", "djf", "bif", "vuv"}


class StripeCard(Provider):
    method = "card"

    @property
    def currency(self):
        return (_cfg("STRIPE_CURRENCY") or "xof").upper()

    @property
    def is_available(self):
        return bool(_cfg("STRIPE_SECRET_KEY"))

    def _base(self):
        return _cfg("STRIPE_API_BASE").rstrip("/")

    def _headers(self, **extra):
        return {"Authorization": f"Bearer {_cfg('STRIPE_SECRET_KEY')}", **extra}

    def ping(self):
        if not self.is_available:
            raise PaymentProviderUnavailable("card")
        _json("card", _call("card", "GET", f"{self._base()}/v1/balance", headers=self._headers()), ok=(200,))
        return "clé acceptée"

    @staticmethod
    def _minor(amount, currency) -> int:
        return int(amount) if currency.lower() in ZERO_DECIMAL else int(Decimal(amount) * 100)

    def create(self, booking, amount_xof):
        if not self.is_available:
            raise PaymentProviderUnavailable("card")
        currency = self.currency.lower()
        order_id = new_order_ref("TR", booking)
        form = {"amount": self._minor(amount_xof, currency), "currency": currency, "automatic_payment_methods[enabled]": "true",
                "metadata[booking_id]": booking.pk, "metadata[tratra_ref]": order_id, "description": f"Tratra — réservation {booking.pk}"}
        data = _json("card", _call("card", "POST", f"{self._base()}/v1/payment_intents", data=form, headers=self._headers(**{"Idempotency-Key": order_id})))
        if not data.get("id") or not data.get("client_secret"):
            raise PaymentProviderError("card", "Le prestataire n'a pas retourné d'intention de paiement.")
        return {"provider": "card", "provider_ref": data["id"], "client_secret": data["client_secret"], "status": "pending", "requires_customer_action": True,
                "session": {"tratra_ref": order_id}}

    def resume(self, payment):
        if not self.is_available or not payment.transaction_id:
            return {}
        data = _json("card", _call("card", "GET", f"{self._base()}/v1/payment_intents/{payment.transaction_id}", headers=self._headers()), ok=(200,))
        return {"client_secret": data["client_secret"]} if data.get("client_secret") and data.get("status") != "succeeded" else {}

    def verify(self, payment) -> Verification:
        if not self.is_available:
            raise PaymentProviderUnavailable("card")
        if not payment.transaction_id:
            raise PaymentProviderError("card", "Référence de transaction introuvable.")
        data = _json("card", _call("card", "GET", f"{self._base()}/v1/payment_intents/{payment.transaction_id}",
                                   params={"expand[]": "latest_charge"}, headers=self._headers()), ok=(200,))
        raw = str(data.get("status", ""))
        currency = str(data.get("currency", "")).lower()
        divisor = 1 if currency in ZERO_DECIMAL else 100
        received = _decimal(data.get("amount_received") or 0)
        amount = (received / divisor) if raw == "succeeded" and received is not None else (_decimal(data.get("amount")) or Decimal(0)) / divisor
        charge = data.get("latest_charge") if isinstance(data.get("latest_charge"), dict) else {}
        if raw == "succeeded" and charge.get("refunded"):
            state = "refunded"
        elif raw == "succeeded":
            state = "completed"
        elif raw == "canceled":
            state = "failed"
        elif raw in ("requires_payment_method", "requires_confirmation", "requires_action", "processing", "requires_capture"):
            state = "pending"
        else:
            raise PaymentProviderError("card", "Statut de transaction inconnu.")
        return Verification(state, amount, currency.upper(), str((data.get("metadata") or {}).get("tratra_ref", "")), raw)


class CashOnService(Provider):
    """A manual method: it stays unpaid until staff record a real receipt."""

    method = "cash"
    is_available = True

    def create(self, booking, amount_xof):
        return {
            "provider": "cash",
            "status": "pending",
            "requires_customer_action": True,
            "instructions": "Paiement en espèces à confirmer manuellement après la prestation.",
        }


def provider_for_method(method):
    """Return the adapter for a method, failing closed for unsupported flows."""
    providers = {
        "om": OrangeMoney,
        "mtn": MTNMoney,
        "card": StripeCard,
        "cash": CashOnService,
    }
    provider_class = providers.get(method)
    if provider_class is None:
        raise PaymentProviderUnavailable(method)
    return provider_class()


def reset_token_caches() -> None:
    _om_token.reset()
    _mtn_token.reset()
