from decimal import Decimal

from django.db import migrations


# Offres par défaut — idempotent (get_or_create par slug). Modifiables ensuite via l'admin.
DEFAULT_PLANS = [
    {
        "slug": "tratra-plus",
        "name": "Tratra+",
        "audience": "client",
        "price": Decimal("2000"),
        "interval": "monthly",
        "features": [
            "Support prioritaire",
            "Réservations illimitées",
            "Annulation gratuite (selon politique)",
        ],
    },
    {
        "slug": "pro-artisan",
        "name": "Pro Artisan",
        "audience": "handyman",
        "price": Decimal("5000"),
        "interval": "monthly",
        "features": [
            "Mise en avant dans les résultats",
            "0% de commission sur la première mission du mois",
            "Badge Pro vérifié",
            "Statistiques avancées",
        ],
    },
    {
        "slug": "entreprise-mensuel",
        "name": "Entreprise",
        "audience": "business",
        "price": Decimal("25000"),
        "interval": "monthly",
        "features": [
            "Comptes collaborateurs",
            "Facturation centralisée",
            "Tableau de bord B2B",
            "Gestionnaire de compte dédié",
        ],
    },
    {
        "slug": "entreprise-annuel",
        "name": "Entreprise (annuel)",
        "audience": "business",
        "price": Decimal("250000"),
        "interval": "yearly",
        "features": [
            "Tous les avantages Entreprise",
            "2 mois offerts",
            "SLA prioritaire",
        ],
    },
]


def seed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("handy", "SubscriptionPlan")
    for p in DEFAULT_PLANS:
        SubscriptionPlan.objects.get_or_create(
            slug=p["slug"],
            defaults={
                "name": p["name"],
                "audience": p["audience"],
                "price": p["price"],
                "interval": p["interval"],
                "features": p["features"],
                "active": True,
            },
        )


def unseed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("handy", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(
        slug__in=[p["slug"] for p in DEFAULT_PLANS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("handy", "0025_alter_user_user_type_companyprofile"),
    ]

    operations = [
        migrations.RunPython(seed_plans, unseed_plans),
    ]
