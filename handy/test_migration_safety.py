"""Migrations NON DESTRUCTIVES : un déploiement doit pouvoir être annulé (image précédente + sauvegarde) sans perdre de données, et
l'ancienne version du code doit tourner sur le schéma migré pendant le déploiement. Ce test est un CLIQUET : toute opération qui supprime,
renomme ou impose une colonne obligatoire sans valeur par défaut sur une table existante fait échouer la suite, et exige une revue
explicite (l'ajouter à `REVIEWED`, avec le motif, après avoir prévu la procédure de retour arrière dans docs/deploiement-staging.md)."""
import re

import pytest
from django.core.management import call_command
from django.db.migrations import operations as ops
from django.db.migrations.loader import MigrationLoader
from django.db.models.fields import NOT_PROVIDED

FIRST_PARTY = ("handy", "backoffice", "engagements", "trust", "business", "live", "continuity", "announcements", "notifications")

# Opérations destructives HISTORIQUES, déjà déployées et revues. Ne jamais allonger cette liste à la légère.
REVIEWED = {
    ("handy", "0014_remove_handymanprofile_deposit_balance", "RemoveField", "deposit_balance"),    # champ de dépôt abandonné, valeur toujours nulle
    ("handy", "0015_availabilityslot_bookingroute_bookingtimeline_and_more", "RenameField", "related_id"),
}


def flagged():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    found = set()
    for (app, name), migration in sorted(loader.disk_migrations.items()):
        if app not in FIRST_PARTY:
            continue
        created = {op.name_lower for op in migration.operations if isinstance(op, ops.CreateModel)}
        for op in migration.operations:
            kind = type(op).__name__
            label = getattr(op, "name", None) or getattr(op, "model_name", "") or ""
            if kind in ("RemoveField", "DeleteModel", "RenameField", "RenameModel", "AlterModelTable"):
                found.add((app, name, kind, label))
            elif isinstance(op, ops.RunSQL) and re.search(r"\b(drop|truncate|delete)\b", str(op.sql), re.I):
                found.add((app, name, "RunSQL-destructif", label))
            elif isinstance(op, ops.RunPython) and op.reverse_code is None:
                found.add((app, name, "RunPython-irréversible", getattr(op.code, "__name__", "")))
            elif isinstance(op, ops.AddField) and op.model_name_lower not in created:
                f = op.field
                required = not f.null and f.default is NOT_PROVIDED and not getattr(f, "auto_now", False) and not getattr(f, "auto_now_add", False) and not f.many_to_many
                if required and not (f.blank and f.get_internal_type() in ("CharField", "TextField")):
                    found.add((app, name, "AddField-obligatoire-sans-défaut", op.name))
    return found


def test_no_new_destructive_or_irreversible_migration_operation():
    assert flagged() - REVIEWED == set(), "Opération de migration destructive non revue (voir l'en-tête de ce fichier)."


def test_the_reviewed_list_only_names_operations_that_still_exist():
    assert REVIEWED <= flagged()                       # pas de dérogation fantôme à réutiliser plus tard


@pytest.mark.django_db
def test_models_and_migrations_are_aligned():
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)


def test_no_unused_third_party_app_with_models_is_installed():
    """`django-push-notifications` était installée sans être utilisée (le push passe par `handy/push.py`, FCM v1) : ses migrations, écrites pour un
    autre type de clé primaire, faisaient détecter à `makemigrations --check` un changement à écrire DANS le paquet installé — faux positif qui
    faisait échouer `scripts/staging/verify.sh` dans l'image Docker. Une application installée doit être utilisée ou retirée."""
    from django.apps import apps
    from django.conf import settings

    assert "push_notifications" not in settings.INSTALLED_APPS
    assert not [app.label for app in apps.get_app_configs() if app.label == "push_notifications"]
