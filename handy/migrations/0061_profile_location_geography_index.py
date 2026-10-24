"""Index GiST sur `geography(location)` des profils : tri « plus proches voisins » de la recherche « près de moi » (handy.proximity.nearest).
L'index géométrique existant (préfiltre ST_DWithin en degrés) est conservé."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('handy', '0060_handymanprofile_published'),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS handy_profile_location_geog_gist ON handy_handymanprofile USING gist (geography(location))",
            "DROP INDEX IF EXISTS handy_profile_location_geog_gist",
        ),
    ]
