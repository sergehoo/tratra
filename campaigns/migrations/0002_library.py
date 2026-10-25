"""30 modèles de campagnes (désactivés) — installation idempotente : un modèle existant n'est jamais réécrit."""
from django.db import migrations


def forwards(apps, schema_editor):
    from campaigns import library

    library.seed(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
