"""Justificatifs PDF : un PDF simple passe ; script, lancement, fichier embarqué, chiffrement ou faux PDF sont refusés."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from engagements.services.common import EngagementError
from engagements.services.evidence import clean_evidence

pytestmark = pytest.mark.django_db

SIMPLE = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


def upload(content, name="recu.pdf"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def test_a_plain_pdf_is_accepted_untouched():
    f = upload(SIMPLE)
    assert clean_evidence(f) is f and f.read() == SIMPLE                                   # curseur remis au début : le fichier est stocké en entier


@pytest.mark.parametrize("active", [b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/EmbeddedFiles", b"/RichMedia", b"/SubmitForm", b"/ImportData", b"/GoToR", b"/Encrypt"])
def test_active_or_opaque_pdf_content_is_refused(active):
    with pytest.raises(EngagementError) as e:
        clean_evidence(upload(SIMPLE.replace(b"/Type/Catalog", b"/Type/Catalog/OpenAction<</S" + active + b">>")))
    assert e.value.status == 400 and "evidence" in e.value.extra["fields"]


def test_similar_names_are_not_mistaken_for_active_content():
    f = upload(SIMPLE.replace(b"/Type/Catalog", b"/Type/Catalog/JSONLike 1/Launcher 2"))
    assert clean_evidence(f) is f


def test_a_fake_pdf_and_oversized_files_are_refused():
    with pytest.raises(EngagementError):
        clean_evidence(upload(b"<html><script>alert(1)</script></html>"))
    with pytest.raises(EngagementError) as e:
        clean_evidence(upload(SIMPLE + b" " * (5 * 1024 * 1024)))
    assert "trop lourd" in str(e.value)
