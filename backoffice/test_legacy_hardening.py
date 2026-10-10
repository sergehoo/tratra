"""L'ancienne API ne doit pas contourner le RBAC du Back-Office : un compte du personnel doté d'un rôle n'obtient que ce que
son rôle autorise ; le personnel historique sans rôle garde son comportement jusqu'à fermeture du passe-droit."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from backoffice import rbac
from handy.api.staff_access import staff_may
from handy.models import Booking, Dispute, HandymanDocument, Payment, Payout
from handy.services.tracking import can_access_booking_tracking
from handy.test_eligibility import artisan, service

User = get_user_model()
pytestmark = pytest.mark.django_db


def person(name):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="client", is_verified=True, phone=f"+22507000{abs(hash(name)) % 100000:05d}")


def staff(name, role=None, superuser=False):
    rbac.ensure_roles()
    u = User.objects.create_user(name, f"{name}@x.test", "pass1234", is_staff=True, is_superuser=superuser)
    if role:
        u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
    return u


def api(u=None):
    c = APIClient()
    if u:
        c.force_authenticate(u)
    return c


@pytest.fixture
def world():
    c, a = person("lh_cli"), artisan("lh_art")
    b = Booking.objects.create(client=c, handyman=a, status="completed", address="Rue 1", city="Abidjan", booking_date=timezone.now())
    payment = Payment.objects.create(booking=b, amount=Decimal("10000"), platform_fee=Decimal("1000"), method="om", status="held", is_paid=True)
    doc = HandymanDocument.objects.create(handyman=a.handyman_profile, document_type="license", status="pending", file="kyc/x.pdf")
    doc.file.save("cni.pdf", ContentFile(b"%PDF-1.4 secret"), save=True)
    dispute = Dispute.objects.create(booking=b, reporter=c, reason="Retard", status="open")
    return dict(client=c, artisan=a, booking=b, payment=payment, doc=doc, dispute=dispute)


def test_a_marketing_staff_account_gets_no_global_access_on_the_legacy_api(world):
    m = api(staff("lh_mkt", "marketing"))
    assert m.get("/handy/bookings/").json()["count"] == 0 and m.get("/handy/payments/").json()["count"] == 0
    assert m.get("/handy/disputes/").json()["count"] == 0
    assert m.get(f"/handy/handyman-docs/{world['doc'].pk}/download/").status_code == 404                  # pièce KYC : introuvable pour lui
    assert m.get("/handy/handyman-docs/").json()["count"] == 0
    assert m.get("/handy/users/").json()["count"] == 1                                                    # seulement son propre compte
    assert m.post(f"/handy/handyman-docs/{world['doc'].pk}/review/", {"action": "approve"}, format="json").status_code in (403, 404)
    assert m.post(f"/handy/disputes/{world['dispute'].pk}/resolve/", {"action": "none"}, format="json").status_code in (403, 404)
    assert not can_access_booking_tracking(staff("lh_mkt2", "marketing"), world["booking"].pk)             # pas de GPS par simple is_staff


def test_roles_open_exactly_what_they_grant_on_the_legacy_api(world):
    ops, support, finance = api(staff("lh_ops", "ops")), api(staff("lh_support", "support")), api(staff("lh_fin", "finance"))
    doc = world["doc"].pk
    assert ops.get(f"/handy/handyman-docs/{doc}/download/").status_code == 200                           # kyc.review
    assert finance.get(f"/handy/handyman-docs/{doc}/download/").status_code == 404
    assert finance.get("/handy/payments/").json()["count"] == 1 and support.get("/handy/payments/").json()["count"] == 0   # finance.view
    assert support.get("/handy/bookings/").json()["count"] == 1 and finance.get("/handy/bookings/").json()["count"] == 1   # bookings.view
    assert ops.get("/handy/users/").json()["count"] >= 3                                                  # users.view (ops)
    # litiges : le support tranche sans argent, ne rembourse pas ; la finance seule ne tranche pas
    d = world["dispute"].pk
    assert support.post(f"/handy/disputes/{d}/resolve/", {"action": "refund_client", "resolution": "x"}, format="json").status_code == 403
    assert finance.post(f"/handy/disputes/{d}/resolve/", {"action": "none", "resolution": "x"}, format="json").status_code in (403, 404)
    assert support.post(f"/handy/disputes/{d}/resolve/", {"action": "none", "resolution": "Réglé à l'amiable"}, format="json").status_code == 200
    assert ops.post(f"/handy/handyman-docs/{doc}/review/", {"action": "approve"}, format="json").status_code == 200
    # écriture : « bookings.view » seul ne permet pas de modifier la réservation d'autrui
    assert finance.patch(f"/handy/bookings/{world['booking'].pk}/", {"description": "x"}, format="json").status_code in (403, 404)


def test_super_admin_and_superuser_keep_everything(world):
    root = api(staff("lh_root", superuser=True))
    assert root.get("/handy/payments/").json()["count"] == 1 and root.get(f"/handy/handyman-docs/{world['doc'].pk}/download/").status_code == 200
    assert api(staff("lh_sa", "super_admin")).get("/handy/payments/").json()["count"] == 1


def test_historical_staff_without_a_role_is_unchanged_until_the_bypass_is_closed(world):
    legacy = staff("lh_legacy")
    assert api(legacy).get("/handy/payments/").json()["count"] == 1 and staff_may(legacy)
    assert api(legacy).get(f"/handy/handyman-docs/{world['doc'].pk}/download/").status_code == 200
    with override_settings(LEGACY_STAFF_BYPASS=False):
        legacy2 = User.objects.get(pk=legacy.pk)                                                          # cache de droits propre à l'objet
        assert api(legacy2).get("/handy/payments/").json()["count"] == 0 and not staff_may(legacy2)
        assert api(legacy2).get(f"/handy/handyman-docs/{world['doc'].pk}/download/").status_code == 404
    assert not staff_may(person("lh_plain")) and not staff_may(None)


def test_assign_legacy_staff_roles_command_simulates_by_default_and_applies_on_request(capsys):
    legacy, with_role, root = staff("as_legacy"), staff("as_ops", "ops"), staff("as_root", superuser=True)
    call_command("assign_legacy_staff_roles")
    out = capsys.readouterr().out
    assert "1 compte(s)" in out and "Simulation" in out and rbac.user_roles(User.objects.get(pk=legacy.pk)) == set()
    call_command("assign_legacy_staff_roles", "--apply", "--role", "support")
    assert rbac.user_roles(User.objects.get(pk=legacy.pk)) == {"support"} and rbac.user_roles(User.objects.get(pk=with_role.pk)) == {"ops"}
    from django.core.management.base import CommandError
    with pytest.raises(CommandError):
        call_command("assign_legacy_staff_roles", "--apply")
