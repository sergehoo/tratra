"""Remplit les nouveaux champs de messagerie pour les données existantes (additif, rejouable)."""
from django.db import migrations
from django.db.models import CharField, F, OuterRef, Subquery
from django.db.models.functions import Substr


def backfill(apps, schema_editor):
    Conversation = apps.get_model("handy", "Conversation")
    Message = apps.get_model("handy", "Message")
    Conversation.objects.filter(booking__isnull=True, kind="booking").update(kind="direct")
    Message.objects.filter(is_read=True, read_at__isnull=True).update(read_at=F("created_at"), delivered_at=F("created_at"))
    last = Message.objects.filter(conversation=OuterRef("pk")).order_by("-id")
    Conversation.objects.filter(last_message_at__isnull=True).update(
        last_message_at=Subquery(last.values("created_at")[:1]), last_message_preview=Substr(Subquery(last.values("content")[:1], output_field=CharField()), 1, 160))


class Migration(migrations.Migration):
    dependencies = [("handy", "0046_messaging_realtime")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
