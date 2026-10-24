"""Modèles de contrat : articles versionnés, clauses selon le métier et le type de relation, rendu des variables.

RÈGLE ABSOLUE : Tratra ne qualifie pas la conformité juridique d'un modèle. Les modèles livrés sont au statut « À valider
juridiquement » ; seul un membre du personnel habilité (« contracts.legal_review ») peut, APRÈS revue par un juriste, les déclarer
« Validé par revue juridique » — jamais « conforme ». Un contrat n'utilise un modèle qu'une fois validé.

Références légales : seules celles dont l'existence est connue sont citées, TOUJOURS marquées « à confirmer par la revue
juridique » (numéro, date, articles applicables, mises à jour). Ce qui n'est pas connu avec certitude (texte réglementaire des
emplois domestiques, barèmes, durées légales) reste un emplacement « [À compléter par la revue juridique] » : rien n'est inventé.
L'OHADA n'est mentionnée que pour les prestations commerciales entrant dans son champ, à apprécier par le juriste.

Variables : {{nom}} remplacées par les conditions du contrat (liste blanche ci-dessous) ; toute autre accolade est laissée telle quelle."""
import re
from typing import Dict, Iterable, List

TO_COMPLETE = "[À compléter par la revue juridique]"

# Variables autorisées dans les articles (aucune expression, aucun accès aux objets : pas d'injection de gabarit).
VARIABLES = {
    "reference": "Référence du contrat", "principal_role": "Qualité du donneur d'ordre (Employeur / Client)",
    "worker_role": "Qualité du professionnel (Salarié / Prestataire)", "principal_name": "Nom du donneur d'ordre",
    "worker_name": "Nom du professionnel", "category": "Métier", "title": "Intitulé du poste ou de la mission",
    "missions": "Missions confiées", "location_city": "Ville du lieu de travail", "start_date": "Date de début",
    "end_date": "Date de fin (ou « durée indéterminée »)", "schedule": "Jours et horaires", "hours_per_week": "Heures par semaine",
    "amount": "Rémunération", "period": "Périodicité de la rémunération", "payment_day": "Jour de paiement",
    "benefits": "Avantages", "conditions": "Conditions particulières", "notice_period_days": "Préavis (jours)",
}
_VAR = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")

# Références proposées, à confirmer : jamais présentées comme vérifiées.
REF_LABOUR_CODE = {"label": "Code du travail de Côte d'Ivoire",
                   "citation": "Loi n° 2015-532 du 20 juillet 2015 portant Code du travail",
                   "status": "à confirmer par la revue juridique (texte en vigueur, articles applicables, modifications)"}
REF_DATA = {"label": "Protection des données à caractère personnel",
            "citation": "Loi n° 2013-450 du 19 juin 2013 relative à la protection des données à caractère personnel",
            "status": "à confirmer par la revue juridique (obligations applicables à Tratra et aux parties)"}
REF_DOMESTIC = {"label": "Emplois domestiques", "citation": TO_COMPLETE,
                "status": "texte réglementaire applicable aux employés de maison à identifier par la revue juridique"}
REF_OHADA = {"label": "OHADA (droit commercial)", "citation": "Acte uniforme relatif au droit commercial général",
             "status": "applicable SEULEMENT si les parties entrent dans son champ d'application — à apprécier par la revue juridique"}


def _a(number: int, key: str, title: str, body: str, *, categories: Iterable[str] = ()) -> Dict:
    return {"number": number, "key": key, "title": title, "body": body, "categories": list(categories)}


