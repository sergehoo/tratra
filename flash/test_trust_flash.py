"""Tratra Trust × Flash : XP séparés du score, gagnés seulement sur missions terminées (plafond anti-fraude) ; pénalités uniquement sur
faits vérifiables (désistement après acceptation ferme), délai de grâce, contestation et décision humaine ; refus jamais pénalisés."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from flash import services
from flash.models import DispatchConfig, MissionOffer
from handy.models import Booking, HandymanProfile, Notification
from trust import penalties, xp
from trust.engine import evaluate_profile
from trust.models import TrustPenalty, XpEntry

pytestmark = pytest.mark.django_db


def as_user(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def win(make_request, pro, **kw):
    req = make_request(**kw)
    offer = MissionOffer.objects.get(request=req, handyman=pro)
    services.accept(offer.pk, pro)
    req.refresh_from_db()
    return req


def test_xp_only_for_really_completed_missions_and_never_mixed_with_the_trust_score(make_pro, make_request):
    pro = make_pro("xp")
    req = win(make_request, pro)
    booking = req.booking
    assert xp.summary(pro.pk)["total"] == 0                       # acceptée, pas terminée : 0 XP
    score_before = HandymanProfile.objects.get(user=pro).trust_score
    booking.transition_to("in_progress", actor=pro)
    booking.transition_to("completed", actor=pro)
    s = xp.summary(pro.pk)
    assert s["total"] == 120 and s["level"] == 1 and s["missions"] == 1   # 100 + bonus Tratra Flash 20
    assert {e["reason"] for e in s["history"]} == {"Mission terminée", "Mission Tratra Flash terminée"}
    assert xp.sync(pro.pk) == 0 and xp.award_for(booking) == 0           # rejeu : aucun doublon
    assert HandymanProfile.objects.get(user=pro).trust_score == score_before   # XP ≠ score de confiance


def test_xp_pair_cap_blocks_farming_with_the_same_client(make_pro, client_user):
    pro = make_pro("ferme")
    for i in range(5):
        b = Booking.objects.create(client=client_user, handyman=pro, status="completed", address="x", city="Abidjan",
                                   booking_date=timezone.now() - timedelta(days=1, hours=i), end_date=timezone.now() - timedelta(hours=20 + i))
        xp.award_for(b)
    points = list(XpEntry.objects.filter(user=pro, reason="mission").order_by("id").values_list("points", flat=True))
    assert points == [100, 100, 100, 0, 0]
    assert "Plafond" in XpEntry.objects.filter(user=pro, points=0).first().detail


def test_refusing_or_ignoring_offers_never_creates_a_penalty(make_pro, make_request, django_capture_on_commit_callbacks):
    DispatchConfig.objects.update_or_create(pk=1, defaults={"wave_size": 1})
    pro = make_pro("libre")
    req = make_request()
    with django_capture_on_commit_callbacks(execute=True):
        services.decline(MissionOffer.objects.get(request=req).pk, pro)
    services.expire_due(now=timezone.now() + timedelta(hours=1))
    assert not TrustPenalty.objects.exists()
    profile = HandymanProfile.objects.get(user=pro)
    evaluate_profile(profile, trigger="test")
    from trust import metrics
    from trust.models import TrustConfig

    assert metrics.commitment(profile, TrustConfig.get_solo())["rate"] is None   # aucun fait : composante non mesurée


def test_withdrawal_after_firm_acceptance_is_a_verifiable_fact_with_grace_and_contest(make_pro, make_request, make_user,
                                                                                   django_capture_on_commit_callbacks):
    DispatchConfig.objects.update_or_create(pk=1, defaults={"withdrawal_grace_minutes": 5, "max_active_requests_per_client": 10})
    pro = make_pro("desiste")
    # 1) annulation dans le délai de grâce (erreur de manipulation) : aucune pénalité
    quick = win(make_request, pro, client=make_user("c1"))
    quick.booking.transition_to("cancelled", actor=pro)
    assert not TrustPenalty.objects.exists()
    # 2) annulation par le CLIENT : jamais imputée au professionnel
    by_client = win(make_request, pro, client=make_user("c2"))
    by_client.booking.transition_to("cancelled", actor=by_client.client)
    assert not TrustPenalty.objects.exists()
    # 3) désistement du pro, une heure après avoir accepté : fait daté, pénalité expliquée et notifiée
    late = win(make_request, pro, client=make_user("c3"))
    late.__class__.objects.filter(pk=late.pk).update(assigned_at=timezone.now() - timedelta(hours=1))
    with django_capture_on_commit_callbacks(execute=True):
        late.booking.transition_to("cancelled", actor=pro)
    p = TrustPenalty.objects.get(user=pro)
    assert p.kind == "withdrawal" and p.booking_id == late.booking_id and p.evidence["cancelled_by"] == pro.pk
    assert Notification.objects.filter(user=pro, notification_type="trust_penalty").exists()
    passport = as_user(pro).get("/handy/me/trust/").json()
    commitment = next(c for c in passport["score"]["components"] if c["key"] == "commitment")
    assert "1 désistement" in commitment["detail"]
    assert passport["penalties"][0]["can_contest"] is True and passport["xp"]["total"] == 0
    # contestation puis décision humaine motivée
    r = as_user(pro).post(f"/handy/me/trust/penalties/{p.pk}/contest/", {"reason": "Le client m'a demandé d'annuler par téléphone."},
                          format="json")
    assert r.status_code == 200 and r.json()["status"] == "contested"
    staff = make_user("equipe", is_staff=True)
    with django_capture_on_commit_callbacks(execute=True):
        penalties.decide(p.pk, staff, uphold_contest=True, note="Échange avec le client confirmé par l'équipe.")
    p.refresh_from_db()
    assert p.status == "cancelled" and p.decided_by == staff
    assert penalties.counted(pro.pk).count() == 0


def test_staff_penalty_requires_a_precise_mission_and_an_explanation(make_pro, make_user, client_user):
    pro = make_pro("absent")
    staff = make_user("equipe2", is_staff=True)
    b = Booking.objects.create(client=client_user, handyman=pro, status="confirmed", address="x", city="Abidjan", booking_date=timezone.now())
    with pytest.raises(penalties.PenaltyError):
        penalties.record_by_staff(user=pro, kind="no_show", booking=None, explanation="x" * 30, evidence={}, staff=staff)
    with pytest.raises(penalties.PenaltyError):
        penalties.record_by_staff(user=pro, kind="no_show", booking=b, explanation="court", evidence={}, staff=staff)
    p = penalties.record_by_staff(user=pro, kind="no_show", booking=b, explanation="Absent au rendez-vous, constaté par appel au client.",
                                  evidence={"call": "2026-10-21 10:12"}, staff=staff)
    assert p.status == "active" and p.created_by == staff
    with pytest.raises(penalties.PenaltyError) as e:
        penalties.record_by_staff(user=pro, kind="no_show", booking=b, explanation="Absent au rendez-vous, constaté une 2e fois.",
                                  evidence={}, staff=staff)
    assert e.value.code == "duplicate"
