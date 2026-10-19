from django.db import migrations, models

# Métiers qui étaient mis en avant par la page d'accueil quand la liste était écrite en dur dans le code web (même ordre).
# Reprise de cet état éditorial UNE fois : seules les catégories RACINES existantes et actives qui portent ces slugs sont marquées « mises en
# avant » et ordonnées. Aucune catégorie n'est créée, renommée ni supprimée ; les identifiants ne changent pas ; l'administration reprend la main.
HISTORIC_FEATURED = ["plomberie", "electricite", "climatisation", "serrurerie", "peinture", "bricolage", "menage", "jardinage", "mecanique-auto",
                     "assistance-informatique", "demenagement", "maconnerie", "menuiserie", "installation-electromenager"]


def keep_historic_selection(apps, schema_editor):
    Category = apps.get_model("handy", "ServiceCategory")
    for index, slug in enumerate(HISTORIC_FEATURED, start=1):
        Category.objects.filter(slug=slug, parent__isnull=True, is_active=True).update(is_featured=True, position=index * 10)


class Migration(migrations.Migration):

    dependencies = [
        ("handy", "0049_user_deleted_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicecategory",
            name="is_featured",
            field=models.BooleanField(db_index=True, default=False, help_text="Mettre ce métier en avant sur la page d'accueil."),
        ),
        migrations.AddField(
            model_name="servicecategory",
            name="position",
            field=models.PositiveIntegerField(db_index=True, default=100, help_text="Ordre d'affichage : le plus petit d'abord (à égalité, ordre alphabétique)."),
        ),
        migrations.RunPython(keep_historic_selection, migrations.RunPython.noop),
    ]
