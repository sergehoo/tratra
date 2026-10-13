"""Messagerie administrateur : droits, envoi individuel à un ou plusieurs membres, isolation des destinataires, consentement, résultats,
rejeu sans doublon, réponses des membres et audit."""
from unittest import mock

import pytest
from django.contrib.auth import get_user_model

from backoffice import staff_messaging
from backoffice.models import StaffMessageBatch, StaffMessageDelivery
from backoffice.test_people import BO, api, audited, person, staff
from handy.models import Conversation, MarketingConsent, Message, Notification
from handy.test_eligibility import artisan

User = get_user_model()
pytestmark = pytest.mark.django_db
URL = f"{BO}/messages"


def send(admin, ids=None, filters=None, body="Bonjour de la part de Tratra", purpose="service"):
    data = {"body": body, "purpose": purpose}
    if ids is not None:
        data["user_ids"] = ids
    if filters is not None:
        data["filters"] = filters
    return api(admin).post(f"{URL}/send/", data, format="json")


def member_api(user):
    return api(user)


# ----------------------------------------------------------------------------------------------------------------- droits

def test_only_authorised_roles_can_use_staff_messaging():
    u = person("sm_target")
    assert api().post(f"{URL}/send/", {"body": "x", "user_ids": [u.id]}, format="json").status_code in (401, 403)
    for role in ("analyst", "finance"):
        assert send(staff(f"sm_{role}", role), [u.id]).status_code == 403
        assert api(staff(f"sm_{role}2", role)).get(f"{URL}/threads/").status_code == 403
    assert api(person("sm_member")).post(f"{URL}/send/", {"body": "x", "user_ids": [u.id]}, format="json").status_code in (401, 403)
    assert send(staff("sm_support", "support"), [u.id]).status_code == 201


def test_bulk_sends_need_the_bulk_permission_and_direct_ones_are_capped_at_twenty():
    support, ops = staff("sm_sup", "support"), staff("sm_ops", "ops")
    users = [person(f"sm_b{i}") for i in range(22)]
    ids = [u.id for u in users]
    r = send(support, ids)                                     # 22 destinataires : au-delà du plafond de l'envoi direct
    assert r.status_code == 403
    assert send(support, filters={"type": "client"}).status_code == 403
    assert send(ops, ids).status_code == 201
    assert api(support).post(f"{URL}/preview/", {"body": "x", "user_ids": ids}, format="json").status_code == 403


# --------------------------------------------------------------------------------------- envoi individuel et isolation

def test_one_message_is_delivered_to_each_recipient_in_their_own_conversation_without_exposing_the_others():
    admin = staff("sm_admin", "support")
    a, b, c = person("sm_a", first_name="Awa"), person("sm_b", first_name="Koffi"), person("sm_c", first_name="Mariam")
    r = send(admin, [a.id, b.id, c.id], body="Maintenance ce soir à 22h.")
    assert r.status_code == 201
    out = r.json()
    assert out["recipient_count"] == 3 and out["results"]["sent"] == 3 and out["status"] == "done"
    assert Conversation.objects.filter(kind="support").count() == 3                                       # un fil par membre, jamais un groupe
    for user in (a, b, c):
        conv = Conversation.objects.get(kind="support", participants=user)
        assert list(conv.participants.values_list("pk", flat=True)) == [user.pk]
        listing = member_api(user).get("/handy/me/conversations/").json()["results"]
        assert len(listing) == 1 and listing[0]["kind"] == "support" and listing[0]["counterpart"] == "Équipe Tratra" and listing[0]["unread"] == 1
        thread = member_api(user).get(f"/handy/me/conversations/{conv.pk}/messages/").json()
        m = thread["results"][0]
        assert m["content"] == "Maintenance ce soir à 22h." and m["sender"] == "Équipe Tratra" and m["via_staff"] is True and m["mine"] is False
        raw = str(thread)
        assert "Sm_admin" not in raw and "Admin" not in raw and "sm_admin" not in raw          # l'identité de l'agent n'est jamais exposée
        assert not any(other.first_name in raw for other in (a, b, c) if other != user)         # aucun autre destinataire
        n = Notification.objects.get(user=user, notification_type="message_received")
        assert n.title == "Équipe Tratra" and n.data == {"kind": "conversation", "id": conv.pk}
    conv_a = Conversation.objects.get(kind="support", participants=a)
    assert member_api(b).get(f"/handy/me/conversations/{conv_a.pk}/messages/").status_code == 404      # isolation stricte
    assert audited("message.batch_created").count() == 1
    ev = audited("message.batch_created").first()
    assert ev.actor_id == admin.id and ev.data["recipients"] == 3 and "Maintenance" not in str(ev.data)  # le texte n'est pas copié dans l'audit


