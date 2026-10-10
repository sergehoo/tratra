"""Contrôles de déploiement (`manage.py check --deploy`) propres à la sécurité de l'administration. Avertissements, jamais de blocage :
un assouplissement volontaire reste possible, mais il est visible dans les journaux de démarrage."""
from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def admin_security(app_configs, **kwargs):
    out = []
    if settings.DEBUG:
        return out
    if not getattr(settings, "BACKOFFICE_MFA_REQUIRED", False):
        out.append(Warning("La double authentification des comptes d'administration est désactivée.", hint="Définir BACKOFFICE_MFA_REQUIRED=1 (défaut en production).", id="tratra.W001"))
    if getattr(settings, "LEGACY_STAFF_BYPASS", True):
        out.append(Warning("LEGACY_STAFF_BYPASS est actif : le personnel historique sans rôle garde un accès global à l'ancienne API.",
                           hint="Attribuer les rôles (manage.py assign_legacy_staff_roles) puis définir LEGACY_STAFF_BYPASS=0.", id="tratra.W002"))
    return out


@register(Tags.security, deploy=True)
def payment_providers(app_configs, **kwargs):
    """Un prestataire configuré avec une devise de bac à sable (≠ XOF) en production : les paiements « réussis » ne seraient pas de l'argent réel."""
    out = []
    if settings.DEBUG:
        return out
    from handy.services.gateway import provider_for_method

    for method in ("om", "mtn", "card"):
        provider = provider_for_method(method)
        if provider.is_available and provider.currency != "XOF":
            out.append(Warning(f"Le prestataire de paiement « {method} » est configuré en devise {provider.currency} (bac à sable ?).",
                               hint="En production : devise XOF et identifiants de production (voir docs/paiements.md).", id="tratra.W003"))
    return out
