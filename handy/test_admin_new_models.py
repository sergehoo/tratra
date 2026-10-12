"""Administration Django : les modèles récents y sont consultables en LECTURE SEULE (changements par le Back-Office, avec motif et audit), sans coordonnées
privées ni empreintes, et n'empêchent pas la suppression d'un compte erroné par un superutilisateur."""
from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from handy.models import Booking, Review, UserAddress
from handy.test_eligibility import artisan
from intelligence.models import AIRun, DocumentAnalysis, RiskCase, RiskDecision
from reputation.models import ClientReview, EvaluationContest, EvaluationWatch, WatchDecision
from transport.models import TransportBand, TransportConfig, TransportConfigVersion, TransportZone

pytestmark = pytest.mark.django_db
User = get_user_model()
READ_ONLY = [UserAddress, Review, ClientReview, EvaluationContest, EvaluationWatch, DocumentAnalysis, AIRun, RiskCase, TransportConfig, TransportZone, TransportBand,
             TransportConfigVersion]


@pytest.fixture
def root():
    c = Client()
    c.force_login(User.objects.create_superuser("adm_root", "adm_root@x.test", "pass1234"))
    return c


def test_recent_models_are_registered_and_cannot_be_created_or_edited_even_by_a_superuser(root):
    rf = root.get("/admin/").wsgi_request
    for model in READ_ONLY:
        ma = admin.site._registry.get(model)
        assert ma is not None, model.__name__
        assert not ma.has_add_permission(rf) and not ma.has_change_permission(rf), model.__name__
    for model in READ_ONLY:
        assert root.get(f"/admin/{model._meta.app_label}/{model._meta.model_name}/").status_code == 200, model.__name__     # la liste s'affiche


def test_configuration_is_never_deletable_and_history_never_in_isolation(root):
    rf = root.get("/admin/").wsgi_request
    for model in (TransportConfig, TransportZone, TransportBand, TransportConfigVersion):
        assert not admin.site._registry[model].has_delete_permission(rf), model.__name__
    # Historique : jamais depuis sa propre liste…
    cfg = TransportConfig.current()
    assert root.post("/admin/transport/transportconfig/", {"action": "delete_selected", "_selected_action": [cfg.pk], "post": "yes"}).status_code in (200, 302)
    assert TransportConfig.objects.filter(pk=cfg.pk).exists()


def test_private_coordinates_and_fingerprints_are_not_shown(root):
    user = User.objects.create_user("adm_addr", "adm_addr@x.test", "pass1234")
    addr = UserAddress.objects.create(user=user, city="Abidjan", street="Rue X", latitude=Decimal("5.123456"), longitude=Decimal("-4.654321"), is_primary=True)
    page = root.get(f"/admin/handy/useraddress/{addr.pk}/change/").content.decode()
    assert "Abidjan" in page and "5.123456" not in page and "-4.654321" not in page
    assert "5.123456" not in root.get("/admin/handy/useraddress/").content.decode()
    pro = artisan("adm_pro")
    doc = pro.handyman_profile.documents.first()
    a = DocumentAnalysis.objects.create(document=doc, file_sha256="a" * 64, id_fingerprint="f1ngerpr1nt" * 5, risk_level="low")
    assert "f1ngerpr1nt" not in root.get(f"/admin/intelligence/documentanalysis/{a.pk}/change/").content.decode()
    User.objects.filter(pk=user.pk).update(latitude=Decimal("5.777777"), longitude=Decimal("-4.888888"))
    assert "5.777777" not in root.get("/admin/handy/user/").content.decode()                   # liste des comptes : plus de coordonnées


def test_a_superuser_deletes_an_account_that_has_addresses_and_surveillance_records(root):
    user = User.objects.create_user("adm_del2", "adm_del2@x.test", "pass1234")
    UserAddress.objects.create(user=user, city="Abidjan", street="Rue Y", is_primary=True)
    watch = EvaluationWatch.objects.create(subject=user, kind="burst", explanation="x")
    WatchDecision.objects.create(watch=watch, decision="investigate", reason="Vérification en cours")
    case = RiskCase.objects.create(subject=user, kind="abnormal_activity", explanation="x")
    RiskDecision.objects.create(case=case, decision="investigate", reason="Vérification en cours")
    r = root.post("/admin/handy/user/", {"action": "delete_selected", "_selected_action": [user.pk], "post": "yes"})
    assert r.status_code == 302 and not User.objects.filter(pk=user.pk).exists()
    assert not UserAddress.objects.exists() and not EvaluationWatch.objects.exists() and not RiskCase.objects.exists()


def test_booking_admin_shows_the_frozen_transport_read_only(root):
    pro, client = artisan("adm_bk_pro"), User.objects.create_user("adm_bk_cli", "adm_bk@x.test", "pass1234")
    b = Booking.objects.create(client=client, handyman=pro, address="x", city="x", booking_date=timezone.now(), transport_fee=1000, transport_quote={"amount": 1000, "reason": "fallback_flat"})
    ma = admin.site._registry[Booking]
    assert "transport_fee" in ma.readonly_fields and "transport_quote" in ma.readonly_fields and "transport_fee" in ma.list_display
    assert root.get(f"/admin/handy/booking/{b.pk}/change/").status_code == 200
