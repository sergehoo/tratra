"""Contrôle de la configuration des prestataires de paiement — sans jamais afficher un identifiant, une clé ou un jeton.

    python manage.py payments_check            # chaque méthode : disponible ? devise ? mode ? secrets de webhook présents ?
    python manage.py payments_check --ping     # + obtient un jeton / interroge l'API du prestataire (prouve que les identifiants sont valides)

Les prestataires non configurés restent « indisponibles » : le serveur le dit au client (503) au lieu de simuler un paiement."""
from django.conf import settings
from django.core.management.base import BaseCommand

from handy.services.gateway import PaymentProviderError, PaymentProviderUnavailable, provider_for_method

LABELS = {"om": "Orange Money", "mtn": "MTN MoMo", "card": "Carte (Stripe)", "cash": "Espèces"}
WEBHOOK_SECRETS = {"om": "PAYMENT_OM_WEBHOOK_SECRET", "mtn": "PAYMENT_MTN_WEBHOOK_SECRET", "card": "PAYMENT_CARD_WEBHOOK_SECRET"}


def _mode(method: str) -> str:
    """Bac à sable ou production, déduit de la configuration (jamais d'une valeur secrète)."""
    if method == "om":
        return "bac à sable" if (settings.OM_CURRENCY or "").upper() == "OUV" else "production"
    if method == "mtn":
        return "bac à sable" if (settings.MTN_MOMO_TARGET_ENV or "") == "sandbox" else "production"
    if method == "card":
        key = settings.STRIPE_SECRET_KEY or ""
        return "essai" if key.startswith(("sk_test_", "rk_test_")) else "production"
    return "manuel"


class Command(BaseCommand):
    help = "Vérifie la configuration des prestataires de paiement (Orange Money, MTN MoMo, carte, espèces)."

    def add_arguments(self, parser):
        parser.add_argument("--ping", action="store_true", help="Appel réseau : jeton OAuth / clé acceptée par le prestataire (aucune transaction créée).")

    def handle(self, *args, **opts):
        problems = 0
        for method in ("om", "mtn", "card", "cash"):
            provider = provider_for_method(method)
            ok = bool(provider.is_available)
            line = f"{LABELS[method]:<16} {'DISPONIBLE' if ok else 'indisponible (non configuré)'}"
            if method != "cash" and ok:
                line += f" · mode {_mode(method)} · devise {provider.currency}"
                if provider.currency != "XOF":
                    line += " (≠ XOF : réservé au bac à sable)"
                line += " · webhook HMAC " + ("configuré" if getattr(settings, WEBHOOK_SECRETS[method], "") else "absent (la réconciliation vérifie quand même)")
                if opts["ping"]:
                    try:
                        line += f" · ping : {provider.ping()}"
                    except (PaymentProviderUnavailable, PaymentProviderError) as exc:
                        line += f" · ping REFUSÉ ({exc})"
                        problems += 1
            self.stdout.write(line)
        self.stdout.write("Règle : un encaissement n'est reconnu qu'après vérification serveur-à-serveur ; espèces = confirmation manuelle.")
        if problems:
            raise SystemExit(1)
