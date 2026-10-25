"""Référentiel des métiers (Côte d'Ivoire) : familles, métiers, prestations et synonymes — IDEMPOTENT (voir handy/catalog_seed.py).

Ajoute seulement ce qui manque : aucun métier, aucune prestation ni aucun profil existant n'est supprimé, renommé, déplacé ou masqué.
Retour arrière : sans effet (les catégories ajoutées restent ; les masquer depuis l'administration si besoin)."""
from django.db import migrations


def forwards(apps, schema_editor):
    from handy import catalog_seed

    catalog_seed.apply(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("handy", "0063_catalog_families_keywords"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
