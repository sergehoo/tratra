from django.db import migrations
from django.db.models import F


def reveal_existing(apps, schema_editor):
    """Les avis déjà publiés le restent : leur date de révélation est celle de leur création (aucun avis ne disparaît)."""
    apps.get_model('handy', 'Review').objects.filter(revealed_at__isnull=True).update(revealed_at=F('created_at'))


class Migration(migrations.Migration):
    dependencies = [('handy', '0044_review_revealed_at_and_more')]
    operations = [migrations.RunPython(reveal_existing, migrations.RunPython.noop)]
