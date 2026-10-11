"""Console du Back-Office : filtres, tri et recherche des listes de gestion, coordonnées complètes réservées au Super Admin,
traçabilité des consultations de données personnelles. Chaque règle de droit reste appliquée CÔTÉ SERVEUR."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from backoffice.test_money import make_org
from backoffice.test_ops import BO, api, audited, make_booking, pay, person, staff
from business.models import ConsolidatedInvoice
from handy.models import Dispute, Invoice, Payout, Review, Service, ServiceCategory
from handy.test_eligibility import artisan, service

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()  # les traces « une par fenêtre » reposent sur le cache : chaque test repart de zéro
    yield
    cache.clear()


# ═══ Coordonnées complètes : Super Admin seulement, avec trace ═══════════════════════════════════════════════════════

def _contact_user():
    return person("ct_awa", first_name="Awa", last_name="Kone", phone="+2250701234567")


def test_user_lists_mask_contacts_for_every_role_except_the_super_admin():
    _contact_user()
    masked = api(staff("ct_ops", "ops")).get(f"{BO}/users/?q=awa").json()["results"][0]
    assert masked["phone"] == "+22507••••4567" and masked["email"] == "c•••@x.test" and "+2250701234567" not in str(masked)
    full = api(staff("ct_root", superuser=True)).get(f"{BO}/users/?q=awa").json()["results"][0]
    assert full["phone"] == "+2250701234567" and full["email"] == "ct_awa@x.test"
    support = api(staff("ct_support", "support")).get(f"{BO}/users/?q=awa").json()["results"][0]
    assert "••••" in support["phone"]


def test_a_super_admin_listing_unmasked_contacts_is_journaled_once_per_window_and_other_roles_leave_no_such_trace():
    _contact_user()
    ops, root = staff("ct_ops2", "ops"), staff("ct_root2", superuser=True)
    api(ops).get(f"{BO}/users/")
    assert not audited("contacts.unmasked_view").exists()
    client = api(root)
    for _ in range(3):
        client.get(f"{BO}/users/")
    events = audited("contacts.unmasked_view", actor=root)
    assert events.count() == 1 and events.get().data["view"] == "bo-users"        # une trace par administrateur, module et fenêtre de 5 minutes
    assert "+2250701234567" not in str(events.get().data)                          # la trace ne recopie aucune coordonnée
    api(staff("ct_root3", superuser=True)).get(f"{BO}/users/")
    assert audited("contacts.unmasked_view").count() == 2                          # un autre administrateur = une autre trace


def test_a_user_sheet_shows_full_contacts_to_authorised_roles_and_each_consultation_is_traced_once_per_window():
    user = _contact_user()
    ops = staff("ct_ops3", "ops")
    detail = api(ops).get(f"{BO}/users/{user.id}/")
    assert detail.status_code == 200 and detail.json()["phone_full"] == "+2250701234567"
    api(ops).get(f"{BO}/users/{user.id}/")
    assert audited("user.contact_viewed", target_id=user.id, actor=ops).count() == 1
    api(staff("ct_support2", "support")).get(f"{BO}/users/{user.id}/")
    assert audited("user.contact_viewed", target_id=user.id).count() == 2
    assert api(staff("ct_finance", "finance")).get(f"{BO}/users/{user.id}/").status_code == 403    # pas de droit « users.view » : ni fiche ni trace
    assert audited("user.contact_viewed", target_id=user.id).count() == 2


def test_booking_sheet_phones_are_masked_except_for_the_super_admin():
    client = person("ct_cl", phone="+2250709990001")
    art = artisan("ct_art")
    art.phone = "+2250709990002"
    art.save(update_fields=["phone"])
    booking = make_booking(client, art, "confirmed", svc=service(art, "Plomberie"))
    masked = api(staff("ct_ops4", "ops")).get(f"{BO}/bookings/{booking.id}/").json()
    assert "••••" in masked["client_phone"] and "••••" in masked["artisan_phone"]
    full = api(staff("ct_root4", superuser=True)).get(f"{BO}/bookings/{booking.id}/").json()
    assert full["client_phone"] == "+2250709990001" and full["artisan_phone"] == "+2250709990002"


# ═══ Utilisateurs ════════════════════════════════════════════════════════════════════════════════════════════════════

def test_users_list_exposes_the_profile_id_filters_by_city_and_sorts_by_name():
    art = artisan("ls_art")
    art.first_name, art.city = "Zoe", "Bouaké"
    art.save(update_fields=["first_name", "city"])
    person("ls_cl", first_name="Aïcha", last_name="Traore").city = "Abidjan"
    User = type(art)
    User.objects.filter(username="ls_cl").update(city="Abidjan")
    ops = api(staff("ls_ops", "ops"))
    rows = {r["name"]: r for r in ops.get(f"{BO}/users/").json()["results"]}
    assert rows["Zoe"]["profile_id"] == art.handyman_profile.pk and rows["Aïcha T."]["profile_id"] is None
    assert [r["name"] for r in ops.get(f"{BO}/users/?city=bouaké").json()["results"]] == ["Zoe"]
    ordered = [r["name"] for r in ops.get(f"{BO}/users/?ordering=name").json()["results"] if r["name"] in ("Zoe", "Aïcha T.")]
    assert ordered == ["Aïcha T.", "Zoe"]
    assert ops.get(f"{BO}/users/?ordering=password").status_code == 200       # clé inconnue : tri par défaut, jamais d'erreur ni de fuite


# ═══ Réservations, litiges, avis ════════════════════════════════════════════════════════════════════════════════════

def test_bookings_filter_by_user_category_and_payment_status():
    a1, a2 = artisan("bk_a1"), artisan("bk_a2")
    c1, c2 = person("bk_c1"), person("bk_c2")
    s1, s2 = service(a1, "Peinture"), service(a2, "Électricité")
    b1 = make_booking(c1, a1, "completed", svc=s1)
    b2 = make_booking(c2, a2, "pending", svc=s2)
    pay(b1, status="released")
    ops = api(staff("bk_ops", "ops"))
    ids = lambda qs: sorted(r["id"] for r in ops.get(f"{BO}/bookings/?{qs}").json()["results"])      # noqa: E731
    assert ids(f"user={c1.id}") == [b1.id] and ids(f"user={a1.id}") == [b1.id]            # client OU artisan
    assert ids(f"user={c2.id}") == [b2.id] and ids("user=999999") == []
    paint, elec = ServiceCategory.objects.create(name="Peinture QA", slug="peinture-qa"), ServiceCategory.objects.create(name="Électricité QA", slug="electricite-qa")
    Service.objects.filter(pk=s1.pk).update(category=paint)
    Service.objects.filter(pk=s2.pk).update(category=elec)
    assert ids(f"category={elec.id}") == [b2.id] and ids(f"category={paint.id}") == [b1.id] and ids("category=abc") == sorted([b1.id, b2.id])
    assert ids("payment_status=released") == [b1.id] and ids("payment_status=inconnu") == sorted([b1.id, b2.id])   # valeur invalide ignorée


def test_disputes_filter_by_text_user_period_and_sort():
    a, c = artisan("ds_art"), person("ds_cl", first_name="Fatou")
    booking = make_booking(c, a, "completed", svc=service(a, "Serrurerie"))
    old = Dispute.objects.create(booking=booking, reporter=c, reason="Travail non conforme au devis")
    Dispute.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=10))
    recent = Dispute.objects.create(booking=booking, reporter=c, reason="Retard de deux heures", status="under_review")
    ops = api(staff("ds_ops", "ops"))
    ids = lambda qs: [r["id"] for r in ops.get(f"{BO}/disputes/?{qs}").json()["results"]]       # noqa: E731
    assert ids("q=retard") == [recent.id] and ids("q=fatou") == [recent.id, old.id]
    assert ids(f"q={booking.id}") == [recent.id, old.id] and ids(f"user={c.id}") == [recent.id, old.id] and ids(f"user={a.id}") == [recent.id, old.id]
    assert ids("user=999999") == []
    assert ids(f"from={timezone.localdate() - timedelta(days=2)}") == [recent.id]
    assert ids("ordering=created_at") == [old.id, recent.id] and ids("status=under_review") == [recent.id]


def test_reviews_keep_the_moderation_queue_by_default_and_accept_period_and_rating_sort():
    a = artisan("rv_art")
    first = make_booking(person("rv_c1"), a, "completed", svc=service(a, "Vitrerie"))
    second = make_booking(person("rv_c2"), a, "completed", svc=service(a, "Carrelage"))
    low = Review.objects.create(booking=first, rating=2, comment="Moyen")
    high = Review.objects.create(booking=second, rating=5, comment="Parfait")
    Review.objects.filter(pk=low.pk).update(created_at=timezone.now() - timedelta(days=20))
    ops = api(staff("rv_ops", "ops"))
    ids = lambda qs="": [r["id"] for r in ops.get(f"{BO}/reviews/?{qs}").json()["results"]]       # noqa: E731
    assert ids("ordering=rating") == [low.id, high.id] and ids("ordering=-rating") == [high.id, low.id]
    assert ids(f"from={timezone.localdate() - timedelta(days=3)}") == [high.id]
    assert set(ids()) == {low.id, high.id}


# ═══ Finances ════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_payments_search_by_name_filter_by_user_and_sort():
    a1, a2 = artisan("py_a1"), artisan("py_a2")
    c1, c2 = person("py_c1", first_name="Awa"), person("py_c2", first_name="Moussa")
    p1 = pay(make_booking(c1, a1, svc=service(a1, "Jardinage")), "released", amount="20000")
    p2 = pay(make_booking(c2, a2, svc=service(a2, "Maçonnerie")), "held", amount="5000")
    fin = api(staff("py_fin", "finance"))
    ids = lambda qs: [r["id"] for r in fin.get(f"{BO}/finance/payments/?{qs}").json()["results"]]       # noqa: E731
    assert ids("q=awa") == [p1.id] and ids("q=moussa") == [p2.id]            # avant : un texte non numérique était ignoré (liste entière)
    assert ids(f"q={p2.id}") == [p2.id] and ids("q=zzzz") == []
    assert ids(f"user={c1.id}") == [p1.id] and ids(f"user={a2.id}") == [p2.id]
    assert ids("ordering=amount") == [p2.id, p1.id] and ids("ordering=-amount") == [p1.id, p2.id]
    assert "SECRET-REF" not in str(fin.get(f"{BO}/finance/payments/?q=awa").json())


def test_payouts_and_invoices_gain_text_period_and_sort_filters():
    a1, a2 = artisan("po_a1"), artisan("po_a2")
    a1.first_name, a2.first_name = "Ibrahim", "Salif"
    a1.save(update_fields=["first_name"])
    a2.save(update_fields=["first_name"])
    p1 = Payout.objects.create(handyman=a1, amount=Decimal("5000"), status="pending")
    p2 = Payout.objects.create(handyman=a2, amount=Decimal("9000"), status="pending")
    Payout.objects.filter(pk=p1.pk).update(requested_at=timezone.now() - timedelta(days=30))
    fin = api(staff("po_fin", "finance"))
    ids = lambda qs: [r["id"] for r in fin.get(f"{BO}/finance/payouts/?{qs}").json()["results"]]       # noqa: E731
    assert ids("q=ibrahim") == [p1.id] and ids(f"q={p2.id}") == [p2.id]
    assert ids(f"from={timezone.localdate() - timedelta(days=7)}") == [p2.id]
    assert ids("ordering=amount") == [p1.id, p2.id] and ids("status=sent") == []

    client = person("iv_cl", first_name="Kader")
    booking = make_booking(client, a1, svc=service(a1, "Peinture murale"))
    Invoice.objects.create(booking=booking, number="INV-2026-001", amount=Decimal("1000"), fee=Decimal("100"), total=Decimal("1100"))
    rows = lambda qs: fin.get(f"{BO}/finance/invoices/?{qs}").json()["results"]       # noqa: E731
    assert len(rows("q=inv-2026")) == 1 and len(rows("q=kader")) == 1 and rows("q=introuvable") == []
    assert len(rows(f"q={booking.id}")) == 1 and rows(f"from={timezone.localdate() + timedelta(days=2)}") == []


def test_business_invoices_filter_by_status_text_and_period():
    _, org, _ = make_org("bi_owner", "Résidence Plateau")
    done = ConsolidatedInvoice.objects.create(organization=org, number="CI-2026-01", period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), total=Decimal("40000"))
    void = ConsolidatedInvoice.objects.create(organization=org, number="CI-2026-02", period_start=date(2026, 2, 1), period_end=date(2026, 2, 28), total=Decimal("9000"), status="void")
    fin = api(staff("bi_ops", "ops"))
    ids = lambda qs: sorted(r["id"] for r in fin.get(f"{BO}/business/invoices/?{qs}").json()["results"])       # noqa: E731
    assert ids("status=void") == [void.id] and ids("status=issued") == [done.id]
    assert ids("q=plateau") == sorted([done.id, void.id]) and ids("q=ci-2026-02") == [void.id] and ids("q=zzz") == []
    assert ids("ordering=total") == sorted([done.id, void.id]) and ids(f"to={timezone.localdate() - timedelta(days=1)}") == []
