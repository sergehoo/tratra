"""Suppression sécurisée : données fictives supprimées avec leurs dépendances, argent réel jamais effacé, droits superutilisateur, commande de nettoyage."""
import json
import os
import time
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.utils import timezone

from handy import safe_delete as sd
from handy.models import Booking, Device, OTPCode, Payment, Payout, User
from trust.models import AuditEvent

pytestmark = pytest.mark.django_db
_n = 0


def demo_user(prefix="d"):
    """Comptes tels que les crée le générateur de données : jamais connectés, conditions non acceptées, aucune session. Nom volontairement banal."""
    global _n
    _n += 1
    return User.objects.create_user(username=f"{prefix}{_n}", email=f"{prefix}{_n}@demo.test", password="x", first_name="Alice", last_name="Martin")


def real_user(prefix="r"):
    u = demo_user(prefix)
    User.objects.filter(pk=u.pk).update(last_login=timezone.now(), terms_accepted_at=timezone.now())
    u.refresh_from_db()
    return u


def booking(client, pro, *, status="completed"):
    return Booking.objects.create(client=client, handyman=pro, address="x", city="x", booking_date=timezone.now(), status=status)


def payment(b, *, verified=False):
    p = Payment.objects.create(booking=b, amount=Decimal("2500"), platform_fee=Decimal("250"), method="om", status="completed", transaction_id=f"tx{b.pk}{verified}")
    if verified:
        Payment.objects.filter(pk=p.pk).update(provider_verified_at=timezone.now(), provider_session={"id": "s1"})
    return p


@pytest.fixture
def root():
    c = Client()
    c.force_login(User.objects.create_superuser("sd_root", "sd_root@x.test", "pass1234"))
    return c


def post_user_action(client, ids, **extra):
    data = {"action": "safe_delete_selected", "_selected_action": ids, **extra}
    return client.post("/admin/handy/user/", data)


# ------------------------------------------------------------------ reconnaissance des données fictives (jamais sur le nom)
def test_demo_signals_are_structural_never_the_name():
    seeded = demo_user()
    assert sd.looks_demo(seeded)
    for field, value in (("last_login", timezone.now()), ("terms_accepted_at", timezone.now()), ("is_staff", True)):
        u = demo_user()
        User.objects.filter(pk=u.pk).update(**{field: value})
        u.refresh_from_db()
        assert not sd.looks_demo(u), field
    u = demo_user()
    OTPCode.objects.create(user=u, code="123456", expires_at=timezone.now())
    assert not sd.looks_demo(u)
    u = demo_user()
    Device.objects.create(user=u, device_token="tok-" + str(u.pk), device_type="android")
    assert not sd.looks_demo(u)
    assert sd.looks_demo(User.objects.create_user("Demo Client", "demo.client@x.test", "x", first_name="Demo", last_name="Client"))   # un nom « démo » ne dit rien
    assert not sd.looks_demo(User.objects.create_user("jean.kouame", "jean.kouame@x.test", "x", is_staff=True))                        # un nom « normal » non plus


# ------------------------------------------------------------------ administration : suppression des données fictives avec leurs dépendances
def test_aperçu_puis_confirmation_supprime_les_donnees_fictives_et_leurs_paiements(root):
    client, pro = demo_user(), demo_user()
    b = booking(client, pro)
    p = payment(b)
    preview = post_user_action(root, [client.pk, pro.pk])
    assert preview.status_code == 200 and "Suppression définitive" in preview.content.decode()
    assert User.objects.filter(pk=client.pk).exists() and Payment.objects.filter(pk=p.pk).exists()      # l'aperçu ne modifie rien
    no_word = post_user_action(root, [client.pk, pro.pk], safe_delete_apply="1", confirm_word="oui")
    assert no_word.status_code == 200 and User.objects.filter(pk=client.pk).exists()                   # mauvais mot : rien
    done = post_user_action(root, [client.pk, pro.pk], safe_delete_apply="1", confirm_word="SUPPRIMER")
    assert done.status_code == 302
    assert not User.objects.filter(pk__in=[client.pk, pro.pk]).exists() and not Booking.objects.filter(pk=b.pk).exists() and not Payment.objects.filter(pk=p.pk).exists()
    event = AuditEvent.objects.filter(action="admin.safe_delete").latest("id")
    assert event.data["deleted"] == 2 and set(event.data) <= {"ids", "deleted", "anonymized", "refused", "objects"}   # aucune donnée personnelle


