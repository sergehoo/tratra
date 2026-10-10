from django.db import migrations

# Copie figée du classement par type (les migrations ne doivent jamais dépendre du code applicatif).
CATEGORY_BY_TYPE = {
    'profile_incomplete': 'account', 'profile_completed': 'account', 'kyc_approved': 'account', 'kyc_rejected': 'account',
    'booking_request': 'booking', 'booking_confirmed': 'booking', 'booking_cancelled': 'booking',
    'booking_started': 'booking', 'booking_completed': 'booking', 'booking_status': 'booking',
    'dispute_opened': 'booking', 'dispute_resolved': 'booking',
    'payment_received': 'payment', 'refund_issued': 'payment',
    'review_received': 'review', 'review_reply': 'review',
    'message_received': 'message',
    'live_en_route': 'live', 'live_arrived': 'live',
    'business_request': 'business', 'business_update': 'business', 'business_reminder': 'business',
    'announcement': 'announcement',
}


def backfill(apps, schema_editor):
    Notification = apps.get_model('handy', 'Notification')
    for ntype, category in CATEGORY_BY_TYPE.items():
        Notification.objects.filter(notification_type=ntype).update(category=category)
    # Les notifications déjà lues gardent une date de lecture approximative (création).
    Notification.objects.filter(is_read=True, read_at__isnull=True).update(read_at=models_f_created(Notification))


def models_f_created(Notification):
    from django.db.models import F
    return F('created_at')


class Migration(migrations.Migration):
    dependencies = [('handy', '0035_notification_center')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
