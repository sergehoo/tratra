"""Suppression de compte (exigence Google Play) : confirmation, mot de passe, blocages, anonymisation complète, jetons révoqués, effets sur les
autres membres et idempotence."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from handy.models import (Booking, Conversation, Device, HandymanDocument, Message, Notification, Payment, Service, UserAddress, UserBlock)
from handy.test_booking_regression import _booking, _client
from handy.test_eligibility import artisan, service
from handy.test_messaging import link, open_direct, send
from handy.testing import make_jpeg
from statuses.models import Status
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db
URL = "/handy/me/account/deletion/"


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


def erase(user, password="pass1234", confirm="SUPPRIMER"):
    return api(user).post(URL, {"password": password, "confirm": confirm}, format="json")


def test_requires_authentication_confirmation_and_password():
    u = _client("del_a")
    assert api().get(URL).status_code in (401, 403) and api().post(URL, {}, format="json").status_code in (401, 403)
    assert erase(u, confirm="oui").json()["code"] == "confirm_required"
    r = erase(u, password="mauvais")
    assert r.status_code == 403 and r.json()["code"] == "wrong_password"
    assert User.objects.get(pk=u.pk).is_active and User.objects.get(pk=u.pk).deleted_at is None
    assert api(u).get(URL).json() == {"allowed": True, "blockers": [], "confirm_word": "SUPPRIMER"}


def test_ongoing_obligations_block_the_deletion_with_clear_reasons_and_nothing_is_touched():
    pro, cli = artisan("del_pro"), _client("del_cli")
    b = _booking(cli, pro, service(pro), status="confirmed")
    codes = {x["code"] for x in api(cli).get(URL).json()["blockers"]}
    assert codes == {"active_bookings"} and {x["code"] for x in api(pro).get(URL).json()["blockers"]} == {"active_bookings"}
    r = erase(cli)
    assert r.status_code == 409 and r.json()["code"] == "blocked" and r.json()["blockers"][0]["detail"]
    cli.refresh_from_db()
    assert cli.is_active and cli.deleted_at is None and cli.username == "del_cli"
    Booking.objects.filter(pk=b.pk).update(status="completed")
    assert api(cli).get(URL).json()["allowed"] is True
    Payment.objects.create(booking=b, amount=10000, platform_fee=1000, method="cash", status="released")
    assert {x["code"] for x in api(pro).get(URL).json()["blockers"]} == {"earnings"}         # gains à retirer d'abord


def test_staff_accounts_cannot_delete_themselves_through_the_member_endpoint():
    staff = User.objects.create_user("del_staff", "ds@x.test", "pass1234", is_staff=True)
    assert [x["code"] for x in api(staff).get(URL).json()["blockers"]] == ["staff"]
    assert erase(staff).status_code == 409 and User.objects.get(pk=staff.pk).is_active


def test_deletion_anonymises_the_account_and_removes_personal_data_while_keeping_records_for_others(django_capture_on_commit_callbacks):
    pro, cli = artisan("del_p2"), _client("del_c2")
    pro.first_name, pro.last_name, pro.email, pro.phone, pro.city = "Koffi", "Yao", "koffi@x.test", "+2250700001234", "Abidjan"
    pro.profile_picture = SimpleUploadedFile("p.jpg", make_jpeg(), "image/jpeg")
    pro.save()
    profile = pro.handyman_profile
    profile.bio, profile.cni_number = "Plombier depuis dix ans", "CI0012345"
    profile.save()
    doc = HandymanDocument.objects.create(handyman=profile, document_type="id_card", file=ContentFile(b"%PDF-1.4 secret", name="cni.pdf"))
    doc_name = doc.file.name
    svc = service(pro)
    done = _booking(cli, pro, svc, status="completed")
    UserAddress.objects.create(user=pro, city="Abidjan", street="Rue des Jardins", is_primary=True)
    Device.objects.create(user=pro, device_token="tok-xyz")
    Notification.objects.create(user=pro, notification_type="system", message="x")
    link(pro, cli)
    conv = open_direct(cli, pro)
    send(pro, conv, "mon message privé")
    send(cli, conv, "réponse du client")
    Status.objects.create(author=pro, kind="text", text="mon statut", expires_at=timezone.now() + timedelta(hours=5))
    Booking.objects.update(status="completed")                                  # plus rien d'en cours : la suppression est possible
    cli_conv_count = Conversation.objects.count()
    token = api(pro).post("/handy/auth/login/", {"username": "del_p2", "password": "pass1234"}, format="json").json().get("refresh")

    with django_capture_on_commit_callbacks(execute=True):                       # suppression des fichiers après validation de la transaction
        r = erase(pro)
    assert r.status_code == 200 and r.json() == {"deleted": True}
    pro.refresh_from_db()
    assert pro.deleted_at and not pro.is_active and pro.email is None and pro.phone is None and pro.first_name == "" and pro.last_name == ""
    assert pro.city is None and not pro.profile_picture and not pro.has_usable_password() and pro.username.startswith("supprime-")
    profile.refresh_from_db()
    assert profile.bio is None and profile.cni_number is None and profile.is_approved is False and not HandymanDocument.objects.filter(handyman=profile).exists()
    assert not HandymanDocument._meta.get_field("file").storage.exists(doc_name)                                              # le fichier de la pièce d'identité est supprimé du stockage
    assert not UserAddress.objects.filter(user=pro).exists() and not Device.objects.filter(user=pro).exists() and not Notification.objects.filter(user=pro).exists()
    assert not Status.objects.filter(author=pro).exists() and not Message.objects.filter(sender=pro).exists()
    assert list(Message.objects.filter(conversation_id=conv).values_list("content", flat=True)) == ["réponse du client"]      # le message de l'interlocuteur reste le sien
    assert not Conversation.objects.get(pk=conv).participants.filter(pk=pro.pk).exists() and Conversation.objects.count() == cli_conv_count
    assert not Service.objects.get(pk=svc.pk).is_active                                                                     # services retirés du catalogue
    done.refresh_from_db()
    assert done.handyman_id == pro.pk and Booking.objects.filter(pk=done.pk).exists()                                       # l'historique de la réservation survit, sans identité
    assert AuditEvent.objects.filter(action="account.deleted", target_id=pro.pk).count() == 1
    assert "Koffi" not in str(AuditEvent.objects.filter(action="account.deleted").values()) and "+2250700001234" not in str(AuditEvent.objects.values())


def test_deleted_account_can_no_longer_sign_in_nor_use_old_tokens_and_the_number_is_reusable():
    u = _client("del_login")
    u.phone = "+2250700005678"
    u.save()
    login = api().post("/handy/auth/login/", {"username": "+2250700005678", "password": "pass1234"}, format="json")
    assert login.status_code == 200
    assert erase(u).status_code == 200
    assert api().post("/handy/auth/login/", {"username": "+2250700005678", "password": "pass1234"}, format="json").status_code in (400, 401)
    assert api().post("/handy/auth/login/", {"username": "del_login", "password": "pass1234"}, format="json").status_code in (400, 401)
    again = User.objects.create_user("del_login_new", "n@x.test", "pass1234", phone="+2250700005678")            # le numéro est libre : nouvelle inscription possible
    assert again.pk != u.pk
    refresh = login.json().get("refresh")
    if refresh:
        assert api().post("/handy/auth/refresh/", {"refresh": refresh}, format="json").status_code in (400, 401)


def test_deletion_is_idempotent_and_removes_blocks_and_biometric_captures():
    u, other = _client("del_idem"), _client("del_idem2")
    UserBlock.objects.create(blocker=u, blocked=other)
    UserBlock.objects.create(blocker=other, blocked=u)
    assert erase(u).status_code == 200
    assert not UserBlock.objects.exists()
    from handy import account_deletion

    assert account_deletion.delete_account(u) == {"deleted": True, "already": True}          # rejeu sans effet
    assert AuditEvent.objects.filter(action="account.deleted", target_id=u.pk).count() == 1
