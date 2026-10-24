"""Copie calculée de l'éligibilité (`HandymanProfile.published`) : ajout de la colonne puis premier calcul à partir de la règle.

Le calcul appelle le code courant de la règle (handy/eligibility.py) : sur une base rejouée bien plus tard, il peut échouer si la règle
lit une colonne ajoutée par une migration ultérieure. Il est donc fait dans un point de sauvegarde et, en cas d'échec, laissé au
démarrage (`manage.py eligibility_sync`, lancé par l'entrypoint après les migrations) et à la réconciliation périodique."""
import logging

from django.db import DatabaseError, migrations, models, transaction

logger = logging.getLogger(__name__)


def compute(apps, schema_editor):
    from handy.eligibility import refresh_published

    try:
        with transaction.atomic():
            refresh_published()
    except DatabaseError:
        logger.warning("Calcul initial de `published` reporté au démarrage (manage.py eligibility_sync).", exc_info=True)


class Migration(migrations.Migration):

    dependencies = [
        ('handy', '0059_mobile_app_links'),
    ]

    operations = [
        migrations.AddField(
            model_name='handymanprofile',
            name='published',
            field=models.BooleanField(db_index=True, default=False, editable=False),
        ),
        migrations.AlterField(
            model_name='notification',
            name='push_status',
            field=models.CharField(blank=True, choices=[('', 'Non concerné'), ('queued', 'En file'), ('sending', 'Envoi en cours'), ('sent', 'Envoyé'), ('no_device', 'Aucun appareil'), ('disabled', "Désactivé par l'utilisateur"), ('unconfigured', 'Firebase non configuré'), ('failed', 'Échec'), ('obsolete', 'Non envoyé : mission déjà attribuée ou expirée')], default='', max_length=20),
        ),
        migrations.RunPython(compute, migrations.RunPython.noop),
    ]
