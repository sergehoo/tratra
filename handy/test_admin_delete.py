"""Suppression de données erronées depuis l'administration : un stockage d'objets indisponible ne doit jamais l'empêcher (500)."""
import io
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import Client
from PIL import Image

from handy.models import Service, ServiceCategory, ServiceImage
from handy.test_eligibility import artisan

pytestmark = pytest.mark.django_db
User = get_user_model()


def _category_with_image():
    pro = artisan("del_pro")
    cat = ServiceCategory.objects.create(name="Erronée", slug="erronee")
    svc = Service.objects.create(handyman=pro, category=cat, title="t", description="d", price_type="fixed", price=1000)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    ServiceImage.objects.create(service=svc, image=ContentFile(buf.getvalue(), name="x.png"))
    return cat


def _admin_delete(cat):
    c = Client()
    c.force_login(User.objects.create_superuser("del_admin", "del@x.test", "pass1234"))
    return c.post("/admin/handy/servicecategory/", {"action": "delete_selected", "_selected_action": [cat.pk], "post": "yes"})


def test_category_with_its_services_and_images_is_deleted():
    cat = _category_with_image()
    assert _admin_delete(cat).status_code == 302
    assert not ServiceCategory.objects.filter(pk=cat.pk).exists() and not ServiceImage.objects.exists() and not Service.objects.exists()


def test_deletion_succeeds_even_if_the_file_storage_is_down(caplog, django_capture_on_commit_callbacks):
    cat = _category_with_image()
    with mock.patch("django.core.files.storage.FileSystemStorage.delete", side_effect=OSError("storage down")), django_capture_on_commit_callbacks(execute=True):
        resp = _admin_delete(cat)
    assert resp.status_code == 302                                                                  # plus de 500
    assert not ServiceCategory.objects.filter(pk=cat.pk).exists() and not ServiceImage.objects.exists()
    assert "exception deleting the file" in caplog.text                                             # django-cleanup journalise le fichier orphelin au lieu de lever


def _login(staff=False, superuser=True):
    c = Client()
    u = User.objects.create_user("adm_del", "adm_del@x.test", "pass1234", is_staff=True, is_superuser=superuser) if not staff else None
    c.force_login(u)
    return c


def _delete_user(client, user):
    return client.post("/admin/handy/user/", {"action": "delete_selected", "_selected_action": [user.pk], "post": "yes"})


def test_a_superuser_can_delete_an_erroneous_account_that_has_badge_history():
    """Reproduit « Impossible de supprimer users … badge award » : l'historique des badges suit le compte supprimé."""
    from handy.models import HandymanDocument
    from trust.models import BadgeAward

    pro = artisan("del_badge")
    assert BadgeAward.objects.filter(profile__user=pro).exists()
    admin = _login()
    blocked = _delete_user(admin, pro)
    assert blocked.status_code == 200 and User.objects.filter(pk=pro.pk).exists()      # les pièces KYC restent PROTÉGÉES (conservation) : à supprimer d'abord
    assert "autorisé à supprimer" not in blocked.content.decode().lower()                  # plus de refus de DROIT sur l'historique des badges (seul reste la protection des pièces)
    HandymanDocument.objects.filter(handyman__user=pro).delete()
    resp = _delete_user(admin, pro)
    assert resp.status_code == 302 and not User.objects.filter(pk=pro.pk).exists()
    assert not BadgeAward.objects.filter(profile__user_id=pro.pk).exists()


def test_the_badge_history_itself_still_cannot_be_deleted_from_its_own_admin():
    from trust.models import BadgeAward

    pro = artisan("del_badge2")
    award = BadgeAward.objects.filter(profile__user=pro).first()
    c = _login()
    c.post("/admin/trust/badgeaward/", {"action": "delete_selected", "_selected_action": [award.pk], "post": "yes"})
    c.post(f"/admin/trust/badgeaward/{award.pk}/delete/", {"post": "yes"})
    assert BadgeAward.objects.filter(pk=award.pk).exists()


def test_a_non_superuser_staff_cannot_delete_the_account_through_the_cascade():
    pro = artisan("del_badge3")
    c = _login(superuser=False)
    resp = _delete_user(c, pro)
    assert User.objects.filter(pk=pro.pk).exists() and resp.status_code in (200, 302, 403)


def test_a_storage_outage_during_an_upload_is_a_clear_503_not_an_opaque_500():
    """Journal de production : « Connect timeout on endpoint URL … minioapi » pendant un dépôt de pièce ou une photo de profil → 500."""
    from botocore.exceptions import ConnectTimeoutError
    from rest_framework.test import APIClient

    pro = artisan("outage_pro", eligible=False)
    api = APIClient()
    api.force_authenticate(pro)
    from django.core.files.uploadedfile import SimpleUploadedFile

    pdf = SimpleUploadedFile("id.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
    with mock.patch("django.core.files.storage.FileSystemStorage.save", side_effect=ConnectTimeoutError(endpoint_url="https://minio.example")):
        r = api.post("/handy/handyman-docs/", {"document_type": "id_card", "file": pdf}, format="multipart")
    assert r.status_code == 503 and r.json()["code"] == "storage_unavailable" and "réessayez" in r.json()["detail"]
    # (la requête est annulée : set_rollback marque la transaction de test, aucune interrogation de la base ensuite)