def employment_articles() -> List[Dict]:
    """Contrat de travail — emploi domestique (salarié). Structure demandée : objet / obligations / durée, horaires, rémunération,
    repos, congés, rupture, litiges, signatures. Les règles légales (durées, montants, indemnités) restent à compléter."""
    return [
        _a(1, "objet", "Objet, qualification et cadre juridique",
           "Le présent contrat est un CONTRAT DE TRAVAIL : {{worker_name}} est engagé(e) en qualité de salarié(e) par {{principal_name}} "
           "(l'Employeur) pour occuper le poste de « {{title}} » ({{category}}). Les parties reconnaissent un lien de subordination : "
           "le travail est exécuté sous l'autorité de l'Employeur. Le contrat est régi par le droit ivoirien du travail et par le "
           "texte applicable aux emplois domestiques " + TO_COMPLETE + ". Tratra met les parties en relation et conserve la preuve des "
           "conditions acceptées ; Tratra n'est pas l'employeur."),
        _a(2, "obligations_employeur", "Obligations de l'Employeur",
           "L'Employeur fournit le travail convenu, verse la rémunération aux échéances prévues, respecte la durée du travail, les "
           "repos et les congés, assure des conditions de travail sûres et respectueuses de la dignité du/de la salarié(e), et accomplit "
           "les formalités et déclarations qui lui incombent " + TO_COMPLETE + "."),
        _a(3, "obligations_salarie", "Obligations du/de la salarié(e)",
           "Le/la salarié(e) exécute personnellement et avec soin les missions suivantes : {{missions}}. Il/elle respecte les horaires "
           "convenus, signale sans délai toute absence et observe la discrétion sur la vie privée du foyer."),
        _a(4, "duree", "Date de début et durée",
           "Le contrat prend effet le {{start_date}} pour une durée : {{end_date}}. Période d'essai éventuelle : " + TO_COMPLETE + "."),
        _a(5, "lieu_horaires", "Lieu, jours et horaires de travail",
           "Lieu de travail : {{location_city}} (adresse précise connue des seules parties). Jours et horaires : {{schedule}}. Durée "
           "hebdomadaire convenue : {{hours_per_week}} heures, dans la limite de la durée légale " + TO_COMPLETE + "."),
        _a(6, "remuneration", "Rémunération",
           "Rémunération convenue : {{amount}} ({{period}}), payable le {{payment_day}} de chaque mois. Elle ne peut être inférieure au "
           "minimum légal ou conventionnel applicable " + TO_COMPLETE + ". Avantages : {{benefits}}. Les paiements déclarés sur Tratra ne "
           "valent qu'une fois confirmés par l'autre partie ; Tratra ne verse ni n'encaisse la rémunération."),
        _a(7, "repos_conges", "Repos et congés",
           "Le/la salarié(e) bénéficie du repos hebdomadaire et des congés payés prévus par la loi " + TO_COMPLETE + ". Les congés et "
           "absences sont demandés et validés dans le planning du contrat."),
        _a(8, "garde_enfants", "Garde d'enfants",
           "Les consignes de sécurité, d'alimentation et de sortie des enfants sont convenues par écrit entre les parties. Toute "
           "situation d'urgence est signalée immédiatement à l'Employeur.", categories=("nounou", "garde-enfants", "baby-sitting")),
        _a(9, "donnees", "Données personnelles et confidentialité",
           "Chaque partie traite les données personnelles de l'autre uniquement pour l'exécution du contrat, dans le respect de la "
           "réglementation ivoirienne sur la protection des données " + TO_COMPLETE + "."),
        _a(10, "rupture", "Suspension et rupture du contrat",
           "Le contrat peut être suspendu ou rompu dans les cas et selon les formes prévus par la loi " + TO_COMPLETE + ". Préavis "
           "convenu : {{notice_period_days}} jours, sans préjudice des préavis et indemnités légaux " + TO_COMPLETE + "."),
        _a(11, "litiges", "Litiges",
           "Les parties recherchent d'abord une solution amiable (la médiation de Tratra peut être demandée depuis l'application). À "
           "défaut, le litige est porté devant l'instance compétente " + TO_COMPLETE + "."),
        _a(12, "signatures", "Signatures",
           "Chaque partie signe électroniquement sur Tratra (signature électronique simple : identité du compte, date, heure et "
           "empreinte du document). Le document final est scellé par la signature numérique de la plateforme et vérifiable par son QR "
           "code. Conditions particulières : {{conditions}}."),
    ]


