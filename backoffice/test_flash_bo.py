"""Back-Office Tratra Flash : droits (lecture « bookings.view », réglages « settings.manage », pénalités « trust.manage »), réglages validés
et journalisés, historique expliqué (critères, délais, motifs d'exclusion), supervision et recommandations, contestations décidées par un
humain, outil Tratra AI en lecture seule."""
import json
from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from backoffice.assistant import tools as T
from backoffice.test_people import BO, api, audited, person, staff
from handy.models import User
from flash import services
from flash.models import DispatchConfig, MissionOffer, MissionRequest
from handy.models import Booking, ServiceCategory
from handy.testing import make_eligible
from trust.models import TrustPenalty

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_push(settings):
    settings.FCM_CREDENTIALS_FILE = ""
    settings.FCM_CREDENTIALS_JSON = ""


def handyman(name, **kw):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", user_type="handyman", **kw)


def world():
    cat = ServiceCategory.objects.create(slug="flash-bo", name="Électricité")
    pro = handyman("bo_pro", first_name="Yao", last_name="K")
    profile = pro.handyman_profile
    profile.location, profile.online = Point(-3.99, 5.37, srid=4326), True
    profile.save()
    make_eligible(profile, category=cat)
    client = person("bo_cli", first_name="Awa")
    req = services.create_request(client, category=cat, address="Rue 1", commune="Cocody", amount=12000, lat=5.36, lng=-3.99)
    return cat, pro, client, req


def test_rights_read_for_operations_settings_only_with_the_settings_right():
    _, _, _, req = world()
    support, ops, su = staff("f_sup", "support"), staff("f_ops", "ops"), staff("f_su", superuser=True)
    assert api(support).get(f"{BO}/flash/supervision/").status_code == 200
    assert api(staff("f_mkt", "marketing")).get(f"{BO}/flash/requests/").status_code == 403
    assert api(ops).get(f"{BO}/flash/config/").status_code == 200
    assert api(ops).put(f"{BO}/flash/config/", {"wave_size": 5}, format="json").status_code == 403    # ops n'a pas « settings.manage »
    r = api(su).put(f"{BO}/flash/config/", {"wave_size": 5, "weight_distance": 50}, format="json")
    assert r.status_code == 200 and {f["name"]: f["value"] for f in r.json()["fields"]}["wave_size"] == 5
    assert DispatchConfig.get_solo().weight_distance == 50
    log = audited("flash.config_updated").get()
    assert log.data["changes"]["wave_size"] == [3, 5]
    bad = api(su).put(f"{BO}/flash/config/", {"wave_size": 0}, format="json")
    assert bad.status_code == 400 and "vague" in bad.json()["detail"]
    zero = {k: 0 for k in ("weight_distance", "weight_trust", "weight_rating", "weight_reactivity", "weight_fairness")}
    assert api(su).put(f"{BO}/flash/config/", zero, format="json").status_code == 400


def test_history_explains_rank_response_time_and_exclusions():
    cat, pro, client, req = world()
    offer = MissionOffer.objects.get(request=req)
    services.decline(offer.pk, pro, "too_far")
    su = staff("f_su2", superuser=True)
    rows = api(su).get(f"{BO}/flash/requests/?status=open").json()["results"]
    assert rows and rows[0]["id"] == req.pk and rows[0]["contacted"] == 1
    d = api(su).get(f"{BO}/flash/requests/{req.pk}/").json()
    o = d["offers"][0]
    assert o["pro"] == "Yao K." and o["status"] == "declined" and o["decline_reason"] == "Trop loin" and o["response_seconds"] is not None
    assert {c["key"] for c in o["criteria"]} == {"distance", "trust", "rating", "reactivity", "fairness"}
    kinds = [e["kind"] for e in d["events"]]
    assert kinds[:3] == ["created", "offer_sent", "wave"] and "declined" in kinds
    assert "Rue 1" not in json.dumps(rows)       # la liste n'expose pas l'adresse


def test_supervision_figures_and_explainable_recommendations():
    cat, pro, client, req = world()
    for i in range(12):
        MissionOffer.objects.create(request=req, handyman=handyman(f"x{i}"), wave=1, rank=i + 2, score=40,
                                    expires_at=timezone.now(), status="expired")
    d = api(staff("f_sup3", "support")).get(f"{BO}/flash/supervision/").json()
    assert d["offers"]["expiry_rate"] > 0.5 and d["requests"]["total"] == 1
    assert any("sans réponse" in r["rule"] for r in d["recommendations"])
    assert d["open_requests"][0]["id"] == req.pk


def test_contested_penalty_is_decided_by_a_human_with_a_reason_and_logged():
    cat, pro, client, req = world()
    services.accept(MissionOffer.objects.get(request=req).pk, pro)
    req.refresh_from_db()
    MissionRequest.objects.filter(pk=req.pk).update(assigned_at=timezone.now() - timedelta(hours=2))
    req.booking.transition_to("cancelled", actor=pro)
    p = TrustPenalty.objects.get(user=pro)
    api(pro).post(f"/handy/me/trust/penalties/{p.pk}/contest/", {"reason": "Panne de moto, client prévenu à temps."}, format="json")
    ops, support = staff("f_ops4", "ops"), staff("f_sup4", "support")
    assert api(support).get(f"{BO}/trust/penalties/").status_code == 403          # le support n'a pas « trust.manage »
    rows = api(ops).get(f"{BO}/trust/penalties/?status=contested").json()["results"]
    assert rows[0]["id"] == p.pk and rows[0]["created_by"] == "Constat automatique"
    assert api(ops).post(f"{BO}/trust/penalties/{p.pk}/decide/", {"decision": "cancel", "note": "court"}, format="json").status_code == 400
    r = api(ops).post(f"{BO}/trust/penalties/{p.pk}/decide/", {"decision": "cancel", "note": "Panne vérifiée par appel au client."}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["decided_by"] == "F_Ops4 A."
    assert audited("trust.penalty_cancel").exists()


def test_staff_can_record_a_no_show_only_on_a_precise_mission():
    cat, pro, client, _ = world()
    b = Booking.objects.create(client=client, handyman=pro, status="confirmed", address="x", city="Abidjan", booking_date=timezone.now())
    ops = staff("f_ops5", "ops")
    r = api(ops).post(f"{BO}/trust/penalties/", {"user": pro.pk, "booking": b.pk, "kind": "no_show",
                                                 "explanation": "Absent au rendez-vous, constaté par l'équipe au téléphone."}, format="json")
    assert r.status_code == 201 and r.json()["by_team"] is True
    r = api(ops).post(f"{BO}/trust/penalties/", {"user": pro.pk, "kind": "no_show", "explanation": "x" * 30}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "booking_required"


def test_tratra_ai_reads_flash_supervision_without_changing_anything():
    world()
    before = DispatchConfig.get_solo().updated_at
    result = T.execute(staff("f_fin", "finance"), "flash_overview", {"days": 7})
    body = json.loads(result.content.split("\n", 1)[1])
    assert body["requests"]["total"] == 1 and body["lien"] == "/backoffice/flash" and "Lecture seule" in body["note"]
    assert DispatchConfig.get_solo().updated_at == before
    denied = T.execute(staff("f_mkt2", "marketing"), "flash_overview", {})
    assert "refus" in denied.content.lower() or "droit" in denied.content.lower()
