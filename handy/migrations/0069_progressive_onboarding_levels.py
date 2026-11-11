"""Onboarding progressif — reprise des profils existants (colonnes : 0068), SANS attribution de badge.

Séparée de 0068 : les index des nouvelles colonnes doivent être créés avant toute modification de lignes (PostgreSQL :
« cannot CREATE INDEX … because it has pending trigger events » sur une base non vide)."""
import logging

from django.db import DatabaseError, migrations, transaction

logger = logging.getLogger(__name__)

DECISIONS = {"backoffice.kyc.profile_suspended": True, "backoffice.tratra_id.revoked": True, "backoffice.kyc.profile_approved": False,
             "backoffice.kyc.profile_restored": False}


def mark_suspended(apps, schema_editor):
    Profile = apps.get_model("handy", "HandymanProfile")
    Audit = apps.get_model("trust", "AuditEvent")
    last = {}
    rows = (Audit.objects.filter(target_type="handymanprofile", action__in=list(DECISIONS)).order_by("created_at", "id")
            .values_list("target_id", "action"))
    for target_id, action in rows.iterator():
        last[target_id] = DECISIONS[action]
    ids = [pk for pk, suspended in last.items() if suspended and pk]
    for start in range(0, len(ids), 500):
        Profile.objects.filter(pk__in=ids[start:start + 500], is_approved=False).update(suspended=True)


def compute(apps, schema_editor):
    from handy.eligibility import refresh_published

    try:
        with transaction.atomic():
            refresh_published()
    except DatabaseError:
        logger.warning("Calcul des niveaux (publication, commandes, vérification) reporté au démarrage (manage.py eligibility_sync).", exc_info=True)


class Migration(migrations.Migration):

    dependencies = [
        ('handy', '0068_progressive_onboarding'),
        ('trust', '0003_xp_penalties_score_history'),
        ('biometrics', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(mark_suspended, migrations.RunPython.noop),
        migrations.RunPython(compute, migrations.RunPython.noop),
    ]
