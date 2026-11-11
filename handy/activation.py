"""Activation des commandes d'un professionnel (deuxième niveau du parcours progressif).

Publication, commandes et badge « Vérifié » sont trois niveaux séparés (`handy.eligibility`). Ce module décide du passage au niveau
« commandes » (`HandymanProfile.is_approved`) :

- AUTOMATIQUE dès que l'équipe approuve la pièce d'identité (contrôle documentaire humain) : aucune seconde validation n'est demandée,
  SAUF dossier de risque à haute priorité ouvert ou confirmé sur le compte (`intelligence.RiskCase`) — l'activation reste alors une
  décision de l'équipe (recours manuel : `backoffice.services.approve_profile`) ;
- la vérification faciale exigée par un métier sensible n'est pas décidée ici : la règle des commandes la contrôle à chaque lecture ;
- jamais pour un profil suspendu ou un compte désactivé.

Chaque décision est journalisée (`trust.AuditEvent`) avec son auteur."""
from django.db import transaction

from handy.models import HandymanProfile

ACTIVATED, HELD, UNCHANGED = "activated", "held", "unchanged"
HOLD_STATUSES = ("open", "investigating", "confirmed")


def risk_hold(profile) -> bool:
    """Un dossier de risque à haute priorité (ouvert, en enquête ou confirmé) retient l'activation automatique : l'équipe décide."""
    from intelligence.models import RiskCase

    return RiskCase.objects.filter(subject_id=profile.user_id, priority__gte=3, status__in=HOLD_STATUSES).exists()


@transaction.atomic
def after_document_approved(document, *, by=None) -> str:
    """Appelée après l'approbation d'une pièce : active les commandes si les pièces obligatoires sont toutes approuvées."""
    from trust.models import audit

    profile = HandymanProfile.objects.select_for_update().select_related("user").get(pk=document.handyman_id)
    if profile.is_approved or profile.suspended or not profile.user.is_active or not profile.has_required_kyc():
        return UNCHANGED
    if risk_hold(profile):
        audit("kyc.orders_activation_held", actor=by, target=profile, reason="risk_case", document_id=document.pk)
        return HELD
    profile.is_approved = True
    profile.save(update_fields=["is_approved"])     # copies d'éligibilité et Tratra Trust suivent par signal, dans la transaction
    audit("kyc.orders_activated", actor=by, target=profile, source="document", document_id=document.pk)
    return ACTIVATED
