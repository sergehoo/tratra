"""purge_accounts : simulation par défaut, suppression en cascade des objets protégés, refus des flux d'argent et des administrateurs."""
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from handy.models import Booking, HandymanDocument, Payment, Review
from handy.test_eligibility import artisan

pytestmark = pytest.mark.django_db
User = get_user_model()


def _demo():
    client, pro = User.objects.create_user("pg_client", "pg_c@x.test", "pass1234"), artisan("pg_pro")
    b = Booking.objects.create(client=client, handyman=pro, address="x", city="x", booking_date=timezone.now(), status="completed")
    Review.objects.create(booking=b, rating=4)
    Payment.objects.create(booking=b, amount=5000, platform_fee=0, method="cash", status="pending")
    assert HandymanDocument.objects.filter(handyman__user=pro).exists()                   # pièce KYC PROTÉGÉE
    return client, pro, b


def run(*args):
    out = StringIO()
    call_command("purge_accounts", *args, stdout=out)
    return out.getvalue()


def test_dry_run_counts_exactly_what_would_go_and_changes_nothing():
    client, pro, b = _demo()
    text = run("--ids", f"{client.pk},{pro.pk}")
    assert "SIMULATION" in text and "handy.Booking" in text and "handy.HandymanDocument" in text and "--apply" in text
    assert User.objects.filter(pk__in=[client.pk, pro.pk]).count() == 2 and Booking.objects.filter(pk=b.pk).exists() and Payment.objects.filter(booking=b).exists()


def test_apply_removes_accounts_and_every_protected_dependency_in_one_transaction():
    from trust.models import AuditEvent

    client, pro, b = _demo()
    text = run("--ids", f"{client.pk},{pro.pk}", "--apply")
    assert "SUPPRIMÉ" in text
    assert not User.objects.filter(pk__in=[client.pk, pro.pk]).exists() and not Booking.objects.filter(pk=b.pk).exists()
    assert not Payment.objects.filter(booking_id=b.pk).exists() and not Review.objects.filter(booking_id=b.pk).exists() and not HandymanDocument.objects.exists()
    event = AuditEvent.objects.get(action="admin.accounts_purged")
    assert event.data["accounts"] == 2 and "pg_" not in str(event.data)                         # aucune donnée personnelle dans la trace


def test_real_money_blocks_the_purge_unless_explicitly_forced():
    client, pro, b = _demo()
    Payment.objects.filter(booking=b).update(status="held")
    with pytest.raises(CommandError) as e:
        run("--ids", str(client.pk), "--apply")
    assert "flux d'argent" in str(e.value) and User.objects.filter(pk=client.pk).exists()
    assert "SUPPRIMÉ" in run("--ids", f"{client.pk},{pro.pk}", "--apply", "--allow-money")


def test_admin_accounts_unknown_ids_and_bad_input_are_refused():
    admin = User.objects.create_user("pg_adm", "pg_a@x.test", "pass1234", is_staff=True)
    with pytest.raises(CommandError, match="administration"):
        run("--ids", str(admin.pk), "--apply")
    with pytest.raises(CommandError, match="introuvables"):
        run("--ids", "999999")
    with pytest.raises(CommandError):
        run("--ids", "abc")
    with pytest.raises(CommandError, match="au plus"):
        run("--ids", ",".join(str(i) for i in range(100000, 100060)))
    assert User.objects.filter(pk=admin.pk).exists()
