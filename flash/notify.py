"""Notifications Tratra Flash : nouvelle mission (alerte prioritaire « Ta – Tra – Tra ! »), arrêt de l'alerte, devis, demande sans pro.

Une proposition n'alerte que tant qu'elle attend une réponse : le push n'est jamais envoyé pour une proposition déjà attribuée, retirée ou
expirée (contrôle au moment de l'envoi, `deliverable_ttl`), sa durée de vie FCM est le temps de réponse restant, et sa fermeture envoie un
signal silencieux qui retire l'alerte des téléphones. Aucune donnée privée du client (nom, téléphone, adresse exacte) n'est transmise."""
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from flash.models import MissionOffer, MissionRequest
from handy.notifications import notify

FLASH_CAPABILITY = "flash1"          # appareil dont l'application affiche elle-même l'alerte (actions Accepter / Refuser / Voir)
DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def offer_key(offer_id: int) -> str:
    return f"flash:offer:{offer_id}"


def money(amount) -> str:
    return f"{int(amount):,}".replace(",", " ") + " FCFA"


def when_label(req: MissionRequest) -> str:
    if req.is_immediate:
        return "Maintenant"
    local = timezone.localtime(req.scheduled_for)
    today = timezone.localdate()
    day = ("Aujourd'hui" if local.date() == today else "Demain" if local.date() == today + timedelta(days=1)
           else f"{DAYS[local.weekday()].capitalize()} {local:%d/%m}")
    return f"{day} à {local:%H} h {local:%M}"


def duration_label(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 120:
        return f"{seconds} s"
    return f"{round(seconds / 60)} min"


def zone_label(req: MissionRequest) -> str:
    return req.commune or req.city or "Zone non précisée"


def offer_payload(offer: MissionOffer) -> dict:
    """Ce que voit le professionnel AVANT d'accepter : métier, zone, date, montant, délai, distance. Ni nom, ni téléphone, ni adresse."""
    req = offer.request
    return {"kind": "flash_offer", "id": offer.pk, "request": req.pk, "mode": req.mode, "category": req.category.name,
            "zone": zone_label(req), "when": timezone.localtime(req.scheduled_for).isoformat(), "when_label": when_label(req),
            "immediate": "1" if req.is_immediate else "0", "amount": str(int(req.amount)) if req.amount is not None else "",
            "amount_label": money(req.amount) if req.amount is not None else "Sur devis",
            "expires_at": offer.expires_at.isoformat(), "distance_km": "" if offer.distance_km is None else str(offer.distance_km)}


def new_offer(offer_id: int) -> None:
    offer = MissionOffer.objects.select_related("request", "request__category").filter(pk=offer_id).first()
    if offer is None or offer.status != MissionOffer.PENDING:
        return
    req = offer.request
    remaining = int((offer.expires_at - timezone.now()).total_seconds())
    price = money(req.amount) if req.amount is not None else "Sur devis"
    notify(offer.handyman_id, "new_mission",
           f"{zone_label(req)} · {when_label(req)} · {price} — {duration_label(remaining)} pour répondre",
           title=f"Nouvelle mission · {req.category.name}", data=offer_payload(offer), dedupe_key=offer_key(offer.pk),
           content_object=offer, collapse_key=f"flash-{offer.pk}")


def deliverable_ttl(notification) -> Optional[int]:
    """Durée de vie du push d'une nouvelle mission (secondes restantes) ; None si la proposition n'attend plus de réponse."""
    offer = MissionOffer.objects.filter(pk=(notification.data or {}).get("id")).only("status", "expires_at").first()
    if offer is None or offer.status != MissionOffer.PENDING:
        return None
    remaining = int((offer.expires_at - timezone.now()).total_seconds())
    return remaining if remaining >= 5 else None


def offer_closed(offer_id: int) -> None:
    """La proposition n'attend plus de réponse : la notification est marquée lue et l'alerte est retirée des téléphones."""
    from handy import push
    from handy.models import Notification

    offer = MissionOffer.objects.filter(pk=offer_id).only("handyman_id", "status").first()
    if offer is None:
        return
    Notification.objects.filter(user_id=offer.handyman_id, dedupe_key=offer_key(offer_id), is_read=False).update(
        is_read=True, read_at=timezone.now())
    push.send_data_to_user(offer.handyman_id, {"t": "flash_closed", "offer": offer_id, "status": offer.status},
                           capability=FLASH_CAPABILITY, ttl_seconds=600, collapse_key=f"flash-{offer_id}")


def quote_received(offer_id: int) -> None:
    offer = MissionOffer.objects.select_related("request", "request__category", "handyman").filter(pk=offer_id).first()
    if offer is None or offer.status != MissionOffer.QUOTED:
        return
    req = offer.request
    who = (offer.handyman.first_name or "").strip() or "Un professionnel"
    notify(req.client_id, "mission_quote", f"{who} propose {money(offer.quote_amount)} pour « {req.category.name} ».",
           title="Nouveau devis", data={"kind": "flash_request", "id": req.pk}, dedupe_key=f"flash:quote:{offer.pk}", content_object=req)


def unfulfilled(request_id: int) -> None:
    req = MissionRequest.objects.select_related("category").filter(pk=request_id).first()
    if req is None or req.status != MissionRequest.UNFULFILLED:
        return
    notify(req.client_id, "mission_unfulfilled",
           f"Aucun professionnel n'a pu prendre « {req.category.name} ». Vous pouvez relancer avec un autre horaire ou un autre montant.",
           title="Aucun professionnel disponible", data={"kind": "flash_request", "id": req.pk},
           dedupe_key=f"flash:request:{req.pk}:unfulfilled", content_object=req)


def paused(user_id: int, streak: int) -> None:
    now = timezone.now()
    notify(user_id, "mission_paused",
           f"{streak} propositions sont restées sans réponse : vous ne recevez plus de missions immédiates. Repassez « Disponible » quand "
           f"vous le souhaitez — aucune conséquence sur votre réputation.",
           title="Vous êtes passé « Indisponible »", data={"kind": "availability"}, dedupe_key=f"flash:paused:{user_id}:{now:%Y%m%d%H%M}")