def test_un_paiement_reel_n_est_jamais_efface_le_compte_est_anonymise(root):
    client, pro = demo_user(), demo_user()
    b = booking(client, pro, status="completed")
    p = payment(b, verified=True)
    resp = post_user_action(root, [client.pk], safe_delete_apply="1", confirm_word="SUPPRIMER", confirm_fictive="1")   # même avec la case cochée
    assert resp.status_code == 302
    client.refresh_from_db()
    assert User.objects.filter(pk=client.pk).exists() and client.deleted_at is not None and not client.is_active and client.first_name == ""
    assert Payment.objects.filter(pk=p.pk).exists() and Booking.objects.filter(pk=b.pk).exists()          # écritures financières conservées


def test_un_compte_reel_sans_argent_est_anonymise_sauf_case_donnees_fictives(root):
    u = real_user()
    post_user_action(root, [u.pk], safe_delete_apply="1", confirm_word="SUPPRIMER")
    u.refresh_from_db()
    assert u.deleted_at is not None and User.objects.filter(pk=u.pk).exists()                          # anonymisé, pas supprimé
    v = real_user()
    post_user_action(root, [v.pk], safe_delete_apply="1", confirm_word="SUPPRIMER", confirm_fictive="1")
    assert not User.objects.filter(pk=v.pk).exists()                                                     # supprimé après confirmation explicite


def test_un_compte_fictif_lie_a_un_compte_reel_n_efface_pas_les_donnees_du_reel(root):
    demo, real = demo_user(), real_user()
    b = booking(real, demo, status="completed")
    post_user_action(root, [demo.pk], safe_delete_apply="1", confirm_word="SUPPRIMER")
    demo.refresh_from_db()
    assert Booking.objects.filter(pk=b.pk).exists() and demo.deleted_at is not None                     # anonymisé : la réservation du compte réel reste


def test_administrateurs_et_son_propre_compte_ne_sont_jamais_supprimes(root):
    other_admin = User.objects.create_superuser("sd_other", "sd_o@x.test", "pass1234")
    me = User.objects.get(username="sd_root")
    resp = post_user_action(root, [other_admin.pk, me.pk], safe_delete_apply="1", confirm_word="SUPPRIMER", confirm_fictive="1")
    assert User.objects.filter(pk__in=[other_admin.pk, me.pk]).count() == 2 and resp.status_code == 302       # 0 supprimé : rien n'a bougé
    preview = post_user_action(root, [other_admin.pk, me.pk], confirm_fictive="1")
    assert "Aucun élément ne peut être supprimé" in preview.content.decode()                                 # aperçu : tout est conservé


def test_seul_un_superutilisateur_dispose_de_la_suppression():
    staff = User.objects.create_user("sd_staff", "sd_staff@x.test", "x", is_staff=True)
    c = Client()
    c.force_login(staff)
    target = demo_user()
    r = post_user_action(c, [target.pk], safe_delete_apply="1", confirm_word="SUPPRIMER")
    assert User.objects.filter(pk=target.pk).exists() and r.status_code in (200, 302, 403)
    ma = admin.site._registry[User]
    req = c.get("/admin/").wsgi_request
    assert not ma.has_delete_permission(req) and "safe_delete_selected" not in ma.get_actions(req)
    assert c.get(f"/admin/handy/user/{target.pk}/delete/").status_code in (302, 403)


def test_le_bouton_supprimer_d_une_fiche_suit_le_meme_parcours(root):
    u = demo_user()
    page = root.get(f"/admin/handy/user/{u.pk}/delete/")
    assert page.status_code == 200 and "Suppression sécurisée" in page.content.decode() and User.objects.filter(pk=u.pk).exists()
    done = root.post(f"/admin/handy/user/{u.pk}/delete/", {"safe_delete_apply": "1", "confirm_word": "SUPPRIMER"})
    assert done.status_code == 302 and not User.objects.filter(pk=u.pk).exists()


def test_taille_maximale_d_une_operation(root):
    users = [demo_user() for _ in range(sd.MAX_BATCH + 1)]
    r = post_user_action(root, [u.pk for u in users], safe_delete_apply="1", confirm_word="SUPPRIMER")
    assert r.status_code == 302 and User.objects.filter(pk__in=[u.pk for u in users]).count() == len(users)


# ------------------------------------------------------------------ réservations
def test_reservation_fictive_supprimee_reservation_a_paiement_reel_refusee(root):
    c1, p1, c2, p2 = demo_user(), demo_user(), demo_user(), demo_user()
    fake, real = booking(c1, p1), booking(c2, p2)
    pay_fake, pay_real = payment(fake), payment(real, verified=True)
    resp = root.post("/admin/handy/booking/", {"action": "safe_delete_selected", "_selected_action": [fake.pk, real.pk],
                                               "safe_delete_apply": "1", "confirm_word": "SUPPRIMER"})
    assert resp.status_code == 302
    assert not Booking.objects.filter(pk=fake.pk).exists() and not Payment.objects.filter(pk=pay_fake.pk).exists()
    assert Booking.objects.filter(pk=real.pk).exists() and Payment.objects.filter(pk=pay_real.pk).exists()


