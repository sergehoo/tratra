"""Texte du consentement biométrique (affiché par l'application avant toute capture) : sa version et son empreinte sont enregistrées."""
import hashlib

from django.conf import settings

CONSENT_TEXT = (
    "Pour vérifier que vous êtes bien la personne de votre pièce d'identité, Tratra peut comparer des photos de votre visage, prises maintenant avec la caméra "
    "avant de votre téléphone, à la photo de votre carte d'identité ou de votre passeport. Ces photos sont des données biométriques sensibles.\n\n"
    "• Elles sont transmises par un canal sécurisé, chiffrées et conservées dans un stockage privé, uniquement pour cette vérification.\n"
    "• Elles ne sont jamais publiques et ne servent à aucune autre fin : Tratra ne constitue aucune base de reconnaissance faciale.\n"
    "• Elles sont envoyées uniquement au fournisseur de vérification d'identité de Tratra, jamais à un service d'IA généraliste.\n"
    "• Elles sont supprimées à l'issue de la durée de conservation prévue (indiquée dans la politique de confidentialité) ou dès que vous retirez votre consentement.\n"
    "• Aucune décision n'est prise par la seule machine : en cas de doute, un membre de l'équipe examine votre dossier, et vous pouvez demander un recours.\n"
    "• Vous pouvez refuser : une vérification humaine alternative vous est proposée, sans pénalité."
)


def version() -> str:
    return str(getattr(settings, "BIOMETRIC_CONSENT_VERSION", "2026-10"))


def text_sha256() -> str:
    return hashlib.sha256(f"{version()}\n{CONSENT_TEXT}".encode()).hexdigest()