def test_second_message_reuses_the_same_support_thread():
    admin = staff("sm_re", "support")
    u = person("sm_reu")
    send(admin, [u.id], body="Premier")
    send(admin, [u.id], body="Second")
    assert Conversation.objects.filter(kind="support").count() == 1 and Message.objects.count() == 2


def test_staff_accounts_and_unknown_ids_are_never_recipients():
    admin, other = staff("sm_s1", "support"), staff("sm_s2", "ops")
    r = send(admin, [other.id, 999999])
    assert r.status_code == 404 and r.json()["code"] == "no_recipient" and Message.objects.count() == 0


# ------------------------------------------------------------------------------------ critères, aperçu, consentement

def test_filters_preview_counts_and_rejects_unauthorised_criteria():
    ops = staff("sm_f", "ops")
    pro = artisan("sm_pro1")
    pro.city = "Abidjan"
    pro.save()
    clients = [person(f"sm_cl{i}") for i in range(3)]
    inactive = person("sm_inactive")
    inactive.city = "Abidjan"
    inactive.is_active = False
    inactive.save()
    r = api(ops).post(f"{URL}/preview/", {"body": "Info", "filters": {"type": "artisan", "city": "abidjan"}}, format="json").json()
    assert r["recipient_count"] == 1 and r["bulk"] is True and "propre conversation" in r["note"]
    r2 = api(ops).post(f"{URL}/preview/", {"body": "Info", "filters": {"type": "client"}}, format="json").json()
    assert r2["recipient_count"] == 3                       # comptes actifs non professionnels : ni inactif, ni personnel, ni artisan
    for bad in ({"password": "x"}, {"type": "alien"}, {"kyc": "???"}):
        r3 = api(ops).post(f"{URL}/preview/", {"body": "Info", "filters": bad}, format="json")
        assert r3.status_code == 400 and r3.json()["code"] in ("invalid_filter",)
    assert api(ops).post(f"{URL}/preview/", {"body": "Info", "user_ids": [clients[0].id], "filters": {"type": "client"}}, format="json").status_code == 400
    assert api(ops).post(f"{URL}/preview/", {"body": "", "user_ids": [clients[0].id]}, format="json").json()["code"] == "empty"
    assert api(ops).post(f"{URL}/preview/", {"body": "x" * 2001, "user_ids": [clients[0].id]}, format="json").json()["code"] == "too_long"
    assert Message.objects.count() == 0                                                   # un aperçu n'envoie jamais rien


def test_inactive_accounts_are_skipped_and_reported():
    ops = staff("sm_i", "ops")
    live, dead = person("sm_live"), person("sm_dead")
    dead.is_active = False
    dead.save()
    out = send(ops, [live.id, dead.id]).json()
    assert out["results"]["sent"] == 1 and out["results"]["skipped_unreachable"] == 1 and out["recipient_count"] == 1


def test_promotions_reach_only_members_with_marketing_consent():
    ops = staff("sm_p", "ops")
    yes, no = person("sm_yes"), person("sm_no")
    MarketingConsent.objects.create(user=yes, granted=True)
    pv = api(ops).post(f"{URL}/preview/", {"body": "Offre", "user_ids": [yes.id, no.id], "purpose": "promotion"}, format="json").json()
    assert pv["recipient_count"] == 1 and pv["skipped"]["no_consent"] == 1
    out = send(ops, [yes.id, no.id], body="Offre -20%", purpose="promotion").json()
    assert out["results"] == {"pending": 0, "sent": 1, "skipped_consent": 1, "skipped_unreachable": 0, "failed": 0}
    assert Conversation.objects.filter(kind="support", participants=no).count() == 0 and Message.objects.count() == 1
    assert send(ops, [yes.id], purpose="newsletter").json()["code"] == "invalid_purpose"


# ------------------------------------------------------------------------------------------ fiabilité : rejeu, échecs

def test_redelivery_never_duplicates_and_one_failure_does_not_stop_the_batch():
    admin = staff("sm_rt", "ops")
    users = [person(f"sm_rt{i}") for i in range(3)]
    real = staff_messaging.messaging.send

    def flaky(sender, conv, content, **kw):
        if conv.pair_key == f"support:{users[1].pk}":
            raise RuntimeError("panne simulée")
        return real(sender, conv, content, **kw)

    with mock.patch.object(staff_messaging.messaging, "send", side_effect=flaky):
        batch = staff_messaging.create_batch(admin, {"user_ids": [u.pk for u in users]}, "Bonjour", "service")
        out = staff_messaging.deliver(batch.pk)
    assert out == {"sent": 2, "failed": 1}
    assert dict(StaffMessageDelivery.objects.filter(batch=batch).values_list("user_id", "status"))[users[1].pk] == "failed"
    assert staff_messaging.deliver(batch.pk) == {"sent": 1, "failed": 0}                  # reprise : seul l'échec est retraité
    assert staff_messaging.deliver(batch.pk) == {"sent": 0, "failed": 0}                  # rejeu : aucun doublon
    assert Message.objects.count() == 3 and StaffMessageBatch.objects.get().status == "done"
    # même après une interruption AVANT l'enregistrement du résultat : le message existe déjà, il n'est pas recréé
    StaffMessageDelivery.objects.filter(batch=batch).update(status="pending", message=None)
    staff_messaging.deliver(batch.pk)
    assert Message.objects.count() == 3