def independent_articles() -> List[Dict]:
    """Contrat de prestation de services indépendante : aucun lien de subordination ; OHADA seulement dans son champ."""
    return [
        _a(1, "objet", "Objet, qualification et cadre juridique",
           "Le présent contrat est un CONTRAT DE PRESTATION DE SERVICES : {{worker_name}} (le Prestataire) réalise en toute "
           "indépendance la prestation « {{title}} » ({{category}}) pour {{principal_name}} (le Client). Il n'existe aucun lien de "
           "subordination : le Prestataire organise librement son travail et peut servir d'autres clients. Si la relation réunissait "
           "dans les faits les éléments d'un contrat de travail, elle relèverait du droit du travail. Droit applicable : droit ivoirien ; "
           "l'Acte uniforme OHADA relatif au droit commercial général ne s'applique que si les parties entrent dans son champ "
           + TO_COMPLETE + "."),
        _a(2, "obligations_client", "Obligations du Client",
           "Le Client décrit précisément la prestation attendue, donne accès au lieu d'intervention et règle le prix convenu aux "
           "échéances prévues."),
        _a(3, "obligations_prestataire", "Obligations du Prestataire",
           "Le Prestataire réalise avec soin les missions suivantes : {{missions}}, avec ses propres méthodes, et informe le Client de "
           "toute difficulté. Il est responsable de ses obligations fiscales et sociales d'indépendant " + TO_COMPLETE + "."),
        _a(4, "duree", "Date de début et durée", "La prestation commence le {{start_date}} pour une durée : {{end_date}}."),
        _a(5, "lieu_horaires", "Lieu et créneaux d'intervention",
           "Lieu : {{location_city}} (adresse précise connue des seules parties). Créneaux convenus : {{schedule}}."),
        _a(6, "prix", "Prix et paiement",
           "Prix convenu : {{amount}} ({{period}}), payable le {{payment_day}} de chaque période. Avantages ou frais convenus : "
           "{{benefits}}. Les paiements déclarés sur Tratra ne valent qu'une fois confirmés par l'autre partie ; Tratra ne verse ni "
           "n'encaisse le prix."),
        _a(7, "interruptions", "Interruptions et indisponibilités",
           "Les indisponibilités du Prestataire et les interruptions demandées par le Client sont convenues dans le planning du contrat."),
        _a(8, "donnees", "Données personnelles et confidentialité",
           "Chaque partie traite les données personnelles de l'autre uniquement pour l'exécution du contrat, dans le respect de la "
           "réglementation ivoirienne sur la protection des données " + TO_COMPLETE + "."),
        _a(9, "rupture", "Résiliation",
           "Chaque partie peut mettre fin au contrat en respectant un préavis de {{notice_period_days}} jours ; un manquement grave "
           "permet une résiliation selon les règles applicables " + TO_COMPLETE + "."),
        _a(10, "litiges", "Litiges",
           "Les parties recherchent d'abord une solution amiable (médiation Tratra). À défaut, le litige est porté devant la juridiction "
           "compétente " + TO_COMPLETE + "."),
        _a(11, "signatures", "Signatures",
           "Chaque partie signe électroniquement sur Tratra (signature électronique simple : identité du compte, date, heure et "
           "empreinte du document). Le document final est scellé par la signature numérique de la plateforme et vérifiable par son QR "
           "code. Conditions particulières : {{conditions}}."),
    ]


SEED_TEMPLATES = [
    {"code": "emploi-domestique-salarie", "relationship": "employment", "title": "Contrat de travail — emploi domestique (salarié)",
     "articles": employment_articles, "references": [REF_LABOUR_CODE, REF_DOMESTIC, REF_DATA]},
    {"code": "prestation-independante", "relationship": "independent", "title": "Contrat de prestation de services (indépendant)",
     "articles": independent_articles, "references": [REF_OHADA, REF_DATA]},
]


def render_text(body: str, values: Dict[str, str]) -> str:
    def sub(m):
        key = m.group(1)
        return values.get(key, m.group(0)) if key in VARIABLES else m.group(0)
    return _VAR.sub(sub, body or "")


def applicable(article: Dict, category_slugs: Iterable[str]) -> bool:
    wanted = set(article.get("categories") or [])
    return not wanted or bool(wanted & set(category_slugs))


def render_articles(articles: List[Dict], values: Dict[str, str], category_slugs: Iterable[str]) -> List[Dict]:
    """Articles applicables au métier, renumérotés dans l'ordre, variables remplacées : c'est ce texte qui est figé dans le contrat."""
    slugs = list(category_slugs)
    kept = [a for a in sorted(articles, key=lambda a: a.get("number", 0)) if applicable(a, slugs)]
    return [{"number": i, "key": a["key"], "title": a["title"], "body": render_text(a["body"], values)} for i, a in enumerate(kept, start=1)]


def validate_articles(articles) -> List[str]:
    """Erreurs de structure d'un modèle (liste vide = correct) : articles numérotés, titres et textes présents, variables connues,
    articles obligatoires présents (objet/qualification, obligations des deux parties, signatures)."""
    errors = []
    if not isinstance(articles, list) or not articles:
        return ["Le modèle doit contenir au moins un article."]
    keys = set()
    for i, a in enumerate(articles):
        if not isinstance(a, dict) or not str(a.get("title") or "").strip() or not str(a.get("body") or "").strip():
            errors.append(f"Article {i + 1} : titre et texte obligatoires.")
            continue
        keys.add(a.get("key"))
        unknown = sorted({v for v in _VAR.findall(a["body"]) if v not in VARIABLES})
        if unknown:
            errors.append(f"Article « {a['title']} » : variables inconnues {', '.join(unknown)}.")
    if "objet" not in keys or "signatures" not in keys or not any(str(k).startswith("obligations_") for k in keys):
        errors.append("Articles obligatoires : objet et qualification, obligations des parties, signatures.")
    return errors
