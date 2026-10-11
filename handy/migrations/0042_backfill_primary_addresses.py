from django.db import migrations
from django.db.models import Q


def backfill(apps, schema_editor):
    """Chaque compte qui avait déjà une adresse (champs historiques du compte) reçoit une adresse principale équivalente.
    Additif : les champs historiques ne sont ni modifiés ni supprimés ; relancer la migration ne duplique rien."""
    User = apps.get_model('handy', 'User')
    UserAddress = apps.get_model('handy', 'UserAddress')
    have = set(UserAddress.objects.values_list('user_id', flat=True))
    batch = []
    for u in User.objects.filter(Q(address__gt='') | Q(city__gt='')).only('id', 'address', 'city', 'country', 'latitude', 'longitude').iterator():
        if u.id in have:
            continue
        batch.append(UserAddress(
            user_id=u.id, label='Adresse principale', country=(u.country or "Côte d'Ivoire")[:80], city=(u.city or '')[:100],
            street=(u.address or '')[:255], latitude=u.latitude, longitude=u.longitude,
            coords_source='manual' if u.latitude is not None else '', is_primary=True,
        ))
        if len(batch) >= 500:
            UserAddress.objects.bulk_create(batch)
            batch = []
    if batch:
        UserAddress.objects.bulk_create(batch)


class Migration(migrations.Migration):
    dependencies = [('handy', '0041_user_addresses')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
