"""Copie calculée de l'éligibilité (`HandymanProfile.published`) : la lecture rapide `publishable()` suit CHAQUE changement de la règle
dans la même transaction (KYC, spécialités, offres, métier, compte, validation), un retrait d'éligibilité est immédiat, et toute
divergence (écriture en masse sans signal) est détectée puis corrigée par la réconciliation."""
import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError

from handy import eligibility
from handy.eligibility import publishable, publishable_rule
from handy.models import HandymanDocument, HandymanProfile, Service, ServiceCategory, User
from handy.testing import make_eligible

pytestmark = pytest.mark.django_db


def _pro(name, **profile):
    user = User.objects.create_user(username=name, password="pass1234", user_type="handyman")
    p = make_eligible(user.handyman_profile, category=ServiceCategory.objects.get_or_create(slug="plomberie-pub", defaults={"name": "Plomberie"})[0])
    for k, v in profile.items():
        setattr(p, k, v)
    p.location = Point(-4.0, 5.36, srid=4326)
    p.save()
    return user


def _published(user) -> bool:
    flag = HandymanProfile.objects.get(user=user).published
    fast = publishable().filter(user=user).exists()
    rule = publishable_rule().filter(user=user).exists()
    assert flag == rule, "la copie calculée diverge de la règle"
    return fast


def test_an_eligible_professional_is_published_and_kyc_rejection_unpublishes_at_once():
    user = _pro("kyc")
    assert _published(user)
    doc = HandymanDocument.objects.get(handyman=user.handyman_profile)
    doc.status = "rejected"
    doc.save()
    assert not _published(user)
    doc.status = "approved"
    doc.save()
    assert _published(user)
    doc.delete()
    assert not _published(user)


def test_suspension_and_unapproval_are_immediate_even_without_any_recalculation():
    user = _pro("suspendu")
    User.objects.filter(pk=user.pk).update(is_active=False)                      # écriture en masse : aucun signal
    assert not publishable().filter(user=user).exists()                          # garde directe sur le compte
    User.objects.filter(pk=user.pk).update(is_active=True)
    HandymanProfile.objects.filter(user=user).update(is_approved=False)          # idem pour la validation de l'équipe
    assert not publishable().filter(user=user).exists()
    user.refresh_from_db()
    user.is_active = False
    user.save()                                                                  # chemin normal : la copie suit aussi
    assert HandymanProfile.objects.get(user=user).published is False


def test_skills_offers_and_trade_minimum_follow_the_rule():
    user = _pro("metier")
    profile = user.handyman_profile
    profile.skills.clear()
    assert not _published(user)
    trade = ServiceCategory.objects.create(name="Électricité", slug="elec-pub")
    profile.skills.add(trade)
    assert _published(user)
    # Un métier qui durcit son expérience minimale retire ceux qui ne l'atteignent pas…
    trade.min_experience_years = 30
    trade.save()
    assert not _published(user)
    trade.min_experience_years = 0
    trade.save()
    assert _published(user)
    # … y compris par une offre active dans une prestation de ce métier.
    prestation = ServiceCategory.objects.create(name="Câblage", slug="cablage-pub", parent=ServiceCategory.objects.create(
        name="Métier exigeant", slug="exigeant-pub", min_experience_years=40))
    offer = Service.objects.create(handyman=user, category=prestation, title="Câblage", description="d", price_type="fixed", price=1000)
    assert not _published(user)
    offer.is_active = False
    offer.save()
    assert _published(user)
    offer.delete()
    assert _published(user)


def test_removing_a_skill_from_the_trade_side_and_deleting_a_trade_unpublish():
    user = _pro("inverse")
    profile = user.handyman_profile
    trade = profile.skills.get()
    trade.handymen.remove(profile)                                               # côté métier (relation inverse)
    assert not _published(user)
    other = ServiceCategory.objects.create(name="Peinture", slug="peinture-pub")
    profile.skills.add(other)
    assert _published(user)
    other.delete()                                                               # suppression du métier : liens supprimés en cascade
    assert not _published(user)


def test_profile_fields_of_the_rule_follow_but_unrelated_saves_do_not_recalculate(monkeypatch):
    user = _pro("profil")
    profile = HandymanProfile.objects.get(user=user)
    profile.photo = ""
    profile.save()
    assert not _published(user)
    profile.photo = "profile_pics/x.jpg"
    profile.save()
    assert _published(user)
    calls = []
    monkeypatch.setattr(eligibility, "refresh_published", lambda *a, **k: calls.append(a) or 0)
    profile.online = True
    profile.save(update_fields=["online"])                                       # disponibilité : hors règle, aucun recalcul
    user.save(update_fields=["last_login"])                                      # chaque connexion : aucun recalcul
    assert calls == []


def test_reconciliation_detects_and_fixes_a_bulk_write_that_skipped_the_signals():
    user = _pro("derive")
    HandymanDocument.objects.filter(handyman=user.handyman_profile).update(status="pending")   # écriture en masse sans signal
    assert HandymanProfile.objects.get(user=user).published is True
    assert eligibility.published_drift() == 1
    with pytest.raises(CommandError):
        call_command("eligibility_sync", "--check")
    from handy.tasks import reconcile_published

    assert reconcile_published() == {"changed": 1}
    assert not _published(user) and eligibility.published_drift() == 0
    call_command("eligibility_sync", "--check")


def test_admin_bulk_approval_recalculates_the_published_copy(rf, monkeypatch):
    from django.contrib.admin.sites import AdminSite

    from handy.admin import HandymanProfileAdmin

    user = _pro("admin", is_approved=False)
    assert not _published(user)
    admin = HandymanProfileAdmin(HandymanProfile, AdminSite())
    monkeypatch.setattr(admin, "message_user", lambda *a, **k: None)
    admin.approve_profiles(rf.post("/"), HandymanProfile.objects.filter(user=user))
    assert _published(user)
