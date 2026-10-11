"""Évaluations mutuelles : mission réelle seulement, une note par partie, notes masquées jusqu'à réciprocité ou expiration, scores sans
note inventée, surveillance qui PROPOSE (l'humain décide, avec recours), droits et isolation."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from backoffice.test_people import api as bo_api, staff
from handy.models import Booking, BookingTimeline, Notification, Review
from handy.reviews import review_stats
from handy.test_eligibility import artisan, service
from reputation import reveal, services, watch
from reputation.models import ClientReview, EvaluationContest, EvaluationWatch, WatchDecision
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db
BO = "/handy/backoffice/reputation"


def person(name):
    return User.objects.create_user(name, f"{name}@x.test", "pass1234", is_verified=True)


def client_of(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


def mission(client, pro, status="completed", **kw):
    b = Booking.objects.create(client=client, handyman=pro, address="x", city="x", booking_date=timezone.now() - timedelta(days=1), status=status, **kw)
    if status == "completed":
        BookingTimeline.objects.create(booking=b, status="completed", previous_status="in_progress")
    return b


@pytest.fixture(autouse=True)
def blind(settings):
    settings.EVALUATION_REVEAL_DAYS, settings.EVALUATION_WINDOW_DAYS = 7, 30      # mode « notes masquées » (le défaut de production)


def rate(user, booking, rating=5, **extra):
    return client_of(user).post(f"/handy/bookings/{booking.pk}/evaluation/", {"rating": rating, **extra}, format="json")


def test_only_completed_real_missions_by_their_two_parties_one_each():
    c, pro, stranger = person("ev_c"), artisan("ev_p"), person("ev_x")
    pending = mission(c, pro, "confirmed")
    assert rate(c, pending).json()["code"] == "not_completed"
    done = mission(c, pro)
    assert rate(stranger, done).status_code == 404
    assert rate(c, done, 4, comment="Très ponctuel").status_code == 201
    assert rate(c, done).json()["code"] == "already_evaluated"
    assert rate(pro, done, 5, criteria={"courtesy": 5, "payment": 4}).status_code == 201
    assert rate(pro, done).json()["code"] == "already_evaluated"
    assert Review.objects.filter(booking=done).count() == 1 and ClientReview.objects.filter(booking=done).count() == 1
    assert rate(c, mission(c, pro), 5, comment="Appelez-moi au 0707070707").json()["fields"]["comment"]        # pas de coordonnées dans un avis
    assert rate(pro, mission(c, pro), 9).status_code == 400 and rate(pro, mission(c, pro), 5, criteria={"quality": 5}).status_code == 400   # critères adaptés au rôle évalué


def test_window_and_recurring_occurrences():
    c, pro = person("ev_c2"), artisan("ev_p2")
    old = mission(c, pro)
    BookingTimeline.objects.filter(booking=old).update(at=timezone.now() - timedelta(days=45))
    assert rate(c, old).json()["code"] == "window_closed"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(services, "is_recurring_occurrence", lambda b: True)
        assert rate(c, mission(c, pro)).json()["code"] == "use_contract_evaluation"       # missions de contrat : évaluation périodique/finale du contrat


def test_reciprocal_ratings_stay_hidden_until_both_reply_then_count():
    c, pro = person("ev_c3"), artisan("ev_p3")
    b = mission(c, pro)
    rate(c, b, 1, comment="Décevant")
    assert Review.objects.get(booking=b).revealed_at is None
    assert review_stats(pro.pk)["count"] == 0                                              # note masquée : pas comptée
    seen_by_provider = client_of(pro).get("/handy/me/reviews/").json()["received"]
    assert seen_by_provider == []                                                         # l'artisan ne voit pas encore la note reçue
    assert client_of(pro).get(f"/handy/reviews/{Review.objects.get(booking=b).pk}/").status_code == 404
    assert client_of(c).get("/handy/me/reviews/").json()["given"]                         # l'auteur voit toujours la sienne
    invite = Notification.objects.get(user=pro, notification_type="evaluation_invite")
    assert "1" not in invite.message and "Décevant" not in invite.message                 # la notification ne divulgue pas la note
    rate(pro, b, 5)                                                                       # l'autre partie répond : les deux notes sont révélées
    assert Review.objects.get(booking=b).revealed_at is not None and ClientReview.objects.get(booking=b).revealed_at is not None
    assert review_stats(pro.pk)["count"] == 1 and len(client_of(pro).get("/handy/me/reviews/").json()["received"]) == 1


def test_unanswered_ratings_are_revealed_when_the_delay_expires_and_the_task_is_replayable():
    c, pro = person("ev_c4"), artisan("ev_p4")
    b = mission(c, pro)
    rate(c, b, 4)
    assert reveal.reveal_due() == 0
    Review.objects.filter(booking=b).update(created_at=timezone.now() - timedelta(days=8))
    assert reveal.reveal_due() == 1 and reveal.reveal_due() == 0                           # rejouable : aucun effet double
    assert review_stats(pro.pk)["count"] == 1
    pro.handyman_profile.refresh_from_db()
    assert pro.handyman_profile.rating == 4


def test_zero_delay_keeps_the_legacy_immediate_publication(settings):
    settings.EVALUATION_REVEAL_DAYS = 0
    c, pro = person("ev_c5"), artisan("ev_p5")
    rate(c, mission(c, pro), 5)
    assert review_stats(pro.pk)["count"] == 1


def test_scores_never_invent_a_number_and_history_is_real():
    pro = artisan("ev_p6")
    clients = [person(f"ev_c6{i}") for i in range(4)]
    for i, c in enumerate(clients):
        b = mission(c, pro)
        rate(c, b, 5 if i < 3 else 3)
        rate(pro, b, 4, criteria={"courtesy": 5})
    me = client_of(pro).get("/handy/me/evaluations/").json()
    assert me["provider_score"]["count"] == 4 and me["provider_score"]["average"] == 4.5 and me["provider_score"]["public"]
    assert me["missions_evaluated"] == 4 + 0 and me["history"]["provider"][0]["count"] == 4
    lone = client_of(clients[0]).get("/handy/me/evaluations/").json()
    assert lone["requester_score"]["count"] == 1 and lone["requester_score"]["average"] is None      # 1 note ≠ une réputation : aucune moyenne publiée
    assert client_of(pro).get(f"/handy/users/{clients[0].pk}/requester-score/").json() == {"count": 1, "average": None, "public": False}
    assert client_of(clients[1]).get(f"/handy/users/{clients[0].pk}/requester-score/").status_code == 404      # seulement les parties d'une mission


def test_pending_list_and_isolation_between_users():
    c, pro, other = person("ev_c7"), artisan("ev_p7"), person("ev_o7")
    b = mission(c, pro)
    mine = client_of(c).get("/handy/me/evaluations/").json()["pending"]
    assert [p["booking_id"] for p in mine] == [b.pk] and mine[0]["role"] == "client" and {x["key"] for x in mine[0]["criteria"]} == {"courtesy", "clarity", "availability", "payment"}
    assert client_of(other).get("/handy/me/evaluations/").json()["pending"] == []
    rate(c, b)
    assert client_of(c).get("/handy/me/evaluations/").json()["pending"] == []
    assert client_of(pro).get("/handy/me/evaluations/").json()["pending"][0]["other_party_evaluated"] is True


def test_requester_can_contest_a_revealed_rating_and_staff_decides_with_audit():
    c, pro = person("ev_c8"), artisan("ev_p8")
    b = mission(c, pro)
    rate(pro, b, 1, comment="Injuste")
    cr = ClientReview.objects.get(booking=b)
    assert client_of(c).post(f"/handy/client-reviews/{cr.pk}/contest/", {"reason": "Je conteste cette note"}, format="json").json()["code"] == "not_revealed"
    rate(c, b, 5)                                                                          # les deux ont répondu : révélée
    assert client_of(pro).post(f"/handy/client-reviews/{cr.pk}/contest/", {"reason": "Je ne suis pas concerné"}, format="json").status_code == 404
    assert client_of(c).post(f"/handy/client-reviews/{cr.pk}/contest/", {"reason": "court"}, format="json").status_code == 400
    ok = client_of(c).post(f"/handy/client-reviews/{cr.pk}/contest/", {"reason": "Cette note est injustifiée, le prestataire n'est pas venu"}, format="json")
    assert ok.status_code == 201 and client_of(c).post(f"/handy/client-reviews/{cr.pk}/contest/", {"reason": "Encore une fois la même"}, format="json").json()["code"] == "already_contested"
    mod, support = bo_api(staff("ev_mod", "support")), bo_api(staff("ev_an", "analyst"))
    assert support.get(f"{BO}/contests/").status_code == 403
    cid = mod.get(f"{BO}/contests/").json()["results"][0]["id"]
    assert mod.post(f"{BO}/contests/{cid}/resolve/", {"outcome": "upheld", "reason": "court"}, format="json").status_code == 400
    r = mod.post(f"{BO}/contests/{cid}/resolve/", {"outcome": "upheld", "reason": "Le prestataire n'a pas pu justifier la note"}, format="json")
    assert r.status_code == 200 and ClientReview.objects.get(pk=cr.pk).is_hidden and ClientReview.objects.filter(pk=cr.pk).exists()     # masquée, pas supprimée
    assert AuditEvent.objects.filter(action="backoffice.reputation.contest_upheld").exists()
    assert services.requester_score(c)["count"] == 0
    assert mod.post(f"{BO}/contests/{cid}/resolve/", {"outcome": "rejected", "reason": "Déjà traité ailleurs"}, format="json").status_code == 409


def _lows(pro, n, rating=1):
    for i in range(n):
        Review.objects.create(booking=mission(person(f"lw{pro.pk}_{i}"), pro), rating=rating)
    Review.objects.filter(booking__handyman=pro).update(revealed_at=timezone.now())


def test_detection_proposes_explained_cases_only_with_a_real_sample_and_never_sanctions():
    pro_ok, pro_bad = artisan("wt_ok"), artisan("wt_bad")
    _lows(pro_ok, 4)                                                                       # échantillon insuffisant : rien n'est proposé
    _lows(pro_bad, 6)
    assert watch.scan()["created"] == 1
    w = EvaluationWatch.objects.get()
    assert w.subject_id == pro_bad.pk and w.kind == "low_received" and w.status == "open" and w.evidence["count"] == 6 and "examiner" in w.explanation.lower()
    pro_bad.refresh_from_db()
    assert pro_bad.is_active                                                               # l'IA/la règle propose, ne sanctionne jamais
    assert watch.scan().get("updated") == 1 and EvaluationWatch.objects.count() == 1       # rejouable : pas de doublon


def test_serial_harsh_raters_weigh_less_and_are_flagged_themselves():
    victim = artisan("wt_victim")
    for i in range(6):
        Review.objects.create(booking=mission(person(f"hr{i}"), victim), rating=5 if i % 2 else 4)
    harsh = person("wt_harsh")
    for i in range(5):
        pro = artisan(f"wt_t{i}")
        for j in range(3):                                                                 # chaque prestataire est bien noté par d'autres
            Review.objects.create(booking=mission(person(f"gd{i}{j}"), pro), rating=5)
        Review.objects.create(booking=mission(harsh, pro), rating=1)
    Review.objects.update(revealed_at=timezone.now())
    watch.scan()
    kinds = set(EvaluationWatch.objects.filter(subject=harsh).values_list("kind", flat=True))
    assert "low_given" in kinds and not EvaluationWatch.objects.filter(subject=victim).exists()


def test_decisions_need_reasons_follow_due_process_and_ban_needs_a_prior_decision_and_a_super_admin():
    pro = artisan("wt_pro")
    _lows(pro, 6)
    watch.scan()
    w = EvaluationWatch.objects.get()
    ops, admin = bo_api(staff("wt_ops", "ops")), bo_api(staff("wt_adm", "super_admin"))
    support = bo_api(staff("wt_sup", "support"))
    assert support.post(f"{BO}/watch/{w.pk}/decision/", {"decision": "suspend", "reason": "Motif suffisamment long"}, format="json").status_code == 403    # pas de gestion des comptes
    assert ops.post(f"{BO}/watch/{w.pk}/decision/", {"decision": "warn", "reason": "court"}, format="json").status_code == 400
    assert admin.post(f"{BO}/watch/{w.pk}/decision/", {"decision": "ban", "reason": "Bannissement direct sans préavis"}, format="json").status_code == 400   # exige un avertissement/une suspension
    assert ops.post(f"{BO}/watch/{w.pk}/decision/", {"decision": "investigate", "reason": "Vérification des missions concernées"}, format="json").status_code == 200
    assert ops.post(f"{BO}/watch/{w.pk}/decision/", {"decision": "warn", "reason": "Premier avertissement motivé"}, format="json").json()["status"] == "warned"
    assert Notification.objects.filter(user=pro, notification_type="system", title="Avertissement").exists()
    assert ops.post(f"{BO}/watch/{w.pk}/decision/", {"decision": "ban", "reason": "Après avertissement, récidive constatée"}, format="json").status_code == 403    # Super Admin requis
    banned = admin.post(f"{BO}/watch/{w.pk}/decision/", {"decision": "ban", "reason": "Après avertissement, récidive constatée"}, format="json")
    assert banned.status_code == 200 and banned.json()["status"] == "banned"
    pro.refresh_from_db()
    assert not pro.is_active
    assert admin.post(f"{BO}/watch/{w.pk}/decision/", {"decision": "appeal", "reason": "Recours reçu par le support le 12/10"}, format="json").status_code == 200      # droit de recours
    back = admin.post(f"{BO}/watch/{w.pk}/decision/", {"decision": "reinstate", "reason": "Recours accepté après vérification"}, format="json")
    assert back.json()["status"] == "cleared"
    pro.refresh_from_db()
    assert pro.is_active
    history = admin.get(f"{BO}/watch/{w.pk}/").json()["history"]
    assert [h["decision"] for h in history] == ["investigate", "warn", "ban", "appeal", "reinstate"]
    assert AuditEvent.objects.filter(action__startswith="backoffice.reputation.watch_").count() == 5
    assert WatchDecision.objects.count() == 5
    watch.scan()
    assert EvaluationWatch.objects.filter(subject=pro, status="open").count() == 0        # classé : pas rouvert sans nouvelle évaluation


def test_backoffice_alerts_and_list_filters():
    pro = artisan("wt_pro2")
    _lows(pro, 6)
    watch.scan()
    admin = bo_api(staff("wt_adm2", "super_admin"))
    rows = admin.get(f"{BO}/watch/?kind=low_received&q={pro.username}").json()["results"]
    assert len(rows) == 1 and rows[0]["priority"] >= 2 and admin.get(f"{BO}/watch/?kind=burst").json()["results"] == []
    assert admin.get(f"{BO}/summary/").json()["watch_open"] == 1
    alerts = admin.get("/handy/backoffice/dashboard/").json()["alerts"]
    assert any(a["key"] == "watch_open" for a in alerts)


def test_engagement_invites_are_optional_deduplicated_and_monthly_by_default():
    from engagements.rules import Rules

    assert Rules.__dataclass_fields__["evaluation_interval_days"].default == 30
    from engagements import tasks

    assert callable(tasks.evaluation_invites)
