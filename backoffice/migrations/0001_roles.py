from django.db import migrations

ROLES = ["super_admin", "ops", "support", "finance", "marketing", "analyst"]


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for role in ROLES:
        Group.objects.get_or_create(name=f"bo_{role}")


class Migration(migrations.Migration):
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(create_groups, migrations.RunPython.noop)]
