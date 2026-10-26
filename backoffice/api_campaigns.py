"""Back-Office « Engagement » : bibliothèque des campagnes automatiques (messages modifiables), ciblage (audience, communes, progression),
délais et fréquence, programmation, activation / désactivation, aperçu, statistiques et historique des envois.

Droit : `announcements.manage` (rôle marketing, Super Admin). Chaque modification et chaque (dés)activation est journalisée ; une
modification concurrente est refusée (version). Activer exige un message valide et un écran ouvert à l'audience ; une campagne qui
annonce une fonction récente ne vise que les comptes dont l'application l'a (handy.features) — l'adoption est affichée."""
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response

from backoffice.common import BOView, audit_op, bad_request, paginate
from campaigns import engine, triggers
from campaigns.models import AUDIENCES, Campaign, CampaignSend
from handy import destinations, features

EDITABLE_TEXT = ("name", "title", "body", "action_label", "action_value")
EDITABLE_INT = {"delay_hours": (0, 24 * 60), "inactive_days": (1, 365), "max_age_days": (1, 90), "min_gap_hours": (0, 24 * 30), "priority": (1, 999)}
EDITABLE_BOOL = ("marketing", "send_push")
LIMITS = {"name": 140, "title": 140, "body": 600, "action_label": 40, "action_value": 120}


def serialize(c: Campaign, *, detail: bool = False) -> dict:
    trigger = triggers.trigger_for(c)
    out = {
        "id": c.id, "key": c.key, "name": c.name, "trigger": c.trigger, "trigger_label": c.get_trigger_display(), "audience": c.audience,
        "audience_label": c.get_audience_display(), "goal": trigger.goal_label if trigger else "", "is_active": c.is_active,
        "marketing": c.marketing, "send_push": c.send_push, "feature": c.feature or None,
        "features": engine.describe_features(engine.required_features(c)), "priority": c.priority,
        "title": c.title, "body": c.body, "action_label": c.action_label, "action_value": c.action_value,
        "starts_at": c.starts_at, "ends_at": c.ends_at, "activated_at": c.activated_at, "version": c.version, "updated_at": c.updated_at,
    }
    if detail:
        out.update({"communes": c.communes, "progress": c.progress, "delay_hours": c.delay_hours, "inactive_days": c.inactive_days,
                    "max_age_days": c.max_age_days, "min_gap_hours": c.min_gap_hours,
                    "action": destinations.describe(c.action_value) if c.action_value else None,
                    "stats": engine.stats(c), "preview": engine.preview(c)})
    return out


def meta() -> dict:
    return {"triggers": [{"id": k, "label": v, "audiences": list(triggers.REGISTRY[k].audiences), "goal": triggers.REGISTRY[k].goal_label}
                         for k, v in Campaign.TRIGGERS],
            "audiences": [{"id": k, "label": v} for k, v in AUDIENCES],
            "progress": [{"id": k, "label": v} for k, v in Campaign.PROGRESS],
            "destinations": destinations.catalog(),
            "features": [{"code": f.code, "label": f.label, **features.adoption([f.code])} for f in features.FEATURES],
            "rules": {"weekly_push_limit": engine.weekly_push_limit(), "send_hours": "%dh-%dh" % engine.send_hours(), "sms": False}}


class CampaignList(BOView):
    bo_permission = "announcements.manage"

    def get(self, request):
        qs = Campaign.objects.all()
        params = request.query_params
        if params.get("trigger"):
            qs = qs.filter(trigger=params["trigger"])
        if params.get("audience"):
            qs = qs.filter(audience=params["audience"])
        if params.get("active") in ("0", "1"):
            qs = qs.filter(is_active=params["active"] == "1")
        rows, adoption = [], {}
        for c in qs.order_by("priority", "key"):
            row = serialize(c)
            needed = frozenset(engine.required_features(c))
            if needed and needed not in adoption:
                adoption[needed] = features.adoption(needed)
            row["app"] = adoption.get(needed)       # téléphones dont l'application ouvre la fonction annoncée
            sent = CampaignSend.objects.filter(campaign=c, status="sent")
            row["sent"], row["converted"] = sent.count(), sent.filter(converted_at__isnull=False).count()
            rows.append(row)
        return Response({"results": rows, "meta": meta()})


def _get(pk):
    return Campaign.objects.select_related("announcement").filter(pk=pk).first()


