"""Pièces KYC : le type est déterminé par le CONTENU (signature), pas par le nom ni le type déclaré (applications mobiles : nom sans extension,
extension d'origine .webp/.heic sur des octets JPEG). Un contenu qui n'est ni PDF, ni JPEG, ni PNG reste refusé quel que soit son nom."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from handy.models import HandymanDocument
from handy.test_eligibility import artisan

pytestmark = pytest.mark.django_db


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(buf, "JPEG")
    return buf.getvalue()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(buf, "PNG")
    return buf.getvalue()


_COUNT = [0]


def _upload(name, content, ctype):
    _COUNT[0] += 1
    pro = artisan(f"kyc_up{_COUNT[0]}", eligible=False)
    api = APIClient()
    api.force_authenticate(pro)
    r = api.post("/handy/handyman-docs/", {"document_type": "id_card", "file": SimpleUploadedFile(name, content, content_type=ctype)}, format="multipart")
    return r, pro


@pytest.mark.parametrize("name,ctype", [("scaled_1234", "application/octet-stream"), ("photo.webp", "image/webp"), ("IMG_0001.HEIC", "image/heic"), ("cni.jpg", "image/jpeg"),
                                         ("cni.JPEG", "image/jpeg")])
def test_a_jpeg_is_accepted_whatever_its_name_or_declared_type_and_stored_with_the_real_type(name, ctype):
    r, pro = _upload(name, _jpeg(), ctype)
    assert r.status_code == 201, r.content
    doc = HandymanDocument.objects.get(handyman__user=pro)
    assert doc.file.name.endswith(".jpg")


def test_png_and_pdf_are_recognized_by_content():
    assert _upload("sans_extension", _png(), "application/octet-stream")[0].status_code == 201
    r, pro = _upload("scan", b"%PDF-1.4 fake", "")
    assert r.status_code == 201 and HandymanDocument.objects.get(handyman__user=pro).file.name.endswith(".pdf")


@pytest.mark.parametrize("name,content,ctype", [("identity.exe", b"MZ\x90\x00 not a document", "application/octet-stream"), ("cni.jpg", b"<html><script>alert(1)</script>", "image/jpeg"),
                                                 ("cni.pdf", b"GIF89a....", "application/pdf"), ("photo.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp")])
def test_the_content_decides_a_wrong_content_is_refused_even_with_a_valid_name(name, content, ctype):
    r, pro = _upload(name, content, ctype)
    assert r.status_code == 400 and "Formats autorisés" in str(r.json()), r.content
    assert not HandymanDocument.objects.filter(handyman__user=pro).exists()
