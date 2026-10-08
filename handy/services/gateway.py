# handy/services/gateway.py
from abc import ABC, abstractmethod


class PaymentProviderUnavailable(RuntimeError):
    """Raised when a payment method has no real, configured provider adapter."""

    code = "payment_provider_unavailable"

    def __init__(self, method, message=None):
        self.method = method
        super().__init__(message or f"Le prestataire de paiement « {method} » n'est pas configuré.")


class Provider(ABC):
    """Interface des fournisseurs de paiement.

    Seule `create` est obligatoire : c'est elle qui initialise la transaction.
    `capture`/`refund` ont une implémentation par défaut « non supportée » afin
    qu'un provider puisse être instancié même s'il ne les gère pas encore
    (évite `TypeError: Can't instantiate abstract class`).
    """

    is_available = False

    @abstractmethod
    def create(self, booking, amount_xof: int) -> dict: ...

    def capture(self, provider_ref: str) -> dict:
        raise NotImplementedError(f"{type(self).__name__}.capture non implémenté")

    def refund(self, provider_ref: str, amount_xof: int) -> dict:
        raise NotImplementedError(f"{type(self).__name__}.refund non implémenté")


class OrangeMoney(Provider):
    def create(self, booking, amount_xof):
        # A predictable local reference is not a payment.  Do not create a
        # pending transaction until an actual Orange Money adapter is wired.
        raise PaymentProviderUnavailable("om")


class MTNMoney(Provider):
    def create(self, booking, amount_xof):
        raise PaymentProviderUnavailable("mtn")


class StripeCard(Provider):
    def create(self, booking, amount_xof):
        raise PaymentProviderUnavailable("card")


class CashOnService(Provider):
    """A manual method: it stays unpaid until staff record a real receipt."""

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