def test_delivery_task_is_retryable():
    from backoffice import tasks

    assert tasks.deliver_batch.max_retries == 5 and tasks.deliver_batch.name == "backoffice.tasks.deliver_batch"


# ------------------------------------------------------------------------------------------------- suivi et historique

def test_batch_history_and_per_recipient_results_with_masked_phone_and_state():
    admin, other = staff("sm_h", "support"), staff("sm_h2", "support")
    ops = staff("sm_h3", "ops")
    u1, u2 = person("sm_h_u1", phone="+2250701234567"), person("sm_h_u2")
    batch_id = send(admin, [u1.id, u2.id]).json()["id"]
    send(other, [u1.id], body="Autre envoi")
    assert [b["id"] for b in api(admin).get(f"{URL}/batches/").json()["results"]] == [batch_id]        # un agent ne voit que ses envois
    assert api(ops).get(f"{URL}/batches/").json()["count"] == 2                                          # le droit « bulk » voit tout
    detail = api(admin).get(f"{URL}/batches/{batch_id}/").json()
    rows = {r["user"]: r for r in detail["deliveries"]["results"]}
    assert rows[u1.id]["status"] == "sent" and rows[u1.id]["state"] == "sent" and "0701234567" not in str(detail) and "••••" in rows[u1.id]["phone"]
    member_api(u1).post(f"/handy/me/messages/delivered/", {"ids": [Message.objects.filter(conversation__participants=u1).first().pk]}, format="json")
    conv = Conversation.objects.get(kind="support", participants=u1)
    member_api(u1).post(f"/handy/me/conversations/{conv.pk}/read/")
    again = api(admin).get(f"{URL}/batches/{batch_id}/").json()
    assert {r["user"]: r["state"] for r in again["deliveries"]["results"]}[u1.id] == "read"
    assert api(other).get(f"{URL}/batches/{batch_id}/").status_code == 404                                # envoi d'un autre agent
    assert api(ops).get(f"{URL}/batches/{batch_id}/").status_code == 200


# ------------------------------------------------------------------------------------------ réponses des membres

def test_member_replies_reach_the_staff_inbox_and_staff_can_answer():
    admin = staff("sm_in", "support")
    u, other = person("sm_in_u", first_name="Awa"), person("sm_in_o")
    send(admin, [u.id, other.id], body="Bonjour")
    conv = Conversation.objects.get(kind="support", participants=u)
    r = member_api(u).post(f"/handy/me/conversations/{conv.pk}/send/", {"content": "J'ai un souci avec mon KYC"}, format="json")
    assert r.status_code == 201 and r.json()["message"]["mine"] is True
    inbox = api(admin).get(f"{URL}/threads/").json()["results"]
    assert len(inbox) == 2 and inbox[0]["member"]["id"] == u.id and inbox[0]["unread"] == 1 and inbox[0]["last_message"] == "J'ai un souci avec mon KYC"
    assert [t["member"]["id"] for t in api(admin).get(f"{URL}/threads/?unread=true").json()["results"]] == [u.id]
    thread = api(admin).get(f"{URL}/threads/{conv.pk}/").json()
    assert [m["from_member"] for m in thread["results"]] == [False, True] and thread["results"][0]["staff"] == "Sm_In A."
    assert api(admin).post(f"{URL}/threads/{conv.pk}/read/").json() == {"marked": 1}
    assert api(admin).get(f"{URL}/threads/?unread=true").json()["results"] == []
    assert api(admin).post(f"{URL}/threads/{conv.pk}/reply/", {"content": "Nous regardons cela."}, format="json").status_code == 201
    mine = member_api(u).get(f"/handy/me/conversations/{conv.pk}/messages/").json()["results"]
    assert mine[-1]["content"] == "Nous regardons cela." and mine[-1]["sender"] == "Équipe Tratra"
    assert audited("message.reply").count() == 1
    assert api(admin).post(f"{URL}/threads/{conv.pk}/reply/", {"content": ""}, format="json").status_code == 400
    direct = Conversation.objects.create(kind="direct")                                                     # une conversation privée n'est jamais lisible par l'équipe ici
    assert api(admin).get(f"{URL}/threads/{direct.pk}/").status_code == 404


def test_modules_menu_lists_messaging_only_for_authorised_roles():
    assert "messages" in [m["id"] for m in api(staff("sm_m1", "support")).get(f"{BO}/me/").json()["modules"]]
    assert "messages" not in [m["id"] for m in api(staff("sm_m2", "analyst")).get(f"{BO}/me/").json()["modules"]]
