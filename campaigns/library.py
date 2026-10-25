"""Bibliothèque de 30 modèles de campagnes (Côte d'Ivoire), TOUS DÉSACTIVÉS par défaut : l'équipe les relit, les ajuste et les active
depuis le Back-Office (« Engagement »).

Règles de rédaction : aucune promesse invérifiable (« des centaines d'artisans », « mieux classé »…), aucune fonction non déployée (les
nouveautés portent `feature` : activables seulement si la fonction figure dans DEPLOYED_FEATURES), chaque bouton ouvre un écran du
registre central accessible à l'audience visée. Installation idempotente : un modèle existant (même `key`) n'est jamais réécrit."""
from typing import Dict, List

C, A, E = "clients", "artisans", "companies"


def T(key, name, trigger, audience, title, body, label, action, *, delay=24, inactive=30, age=14, gap=48, marketing=True, push=True,
      feature="", priority=100, progress=()) -> Dict:
    return dict(key=key, name=name, trigger=trigger, audience=audience, title=title, body=body, action_label=label, action_value=action,
                delay_hours=delay, inactive_days=inactive, max_age_days=age, min_gap_hours=gap, marketing=marketing, send_push=push,
                feature=feature, priority=priority, progress=list(progress))


TEMPLATES: List[Dict] = [
    # ── Bienvenue (inscription vérifiée) ─────────────────────────────────────────────────────────────────────────────────────
    T("bienvenue-client", "Bienvenue — client", "welcome", C, "Bienvenue sur Tratra",
      "Plombier, électricien, frigoriste, nounou… Décrivez votre besoin : Tratra vous met en relation avec des artisans vérifiés près de chez vous.",
      "Trouver un pro", "flash_order", delay=0, gap=0, marketing=False, priority=10),
    T("bienvenue-artisan", "Bienvenue — artisan", "welcome", A, "Bienvenue chez Tratra Pro",
      "Complétez votre profil, vérifiez votre identité et publiez vos offres : les clients de votre commune pourront vous trouver et vous réserver.",
      "Mon espace pro", "pro", delay=0, gap=0, marketing=False, priority=10),
    T("bienvenue-entreprise", "Bienvenue — entreprise", "welcome", E, "Bienvenue sur Tratra Business",
      "Centralisez les demandes d'intervention de vos sites, faites-les valider et suivez les artisans vérifiés qui interviennent.",
      "Espace Business", "business", delay=0, gap=0, marketing=False, priority=10),
    # ── Profil incomplet ─────────────────────────────────────────────────────────────────────────────────────────────────────
    T("profil-artisan-j1", "Profil artisan incomplet — J+1", "profile_incomplete", A, "Votre profil est presque prêt",
      "Ajoutez une photo, votre zone d'intervention et vos métiers : un profil complet inspire confiance aux clients.",
      "Compléter mon profil", "pro", delay=24, marketing=False, priority=20),
    T("profil-artisan-j4", "Profil artisan incomplet — J+4", "profile_incomplete", A, "Il ne manque que quelques informations",
      "Votre profil n'est pas encore complet : sans lui, vos offres ne peuvent pas être publiées. Cela prend quelques minutes.",
      "Compléter mon profil", "pro", delay=96, marketing=False, priority=25),
    T("profil-client-adresse", "Profil client — adresse", "profile_incomplete", C, "Gagnez du temps à la commande",
      "Enregistrez votre nom et votre adresse : vos prochaines demandes partiront en un geste, sans ressaisie.",
      "Mes adresses", "addresses", delay=48, marketing=False, priority=60),
    # ── Vérification d'identité (KYC) ────────────────────────────────────────────────────────────────────────────────────────
    T("kyc-artisan-j1", "Identité à vérifier — J+1", "kyc_pending", A, "Vérifiez votre identité",
      "Une photo de votre CNI ou de votre passeport suffit. Une identité vérifiée est obligatoire pour publier vos offres sur Tratra.",
      "Vérifier mon identité", "kyc", delay=24, marketing=False, priority=15, progress=("verified", "profile_complete")),
    T("kyc-artisan-j5", "Identité à vérifier — J+5", "kyc_pending", A, "Votre badge vérifié vous attend",
      "Les clients choisissent plus volontiers un professionnel vérifié. Transmettez votre pièce d'identité depuis l'application.",
      "Vérifier mon identité", "kyc", delay=120, marketing=False, priority=20, progress=("verified", "profile_complete")),
    T("kyc-refusee", "Pièce d'identité refusée", "kyc_rejected", A, "Nouvelle pièce d'identité demandée",
      "Votre pièce n'a pas pu être validée. Reprenez une photo nette, sans reflet ni doigt sur le document, et renvoyez-la.",
      "Renvoyer ma pièce", "kyc", delay=2, gap=0, marketing=False, priority=5),
    # ── Premier service ──────────────────────────────────────────────────────────────────────────────────────────────────────
    T("premiere-offre-j1", "Première offre — J+1", "first_service", A, "Publiez votre première offre",
      "Décrivez une prestation et votre tarif : vos clients pourront vous réserver dès que votre publication est autorisée.",
      "Ajouter une offre", "pro", delay=24, marketing=False, priority=20, progress=("kyc_approved", "publishable")),
    T("premiere-offre-j4", "Première offre — J+4", "first_service", A, "Vos futurs clients vous cherchent",
      "Climatisation, plomberie, électricité, couture… Ajoutez au moins une offre pour apparaître dans les recherches de votre commune.",
      "Ajouter une offre", "pro", delay=96, marketing=False, priority=30, progress=("kyc_approved", "publishable")),
    T("offre-contrat-mensuel", "Offres au mois (mode contractuel)", "first_service", A, "Proposez aussi des contrats au mois",
      "Nounou, chauffeur, gardien, entretien régulier : cochez « Contractuel (mensuel) » sur votre offre pour recevoir des propositions de contrat.",
      "Mes offres", "pro", delay=168, marketing=False, feature="service_modes", priority=60, progress=("publishable",)),
    # ── Première commande ────────────────────────────────────────────────────────────────────────────────────────────────────
    T("premiere-commande-j1", "Première commande — J+1", "first_order", C, "Un dépannage ? Tratra trouve un pro",
      "Décrivez votre besoin : Tratra prévient les artisans vérifiés disponibles près de chez vous et vous confirme celui qui accepte.",
      "Trouvez-moi un pro", "flash_order", delay=24, priority=30),
    T("premiere-commande-j5", "Première commande — J+5", "first_order", C, "Besoin d'un frigoriste ou d'un plombier ?",
      "Parcourez les offres des artisans vérifiés, avec leurs tarifs et les avis de leurs clients, puis réservez en quelques minutes.",
      "Voir les offres", "explore", delay=120, priority=40),
    T("premiere-commande-panne", "Première commande — « J'ai une panne »", "first_order", C, "Une panne ? Décrivez-la simplement",
      "« Mon frigo ne refroidit plus », « écran cassé »… Tratra trouve le bon métier et les artisans près de chez vous.",
      "J'ai une panne", "panne", delay=240, feature="panne", priority=45),
    T("premiere-demande-entreprise", "Première demande — entreprise", "first_order", E, "Votre première demande d'intervention",
      "Déposez une demande pour l'un de vos sites : elle est validée dans votre équipe puis confiée à un artisan vérifié.",
      "Espace Business", "business", delay=48, marketing=False, priority=40),
    # ── Avis ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    T("avis-client-j1", "Avis après intervention — J+1", "review", C, "Comment s'est passée l'intervention ?",
      "Votre avis aide les autres clients à choisir et récompense les artisans sérieux. Il ne prend qu'une minute.",
      "Donner mon avis", "reviews", delay=24, gap=24, marketing=False, priority=35),
    T("avis-client-j4", "Avis après intervention — J+4", "review", C, "Il est encore temps de noter votre artisan",
      "Notez la qualité, la ponctualité et le rapport qualité-prix de votre dernière intervention.",
      "Donner mon avis", "reviews", delay=96, gap=24, marketing=False, priority=50),
    T("avis-artisan-premiers", "Premiers avis — artisan", "artisan_reviews", A, "Obtenez vos premiers avis",
      "Après chaque intervention, rappelez à votre client qu'il peut vous noter sur Tratra : les avis construisent votre réputation.",
      "Ma réputation", "reputation", delay=72, marketing=False, priority=60),
    # ── Inactivité ───────────────────────────────────────────────────────────────────────────────────────────────────────────
    T("inactif-client-30", "Client inactif — 30 jours", "inactive", C, "Tratra est toujours là pour vous",
      "Une fuite, une panne de courant, une clim qui coule ? Décrivez votre besoin, un artisan vérifié vous répond.",
      "Trouver un pro", "flash_order", inactive=30, age=7, priority=70),
    T("inactif-client-60", "Client inactif — 60 jours", "inactive", C, "Retrouvez les artisans vérifiés de Tratra",
      "Plombiers, électriciens, frigoristes, couturiers… Comparez les offres, les tarifs et les avis avant de réserver.",
      "Voir les offres", "explore", inactive=60, age=7, priority=80),
    T("inactif-artisan-14", "Artisan inactif — 14 jours", "inactive", A, "Restez visible sur Tratra",
      "Passez « En ligne » quand vous êtes disponible : vous recevez alors les demandes Tratra Flash de votre zone.",
      "Ma disponibilité", "availability", inactive=14, age=7, marketing=False, priority=50),
    T("inactif-artisan-30", "Artisan inactif — 30 jours", "inactive", A, "Vos offres sont-elles à jour ?",
      "Vérifiez vos tarifs, vos métiers et votre zone : des informations à jour rassurent les clients qui vous découvrent.",
      "Mon espace pro", "pro", inactive=30, age=7, marketing=False, priority=60),
    T("inactif-entreprise-30", "Entreprise inactive — 30 jours", "inactive", E, "Vos sites ont-ils besoin d'un entretien ?",
      "Programmez vos interventions et suivez-les depuis l'Espace Business, avec validation par votre équipe.",
      "Espace Business", "business", inactive=30, age=7, priority=70),
    # ── Nouveautés (activables seulement si la fonction est déployée) ────────────────────────────────────────────────────────
    T("nouveau-trouvez-moi-un-pro", "Nouveauté — Trouvez-moi un professionnel", "news", C, "Nouveau : « Trouvez-moi un professionnel »",
      "Décrivez votre besoin : Tratra prévient les artisans vérifiés disponibles et vous confirme le premier qui accepte.",
      "Essayer", "flash_order", age=7, feature="flash", priority=90),
    T("nouveau-favoris", "Nouveauté — professionnels favoris", "news", C, "Retrouvez vos artisans préférés",
      "Ajoutez un professionnel à vos favoris pour le réserver à nouveau en un geste.",
      "Mes favoris", "favorites", age=7, feature="favorites", priority=90),
    T("nouveau-badge-tratra-id", "Nouveauté — badge Tratra ID", "news", A, "Votre badge Tratra ID",
      "Présentez votre badge à vos clients : en scannant son QR code, ils vérifient que vous êtes un professionnel vérifié.",
      "Mon badge", "badge", age=7, marketing=False, feature="tratra_id", priority=90),
    T("nouveau-missions-au-mois", "Nouveauté — missions au mois", "news", C, "Nouveau : les missions au mois",
      "Nounou, gardien, entretien régulier : publiez un besoin de longue durée et choisissez parmi les candidatures de professionnels vérifiés.",
      "Découvrir", "engagements", age=7, feature="engagements", priority=90),
    T("nouveau-j-ai-une-panne", "Nouveauté — J'ai une panne", "news", C, "Nouveau : « J'ai une panne »",
      "Décrivez votre problème avec vos mots : Tratra trouve le bon métier et les artisans près de chez vous.",
      "J'ai une panne", "panne", age=7, feature="panne", priority=90),
    T("nouveau-metiers-numerique", "Nouveauté — métiers du numérique", "news", C, "Nouveaux métiers : informatique et numérique",
      "Dépannage d'ordinateur, Wi-Fi, vidéosurveillance, création de site : découvrez les métiers du numérique sur Tratra.",
      "Voir les métiers", "categories", age=7, feature="catalogue_families", priority=90),
]


def seed(apps=None) -> int:
    """Installe les modèles manquants (désactivés). Idempotent : un modèle existant n'est jamais modifié."""
    Campaign = apps.get_model("campaigns", "Campaign") if apps is not None else __import__("campaigns.models", fromlist=["Campaign"]).Campaign
    existing = set(Campaign.objects.values_list("key", flat=True))
    rows = [Campaign(is_active=False, **t) for t in TEMPLATES if t["key"] not in existing]
    Campaign.objects.bulk_create(rows)
    return len(rows)
