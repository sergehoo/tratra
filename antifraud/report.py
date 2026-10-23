"""Comptes suspects (inscriptions en masse) : RAPPORT d'abord, action ensuite, toujours réversible.

Signaux, sur une période d'inscription :
 - nom complet répété (normalisé : « Rita Kamal » = « RITA kamal ») ;
 - numéros d'un même bloc de 1 000 (+225 01 15 98 1xx) ;
 - même adresse IP d'inscription (journal `SignupLog`, à partir de ce correctif) ;
 - rafale : de nombreux comptes créés en quelques minutes ;
 - téléphone jamais vérifié, jamais connecté ; SMS reçus (journal `SmsLog`).
Un compte n'est CANDIDAT que s'il n'a pas de numéro vérifié, aucune activité réelle (réservation, offre, message, demande Tratra
Flash, pièce KYC) et au moins deux signaux dont un signal de masse (nom, bloc, IP, rafale). Le personnel n'est jamais candidat.

La désactivation (is_active = faux) ne supprime rien : chaque compte est inscrit dans un lot (`SuspensionBatch`) avec son état
précédent, et `revert` le rétablit à l'identique. Les sessions des comptes désactivés sont révoquées."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Iterable, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from antifraud.models import AccountSuspension, SignupLog, SmsLog, SuspensionBatch
from antifraud.signup_guard import normalize_name, phone_block

User = get_user_model()
MASS_SIGNALS = ("nom répété", "bloc de numéros", "même IP", "rafale")


def _mask(phone: str) -> str:
    from handy.sms import mask

    return mask(phone or "")


def active_user_ids(ids: Iterable[int]) -> set:
    """Comptes ayant une activité réelle : jamais désactivés en lot."""
    from flash.models import MissionRequest
    from handy.models import Booking, HandymanDocument, Message, Service

    ids = list(ids)
    found = set(Booking.objects.filter(client_id__in=ids).values_list("client_id", flat=True))
    found |= set(Booking.objects.filter(handyman_id__in=ids).values_list("handyman_id", flat=True))
    found |= set(Service.objects.filter(handyman_id__in=ids).values_list("handyman_id", flat=True))
    found |= set(Message.objects.filter(sender_id__in=ids).values_list("sender_id", flat=True))
    found |= set(MissionRequest.objects.filter(client_id__in=ids).values_list("client_id", flat=True))
    found |= set(HandymanDocument.objects.filter(handyman__user_id__in=ids).values_list("handyman__user_id", flat=True))
    return found


def _bursts(rows, minutes: int, size: int) -> set:
    """Comptes créés dans une fenêtre de `minutes` contenant au moins `size` inscriptions."""
    times = sorted((r["date_joined"], r["id"]) for r in rows)
    flagged, start = set(), 0
    window = timedelta(minutes=minutes)
    for end in range(len(times)):
        while times[end][0] - times[start][0] > window:
            start += 1
        if end - start + 1 >= size:
            flagged.update(uid for _, uid in times[start:end + 1])
    return flagged


def build(since: datetime, until: Optional[datetime] = None, *, min_name: int = 3, min_block: int = 3, min_ip: int = 3,
          burst_minutes: int = 10, burst_size: int = 5) -> dict:
    until = until or timezone.now()
    rows = list(User.objects.filter(date_joined__gte=since, date_joined__lt=until, is_staff=False, is_superuser=False)
                .values("id", "username", "first_name", "last_name", "phone", "is_verified", "is_active", "date_joined", "last_login"))
    ids = [r["id"] for r in rows]
    names = {r["id"]: normalize_name(r["first_name"], r["last_name"]) for r in rows}
    blocks = {r["id"]: phone_block(r["phone"] or "") for r in rows}
    ips = dict(SignupLog.objects.filter(user_id__in=ids).exclude(ip=None).values_list("user_id", "ip"))
    sms = dict(SmsLog.objects.filter(user_id__in=ids, status="sent").values("user_id").annotate(n=Count("id")).values_list("user_id", "n"))
    name_count = Counter(n for n in names.values() if n)
    block_count = Counter(b for b in blocks.values() if b)
    ip_count = Counter(ips.values())
    bursts = _bursts(rows, burst_minutes, burst_size)
    active = active_user_ids(ids)

    candidates, excluded_active, excluded_verified = [], 0, 0
    for r in rows:
        uid = r["id"]
        reasons = []
        if names[uid] and name_count[names[uid]] >= min_name:
            reasons.append(f"nom répété ×{name_count[names[uid]]}")
        if blocks[uid] and block_count[blocks[uid]] >= min_block:
            reasons.append(f"bloc de numéros ×{block_count[blocks[uid]]}")
        if uid in ips and ip_count[ips[uid]] >= min_ip:
            reasons.append(f"même IP ×{ip_count[ips[uid]]}")
        if uid in bursts:
            reasons.append("rafale")
        if not r["is_verified"]:
            reasons.append("téléphone non vérifié")
        if r["last_login"] is None:
            reasons.append("jamais connecté")
        if sms.get(uid):
            reasons.append(f"{sms[uid]} SMS reçu(s)")
        mass = any(reason.startswith(MASS_SIGNALS) for reason in reasons)
        if not mass or len(reasons) < 2:
            continue
        if r["is_verified"]:
            excluded_verified += 1
            continue
        if uid in active:
            excluded_active += 1
            continue
        candidates.append({"id": uid, "username": r["username"], "name": f"{r['first_name']} {r['last_name']}".strip(),
                           "phone": _mask(r["phone"]), "joined": r["date_joined"].isoformat(), "active": r["is_active"],
                           "reasons": reasons})
    by_hour = Counter(r["date_joined"].strftime("%Y-%m-%d %H:00") for r in rows)
    sms_period = SmsLog.objects.filter(created_at__gte=since, created_at__lt=until)
    return {
        "criteria": {"since": since.isoformat(), "until": until.isoformat(), "min_name": min_name, "min_block": min_block,
                     "min_ip": min_ip, "burst_minutes": burst_minutes, "burst_size": burst_size},
        "summary": {
            "accounts": len(rows), "candidates": len(candidates), "excluded_active": excluded_active,
            "excluded_verified": excluded_verified, "unverified": sum(1 for r in rows if not r["is_verified"]),
            "top_names": [[n, c] for n, c in name_count.most_common(10) if c > 1],
            "top_phone_blocks": [[f"+{b}xxx", c] for b, c in block_count.most_common(10) if c > 1],
            "top_ips": [[ip, c] for ip, c in ip_count.most_common(10) if c > 1],
            "signups_by_hour": sorted(by_hour.items()),
            "sms": {status: sms_period.filter(status=status).count() for status in ("sent", "blocked", "failed")},
            "sms_blocked_by_reason": dict(sms_period.filter(status="blocked").values_list("reason").annotate(n=Count("id"))),
        },
        "candidates": candidates,
    }


def _revoke_sessions(user) -> None:
    try:
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
    except Exception:  # noqa: BLE001
        return
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


@transaction.atomic
def suspend(candidates: list, *, label: str, criteria: dict, actor: str = "") -> tuple:
    """Désactive les candidats d'un rapport relu, après une NOUVELLE vérification (vérifié entre-temps, activité, personnel :
    écartés). Renvoie (lot, nombre désactivé, nombre écarté)."""
    from trust.models import audit

    by_id = {int(c["id"]): c for c in candidates}
    users = list(User.objects.select_for_update().filter(pk__in=list(by_id), is_staff=False, is_superuser=False))
    active = active_user_ids(u.pk for u in users)
    batch = SuspensionBatch.objects.create(label=label[:120], criteria=criteria, created_by=actor[:150])
    done = skipped = 0
    for user in users:
        if user.is_verified or user.pk in active:
            skipped += 1
            continue
        AccountSuspension.objects.create(batch=batch, user=user, was_active=user.is_active, reasons=by_id[user.pk].get("reasons", []))
        if user.is_active:
            user.is_active = False
            user.save(update_fields=["is_active"])
        _revoke_sessions(user)
        done += 1
    skipped += len(by_id) - len(users)
    audit("antifraud.batch_suspended", target=batch, accounts=done, skipped=skipped, actor_label=actor)
    return batch, done, skipped


@transaction.atomic
def revert(batch_id: int, *, actor: str = "") -> int:
    """Rétablit chaque compte du lot dans son état d'avant (actif s'il l'était). Idempotent."""
    from trust.models import audit

    batch = SuspensionBatch.objects.select_for_update().get(pk=batch_id)
    restored = 0
    for item in batch.items.select_related("user").filter(restored=False):
        if item.was_active and not item.user.is_active:
            item.user.is_active = True
            item.user.save(update_fields=["is_active"])
        item.restored = True
        item.save(update_fields=["restored"])
        restored += 1
    batch.reverted_at, batch.reverted_by = timezone.now(), actor[:150]
    batch.save(update_fields=["reverted_at", "reverted_by"])
    audit("antifraud.batch_reverted", target=batch, accounts=restored, actor_label=actor)
    return restored


def restore_one(batch_id: int, user_id: int) -> bool:
    """Réactive un seul compte légitime d'un lot (réclamation)."""
    item = AccountSuspension.objects.select_related("user").filter(batch_id=batch_id, user_id=user_id, restored=False).first()
    if item is None:
        return False
    if item.was_active:
        item.user.is_active = True
        item.user.save(update_fields=["is_active"])
    item.restored = True
    item.save(update_fields=["restored"])
    return True

