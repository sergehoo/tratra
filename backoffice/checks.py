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
