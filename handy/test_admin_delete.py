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