def test_paiement_reel_atteint_par_la_chaine_de_dependances_bloque_tout():
    """Le garde est appelé sur chaque objet protégé : un retrait envoyé est refusé même s'il est atteint indirectement."""
    pro = demo_user()
    Payout.objects.create(handyman=pro, amount=Decimal("1000"), status="sent")
    outcomes = sd.plan_users([pro], confirm_fictive=True)
    assert outcomes[0].action in ("anonymize", "refuse")
    with pytest.raises(sd.RealMoneyError):
        sd.cascade_delete(pro, __import__("collections").Counter())
    assert User.objects.filter(pk=pro.pk).exists() and Payout.objects.filter(handyman=pro).exists()


# ------------------------------------------------------------------ commande cleanup_demo_data
def _run(*args):
    out = StringIO()
    call_command("cleanup_demo_data", *args, stdout=out)
    return out.getvalue()


def _backup(tmp_path, age_s=0):
    f = tmp_path / "dump.sql"
    f.write_text("-- dump")
    if age_s:
        old = time.time() - age_s
        os.utime(f, (old, old))
    return str(f)


def test_commande_simulation_ne_modifie_rien_et_ecrit_la_selection(tmp_path):
    client, pro = demo_user(), demo_user()
    keep = real_user()
    b = booking(client, pro)
    payment(b)
    sel = tmp_path / "sel.json"
    out = _run("--dry-run", "--selection-out", str(sel))
    assert "SIMULATION" in out and "Aucune donnée n'a été modifiée" in out
    assert User.objects.filter(pk__in=[client.pk, pro.pk, keep.pk]).count() == 3 and Booking.objects.filter(pk=b.pk).exists()
    ids = json.loads(sel.read_text())["user_ids"]
    assert client.pk in ids and pro.pk in ids and keep.pk not in ids


def test_commande_execution_exige_confirmation_sauvegarde_et_selection(tmp_path):
    u = demo_user()
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps({"user_ids": [u.pk]}))
    with pytest.raises(CommandError, match="Confirmation"):
        _run("--execute", "--selection", str(sel), "--backup", _backup(tmp_path))
    with pytest.raises(CommandError, match="--selection"):
        _run("--execute", "--confirm", "SUPPRIMER-DONNEES-DEMO", "--backup", _backup(tmp_path))
    with pytest.raises(CommandError, match="--backup"):
        _run("--execute", "--selection", str(sel), "--confirm", "SUPPRIMER-DONNEES-DEMO")
    with pytest.raises(CommandError, match="48 h"):
        _run("--execute", "--selection", str(sel), "--confirm", "SUPPRIMER-DONNEES-DEMO", "--backup", _backup(tmp_path, age_s=72 * 3600))
    assert User.objects.filter(pk=u.pk).exists()


def test_commande_execution_supprime_la_selection_relue_et_s_arrete_si_un_compte_a_change(tmp_path):
    a, b_ = demo_user(), demo_user()
    bk = booking(a, b_)
    pay = payment(bk)
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps({"user_ids": [a.pk, b_.pk]}))
    # un compte de la sélection s'est connecté depuis : tout est refusé, rien n'est supprimé
    User.objects.filter(pk=b_.pk).update(last_login=timezone.now())
    with pytest.raises(CommandError, match="ne ressemblent plus"):
        _run("--execute", "--selection", str(sel), "--confirm", "SUPPRIMER-DONNEES-DEMO", "--backup", _backup(tmp_path))
    assert User.objects.filter(pk__in=[a.pk, b_.pk]).count() == 2 and Payment.objects.filter(pk=pay.pk).exists()
    User.objects.filter(pk=b_.pk).update(last_login=None)
    out = _run("--execute", "--selection", str(sel), "--confirm", "SUPPRIMER-DONNEES-DEMO", "--backup", _backup(tmp_path))
    assert "2/2" in out
    assert not User.objects.filter(pk__in=[a.pk, b_.pk]).exists() and not Booking.objects.filter(pk=bk.pk).exists() and not Payment.objects.filter(pk=pay.pk).exists()


def test_commande_ne_propose_jamais_un_compte_avec_argent_reel():
    client, pro = demo_user(), demo_user()
    payment(booking(client, pro), verified=True)
    ids = set(sd.demo_candidates().values_list("pk", flat=True))
    assert client.pk not in ids and pro.pk not in ids
