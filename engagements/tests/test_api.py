"""API HTTP des engagements : parcours complet, isolation entre parties, idempotence, versions, pièces privées, absence de données sensibles."""
import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from engagements import tasks
from engagements.testing import WEEK, category, person, pro
from handy.models import Notification

pytestmark = pytest.mark.django_db
BASE = "/handy/engagements/"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def client(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


def walk(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk(v, f"{path}.{k}")
            yield f"{path}.{k}"
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, f"{path}[{i}]")


def clean_of_sensitive_keys(payload):
    forbidden = ("phone", "email", "latitude", "longitude", "lat", "lng", "gps", "position", "password", "token")
    keys = [k.rsplit(".", 1)[-1].split("[")[0] for k in walk(payload)]
    return [k for k in keys if k in forbidden]


def posting_body(**over):
    today = timezone.localdate()
    body = dict(category=category().pk, title="Gardien de nuit — résidence", description="Surveillance de la résidence, rondes et accueil des visiteurs.", mission_type="long_term",
                work_relationship="independent", city="Abidjan", start_date=(today + timedelta(days=3)).isoformat(), schedule=WEEK, amount="180000", period="monthly", conditions="Tenue fournie.")
    body.update(over)
    return body


def test_anonymous_requests_are_refused_everywhere():
    anon = client()
    for path in ("rules/", "me/overview/", "postings/", "contracts/", "me/experience/", "contracts/1/", "evidence/payment/1/"):
        assert anon.get(BASE + path).status_code == 401, path


def test_full_journey_posting_to_confirmed_payment_over_http(monkeypatch):
    owner, worker, stranger = person("h_owner"), pro("h_worker"), pro("h_stranger")
    o, w, s = client(owner), client(worker), client(stranger)
    today = timezone.localdate()
    # 1. Besoin : créé en brouillon, publié, visible des prestataires, jamais d'identité de contact.
    r = o.post(BASE + "postings/", posting_body(), format="json", HTTP_IDEMPOTENCY_KEY="posting-create-0001")
    assert r.status_code == 201 and r.data["status"] == "draft"
    replay = o.post(BASE + "postings/", posting_body(), format="json", HTTP_IDEMPOTENCY_KEY="posting-create-0001")
    assert replay.status_code == 201 and replay["Idempotent-Replay"] == "true" and replay.data["id"] == r.data["id"]
    pid = r.data["id"]
    assert s.get(BASE + f"postings/{pid}/").status_code == 404                                   # un brouillon n'est visible que de son auteur
    assert w.post(BASE + f"postings/{pid}/publish/").status_code == 404                          # ni lisible ni publiable par un tiers
    assert o.post(BASE + f"postings/{pid}/publish/").data["status"] == "open"
    listing = w.get(BASE + "postings/?city=abidjan").data
    assert listing["count"] == 1 and listing["results"][0]["can_apply"] is True and not clean_of_sensitive_keys(listing)
    # 2. Candidature, choix, contrat.
    app = w.post(BASE + f"postings/{pid}/apply/", {"message": "Dix ans d'expérience.", "proposed_amount": "175000"}, format="json")
    assert app.status_code == 201
    assert w.post(BASE + f"postings/{pid}/apply/", {}, format="json").status_code == 409
    assert w.get(BASE + f"postings/{pid}/applications/").status_code == 404                      # le candidat ne lit pas les candidatures des autres
    apps = o.get(BASE + f"postings/{pid}/applications/").data["results"]
    assert apps[0]["applicant"]["name"] and "experience" in apps[0]
    assert o.post(BASE + f"applications/{app.data['id']}/decision/", {"decision": "select"}, format="json").data["status"] == "selected"
    made = o.post(BASE + "contracts/", {"application": app.data["id"], "notice_period_days": 10, "payment_day": 5}, format="json")
    assert made.status_code == 201 and made.data["status"] == "draft" and made.data["amount"] == "175000.00" and made.data["my_role"] == "principal"
    cid = made.data["id"]
    assert w.get(BASE + f"contracts/{cid}/").status_code == 404                                  # brouillon invisible du prestataire
    stale = o.patch(BASE + f"contracts/{cid}/", {"title": "Gardien de nuit (équipe A)", "expected_version": made.data["version"] + 5}, format="json")
    assert stale.status_code == 409 and stale.data["code"] == "version_conflict"
    ok = o.patch(BASE + f"contracts/{cid}/", {"title": "Gardien de nuit (équipe A)"}, format="json", HTTP_IF_MATCH=f'"{made.data["version"]}"')
    assert ok.status_code == 200 and ok.data["version"] == made.data["version"] + 1
    assert o.post(BASE + f"contracts/{cid}/propose/").data["status"] == "pending_acceptance"
    detail = w.get(BASE + f"contracts/{cid}/").data
    assert detail["my_role"] == "worker" and "accept" in detail["actions"] and not clean_of_sensitive_keys(detail)
    assert detail["legal_notice"] and detail["rules"]["max_duration_months"] == 60
    assert s.get(BASE + f"contracts/{cid}/").status_code == 404 and s.post(BASE + f"contracts/{cid}/accept/", {"terms_hash": detail["terms_hash"]}, format="json").status_code == 404
    bad = w.post(BASE + f"contracts/{cid}/accept/", {"terms_hash": "0" * 64}, format="json")
    assert bad.status_code == 409 and bad.data["code"] == "terms_changed"
    todo = w.get(BASE + "me/overview/").data
    assert todo["counts"]["pending_acceptance"] == 1 and any(t["kind"] == "accept_contract" for t in todo["todo"])
    acc = w.post(BASE + f"contracts/{cid}/accept/", {"terms_hash": detail["terms_hash"]}, format="json", HTTP_IDEMPOTENCY_KEY="accept-key-00001")
    assert acc.status_code == 200 and acc.data["status"] == "accepted"
    again = w.post(BASE + f"contracts/{cid}/accept/", {"terms_hash": detail["terms_hash"]}, format="json", HTTP_IDEMPOTENCY_KEY="accept-key-00001")
    assert again["Idempotent-Replay"] == "true"
    doc = o.get(BASE + f"contracts/{cid}/document/").data
    assert {a["role"] for a in doc["acceptances"]} == {"principal", "worker"} and doc["terms_hash"] == detail["terms_hash"] and "signature qualifiée" in doc["notice"]
    # 3. Début du contrat, échéances, paiement déclaré par le donneur d'ordre, confirmé par le prestataire.
    start = today + timedelta(days=3)
    tasks.run(start)
    assert o.get(BASE + f"contracts/{cid}/").data["status"] == "active"
    insts = o.get(BASE + f"contracts/{cid}/installments/").data["results"]
    assert len(insts) == 4 and insts[0]["status"] == "scheduled" and insts[0]["total"] == "175000.00" and insts[0]["balance"] == "175000.00"
    due = insts[0]
    day = due["due_date"] if hasattr(due["due_date"], "year") else timezone.datetime.fromisoformat(due["due_date"]).date()
    tasks.run(day)
    monkeypatch.setattr(timezone, "localdate", lambda *a, **k: day)                              # on avance dans le temps : l'échéance est atteinte
    receipt = SimpleUploadedFile("recu.pdf", b"%PDF-1.4\n%recu de paiement\n" + b"0" * 64, content_type="application/pdf")
    paid_on = day.isoformat()
    declared = o.post(BASE + f"installments/{due['id']}/payments/", {"amount": "175000", "method": "mobile_money", "reference": "OM-123", "paid_on": paid_on, "evidence": receipt},
                      format="multipart", HTTP_IDEMPOTENCY_KEY="payment-key-0001")
    assert declared.status_code == 201, declared.data
    pid_pay = declared.data["id"]
    assert declared.data["status"] == "declared" and declared.data["evidence"]["url"].endswith(f"/evidence/payment/{pid_pay}/")
    assert o.post(BASE + f"payments/{pid_pay}/respond/", {"confirm": True}, format="json").status_code == 403           # jamais confirmé par son auteur
    assert s.post(BASE + f"payments/{pid_pay}/respond/", {"confirm": True}, format="json").status_code == 404
    assert any(t["kind"] == "confirm_payment" for t in w.get(BASE + "me/overview/").data["todo"])
    assert w.post(BASE + f"payments/{pid_pay}/respond/", {"confirm": "oui"}, format="json").status_code == 400
    ev = w.get(declared.data["evidence"]["url"])
    assert ev.status_code == 200 and ev["Cache-Control"] == "private, no-store" and ev["X-Content-Type-Options"] == "nosniff" and b"".join(ev.streaming_content).startswith(b"%PDF")
    assert s.get(declared.data["evidence"]["url"]).status_code == 404 and client().get(declared.data["evidence"]["url"]).status_code == 401
    done = w.post(BASE + f"payments/{pid_pay}/respond/", {"confirm": True}, format="json")
    assert done.status_code == 200 and done.data["status"] == "confirmed"
    inst = o.get(BASE + f"installments/{due['id']}/").data
    assert inst["status"] == "paid" and inst["balance"] == "0.00" and len(inst["payments"]) == 1 and not clean_of_sensitive_keys(inst)
    assert Notification.objects.filter(user=owner, notification_type="payment_confirmed").exists()
    history = o.get(BASE + f"contracts/{cid}/history/").data
    assert history["count"] >= 6 and history["results"][0]["at"] >= history["results"][-1]["at"]
    assert "payment_confirmed" in [e["type"] for e in history["results"]]
    assert s.get(BASE + f"contracts/{cid}/history/").status_code == 404


def test_validation_errors_are_typed_json_and_unknown_routes_never_leak():
    owner = person("v_owner")
    o = client(owner)
    r = o.post(BASE + "postings/", {"title": "x"}, format="json")
    assert r.status_code == 400 and r.data["code"] == "invalid" and "category" in r.data["fields"]
    assert o.get(BASE + "contracts/999999/").status_code == 404 and o.get(BASE + "installments/999999/").status_code == 404
    assert o.get(BASE + "contracts/?limit=abc").status_code == 400
    assert o.get(BASE + "rules/").data["default"]["allow_employment"] is False
    assert o.get(BASE + f"rules/?category={category().pk}").data["max_duration_months"] == 60


def test_calendar_replacements_evaluations_and_disputes_over_http():
    owner, worker, sub = person("c_owner"), pro("c_worker"), pro("c_sub")
    o, w, sb = client(owner), client(worker), client(sub)
    today = timezone.localdate()
    start = today + timedelta(days=1)
    from engagements.testing import make_contract
    c = make_contract(owner, worker, start=today, today=today, months=12, schedule=[{"weekday": d, "start": "08:00", "end": "12:00"} for d in range(7)])
    start = today
    tasks.run(start)
    cal = w.get(BASE + f"contracts/{c.pk}/calendar/?start={start}&end={start + timedelta(days=10)}").data
    shifts = [e for e in cal["events"] if e["kind"] == "shift"]
    assert len(shifts) == 11 and not clean_of_sensitive_keys(cal)
    assert w.get(BASE + f"contracts/{c.pk}/calendar/?start=2027-01-01&end=2029-01-01").status_code == 400
    ev = w.post(BASE + f"contracts/{c.pk}/events/", {"kind": "leave", "date": (start + timedelta(days=20)).isoformat(), "note": "Congé convenu"}, format="json")
    assert ev.status_code == 201 and ev.data["can_cancel"] is True and ev.data["can_respond"] is False
    assert w.post(BASE + f"events/{ev.data['id']}/respond/", {"approve": True}, format="json").status_code == 403
    assert o.post(BASE + f"events/{ev.data['id']}/respond/", {"approve": True}, format="json").data["status"] == "approved"
    rep = w.post(BASE + f"contracts/{c.pk}/replacements/", {"shift": shifts[3]["id"], "replacement_worker": sub.pk, "note": "Rendez-vous"}, format="json")
    assert rep.status_code == 201 and rep.data["replacement_status"] == "proposed"
    mine = sb.get(BASE + "me/replacements/").data["results"]
    assert len(mine) == 1 and mine[0]["can_answer_replacement"] is True and sb.get(BASE + f"contracts/{c.pk}/").status_code == 404        # le remplaçant ne voit pas le contrat
    assert sb.post(BASE + f"events/{rep.data['id']}/replacement/respond/", {"accept": True}, format="json").data["replacement_status"] == "accepted"
    assert o.post(BASE + f"events/{rep.data['id']}/respond/", {"approve": True}, format="json").data["status"] == "approved"
    # Présence déclarée (sans position) puis confirmée.
    first = shifts[0]
    assert first["can_declare_attendance"] is True and first["can_confirm_attendance"] is False
    assert o.post(BASE + f"events/{first['id']}/attendance/", {}, format="json").status_code == 403
    declared = w.post(BASE + f"events/{first['id']}/attendance/", {"actual_start": "08:05", "actual_end": "12:00"}, format="json", HTTP_IDEMPOTENCY_KEY="attend-key-0001")
    assert declared.status_code == 200 and declared.data["attendance_status"] == "declared" and not clean_of_sensitive_keys(declared.data)
    assert w.post(BASE + f"events/{first['id']}/attendance/respond/", {"confirm": True}, format="json").status_code == 403
    assert o.post(BASE + f"events/{first['id']}/attendance/respond/", {"confirm": True}, format="json").data["attendance_status"] == "confirmed"
    # Évaluation périodique trop tôt, litige et unicité.
    early = o.post(BASE + f"contracts/{c.pk}/evaluations/", {"kind": "periodic", "rating": 5}, format="json")
    assert early.status_code == 409 and early.data["code"] == "too_early"
    d = o.post(BASE + f"contracts/{c.pk}/disputes/", {"kind": "planning", "reason": "Désaccord sur les heures de la semaine passée."}, format="json")
    assert d.status_code == 201 and d.data["status"] == "open"
    assert o.post(BASE + f"contracts/{c.pk}/disputes/", {"kind": "planning", "reason": "Désaccord sur les heures de la semaine passée."}, format="json").status_code == 409
    assert Notification.objects.filter(user=worker, notification_type="engagement_dispute").exists()
    assert not any(t["kind"] == "answer_replacement" for t in sb.get(BASE + "me/overview/").data["todo"])


def test_openapi_schema_documents_the_engagement_routes():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = [p for p in schema["paths"] if p.startswith("/handy/engagements/")]
    assert len(paths) >= 40
    assert all(any("Engagements" in (op.get("tags") or []) for op in schema["paths"][p].values() if isinstance(op, dict)) for p in paths)


def test_worker_search_returns_only_verified_professionals_with_public_names_and_a_minimum_query():
    me, verified, unverified = person("ws_me"), pro("ws_marie"), pro("ws_mario")
    verified.first_name, verified.last_name = "Marie", "Kouassi"
    verified.save()
    from handy.testing import make_eligible  # noqa: F401
    from handy.models import HandymanProfile
    unverified.first_name = "Marius"
    unverified.save()
    HandymanProfile.objects.filter(user=unverified).update(is_approved=False)
    c = client(me)
    assert c.get(BASE + "workers/?q=m").data["results"] == []                                       # 2 caractères minimum
    rows = c.get(BASE + "workers/?q=mar").data["results"]
    assert [r["name"] for r in rows] == ["Marie K."] and set(rows[0]) == {"id", "name", "commune"}   # jamais de téléphone ni d'e-mail ; non vérifié exclu
    assert client(verified).get(BASE + "workers/?q=marie").data["results"] == []                    # on ne se propose pas soi-même
