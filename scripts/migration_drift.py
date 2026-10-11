"""Diagnostic LECTURE SEULE : migrations non appliquées dont les objets existent déjà en base.

Usage (depuis l'hôte, sans rien modifier) :
    docker compose run --rm --no-deps -T tratraweb python manage.py shell < scripts/migration_drift.py

Pour chaque migration du plan, signale les tables (CreateModel) et colonnes (AddField) déjà présentes — c'est
exactement ce qui fait échouer `migrate` avec DuplicateColumn / DuplicateTable — puis compare les modèles concernés
au schéma réel (colonnes manquantes, colonnes en trop, nullabilité). N'écrit jamais en base.
"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

CLEAN_START = globals().get("CLEAN_START", False)  # tests : rejouer tout le plan comme sur une base vide

executor = MigrationExecutor(connection)
targets = executor.loader.graph.leaf_nodes()
plan = executor.migration_plan(targets, clean_start=CLEAN_START)
if CLEAN_START:
    from django.db.migrations.state import ProjectState

    state = ProjectState()
else:
    state = executor._create_project_state(with_applied_migrations=True)

tables = set(connection.introspection.table_names())
_cols = {}


def columns(table):
    if table not in _cols:
        with connection.cursor() as cur:
            _cols[table] = {c.name: c for c in connection.introspection.get_table_description(cur, table)}
    return _cols[table]


collisions, touched = [], {}
for migration, _backwards in plan:
    for op in migration.operations:
        kind = type(op).__name__
        label = f"{migration.app_label}.{migration.name}"
        try:
            op.state_forwards(migration.app_label, state)
        except Exception:
            continue
        if kind == "CreateModel":
            model = state.apps.get_model(migration.app_label, op.name)
            if model._meta.db_table in tables:
                collisions.append((label, "TABLE", model._meta.db_table))
                touched[(migration.app_label, model._meta.model_name)] = label
        elif kind == "AddField":
            model = state.apps.get_model(migration.app_label, op.model_name)
            col = model._meta.get_field(op.name).column
            if model._meta.db_table in tables and col in columns(model._meta.db_table):
                collisions.append((label, "COLUMN", f"{model._meta.db_table}.{col}"))
                touched[(migration.app_label, model._meta.model_name)] = label

print(f"Migrations à appliquer : {len(plan)}" + (" (simulation base vide)" if CLEAN_START else ""))
print(f"\nObjets DÉJÀ PRÉSENTS en base ({len(collisions)}) — chacun ferait échouer `migrate` :")
for label, kind, obj in collisions:
    print(f"  {label:<75} {kind:<7} {obj}")
if not collisions:
    print("  aucun : `migrate` ne devrait pas rencontrer de doublon.")

print("\nÉcarts modèle ↔ base pour les modèles touchés :")
found = False
for (app, name), label in sorted(touched.items()):
    model = state.apps.get_model(app, name)
    table = model._meta.db_table
    db = columns(table)
    want = {f.column: f for f in model._meta.concrete_fields}
    for col in sorted(set(want) - set(db)):
        found = True
        print(f"  {table}: colonne ABSENTE de la base : {col}   (vue dans {label})")
    for col in sorted(set(db) - set(want)):
        found = True
        print(f"  {table}: colonne EN TROP en base (inconnue du modèle) : {col}   (vue dans {label})")
    for col in sorted(set(want) & set(db)):
        if want[col].null != bool(db[col].null_ok) and not want[col].primary_key:
            found = True
            print(f"  {table}.{col}: null attendu={want[col].null} mais base null_ok={bool(db[col].null_ok)}   (vue dans {label})")
if not found:
    print("  aucun écart de colonnes sur ces modèles.")
