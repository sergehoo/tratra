from django.db import migrations


# Les offres Entreprise semées par 0026 annonçaient des fonctionnalités qui
# n'existent pas (comptes collaborateurs, facturation centralisée, gestionnaire
# de compte dédié, SLA prioritaire). Elles sont désormais affichées publiquement
# (landing, /company/plans) : on ne garde que ce que la plateforme fournit.
# 0026 est déjà appliquée en base : elle n'est pas modifiée.
SEEDED = {
    "entreprise-mensuel": [
        "Comptes collaborateurs",
        "Facturation centralisée",
        "Tableau de bord B2B",
        "Gestionnaire de compte dédié",
    ],
    "entreprise-annuel": [
        "Tous les avantages Entreprise",
        "2 mois offerts",
        "SLA prioritaire",
    ],
}

CLEANED = {
    "entreprise-mensuel": [
        "Tableau de bord B2B",
        "Profil entreprise vérifié",
        "Réservation d'artisans vérifiés",
    ],
    # 250 000 FCFA/an contre 12 x 25 000 : les 2 mois offerts sont réels.
    "entreprise-annuel": [
        "Tous les avantages Entreprise",
        "2 mois offerts",
    ],
}

NONEXISTENT = {
    "Comptes collaborateurs",
    "Facturation centralisée",
    "Gestionnaire de compte dédié",
    "SLA prioritaire",
}


def clean_features(apps, schema_editor):
    SubscriptionPlan = apps.get_model("handy", "SubscriptionPlan")
    for plan in SubscriptionPlan.objects.filter(slug__in=list(CLEANED)):
        features = plan.features if isinstance(plan.features, list) else []
        if features == SEEDED[plan.slug]:
            cleaned = list(CLEANED[plan.slug])
        else:
            # Liste retouchée via l'admin : on retire seulement les promesses inexistantes.
            cleaned = [item for item in features if item not in NONEXISTENT]
        if cleaned != plan.features:
            plan.features = cleaned
            plan.save(update_fields=["features"])


def restore_features(apps, schema_editor):
    SubscriptionPlan = apps.get_model("handy", "SubscriptionPlan")
    for plan in SubscriptionPlan.objects.filter(slug__in=list(SEEDED)):
        # Ne restaure que les listes laissées telles que ce nettoyage les a écrites.
        if plan.features == CLEANED[plan.slug]:
            plan.features = list(SEEDED[plan.slug])
            plan.save(update_fields=["features"])


class Migration(migrations.Migration):

    dependencies = [
        ("handy", "0027_private_kyc_document_storage"),
    ]

    operations = [
        migrations.RunPython(clean_features, restore_features),
    ]