class CampaignDetail(BOView):
    bo_permission = "announcements.manage"

    def get(self, request, pk):
        c = _get(pk)
        if c is None:
            return bad_request("not_found", "Campagne introuvable.", 404)
        data = serialize(c, detail=True)
        reach = engine.audience(c) if c.is_active or request.query_params.get("estimate") == "1" else None
        data["audience_estimate"] = reach["new"] if reach else None
        data["audience_waiting_update"] = reach["waiting_update"] if reach else None
        return Response(data)

    def patch(self, request, pk):
        c = _get(pk)
        if c is None:
            return bad_request("not_found", "Campagne introuvable.", 404)
        if str(request.data.get("version", "")) != str(c.version):
            return Response({"code": "version_conflict", "detail": "La campagne a été modifiée entre-temps : rechargez-la.", "version": c.version},
                            status=409)
        data, changed, errors = request.data, [], {}
        for field in EDITABLE_TEXT:
            if field in data:
                value = str(data.get(field) or "").strip()
                if len(value) > LIMITS[field]:
                    errors[field] = f"{LIMITS[field]} caractères au plus."
                setattr(c, field, value)
                changed.append(field)
        for field, (lo, hi) in EDITABLE_INT.items():
            if field in data:
                try:
                    value = int(data[field])
                except (TypeError, ValueError):
                    errors[field] = "Nombre entier attendu."
                    continue
                if not lo <= value <= hi:
                    errors[field] = f"Entre {lo} et {hi}."
                setattr(c, field, value)
                changed.append(field)
        for field in EDITABLE_BOOL:
            if field in data:
                setattr(c, field, bool(data[field]))
                changed.append(field)
        for field in ("communes", "progress"):
            if field in data:
                values = data[field] if isinstance(data[field], list) else []
                setattr(c, field, [str(v).strip() for v in values if str(v).strip()][:50])
                changed.append(field)
        for field in ("starts_at", "ends_at"):
            if field in data:
                raw = data[field]
                setattr(c, field, parse_datetime(raw) if raw else None)
                if raw and getattr(c, field) is None:
                    errors[field] = "Date invalide."
                changed.append(field)
        for field in ("trigger", "audience"):          # nature de la campagne : seulement quand elle est désactivée
            if field in data and data[field] != getattr(c, field):
                if c.is_active:
                    errors[field] = "Désactivez la campagne avant de changer son déclencheur ou son audience."
                else:
                    setattr(c, field, str(data[field]))
                    changed.append(field)
        if errors:
            return Response({"code": "invalid", "detail": "Vérifiez les champs signalés.", "fields": errors}, status=400)
        try:
            engine.validate(c)
        except ValidationError as exc:
            return bad_request("invalid", " ".join(exc.messages), 400)
        c.version += 1
        c.updated_by = request.user
        c.save()
        engine.sync_announcement(c)
        audit_op(request, "campaign.updated", None, campaign=c.key, fields=sorted(set(changed)))
        return Response(serialize(_get(pk), detail=True))


class CampaignAction(BOView):
    bo_permission = "announcements.manage"

    def post(self, request, pk, action):
        c = _get(pk)
        if c is None or action not in ("activate", "deactivate"):
            return bad_request("not_found", "Introuvable.", 404)
        try:
            c = engine.set_active(c, action == "activate", actor=request.user)
        except ValidationError as exc:
            return bad_request("invalid", " ".join(exc.messages), 400)
        audit_op(request, f"campaign.{action}d", None, campaign=c.key)
        return Response(serialize(_get(pk), detail=True))


class CampaignSends(BOView):
    """Historique des envois d'une campagne (statut, motif, push, conversion) — nom public du destinataire seulement."""
    bo_permission = "announcements.manage"

    def get(self, request, pk):
        c = _get(pk)
        if c is None:
            return bad_request("not_found", "Campagne introuvable.", 404)
        qs = CampaignSend.objects.filter(campaign=c).select_related("user").order_by("-created_at", "-id")
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])

        def row(s):
            first = (s.user.first_name or "").strip()
            name = f"{first} {(s.user.last_name or '')[:1]}.".strip() if first else f"Compte #{s.user_id}"
            return {"id": s.id, "user": name, "ref": s.ref, "status": s.status, "status_label": s.get_status_display(), "reason": s.reason,
                    "push": s.push, "due_at": s.due_at, "sent_at": s.sent_at, "converted_at": s.converted_at, "created_at": s.created_at}

        return paginate(request, qs, row)


class CampaignRun(BOView):
    """Exécuter un passage maintenant (programmation + envoi des messages dus) — mêmes règles que la tâche planifiée."""
    bo_permission = "announcements.manage"

    def post(self, request):
        result = engine.tick(timezone.now())
        audit_op(request, "campaign.run", None, **{k: v for k, v in result.items() if isinstance(v, int)})
        return Response(result)
