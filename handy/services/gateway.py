# handy/services/gateway.py
from abc import ABC, abstractmethod


class Provider(ABC):
    """Interface des fournisseurs de paiement.

    Seule `create` est obligatoire : c'est elle qui initialise la transaction.
    `capture`/`refund` ont une implémentation par défaut « non supportée » afin
    qu'un provider puisse être instancié même s'il ne les gère pas encore
    (évite `TypeError: Can't instantiate abstract class`).
    """

    @abstractmethod
    def create(self, booking, amount_xof: int) -> dict: ...

    def capture(self, provider_ref: str) -> dict:
        raise NotImplementedError(f"{type(self).__name__}.capture non implémenté")

    def refund(self, provider_ref: str, amount_xof: int) -> dict:
        raise NotImplementedError(f"{type(self).__name__}.refund non implémenté")


class OrangeMoney(Provider):
    def create(self, booking, amount_xof):
        # TODO(S3): brancher l'API Orange Money réelle (retourne redirect_url / otp_ref)
        return {"provider": "om", "provider_ref": f"om_tx_{booking.id}", "status": "pending"}


class MTNMoney(Provider):
    def create(self, booking, amount_xof):
        # TODO(S3): brancher l'API MTN MoMo réelle
        return {"provider": "mtn", "provider_ref": f"mtn_tx_{booking.id}", "status": "pending"}


class StripeCard(Provider):
    def create(self, booking, amount_xof):
        # TODO(S3): créer un PaymentIntent Stripe et retourner le client_secret
        return {"provider": "card", "provider_ref": f"card_tx_{booking.id}", "status": "pending"}