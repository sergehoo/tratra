"""Back-Office — paramètres de transport (frais de déplacement) : configuration, zones et tranches horaires, avec historique.

Tout changement exige un motif, crée une nouvelle version (instantané) et une trace d'audit. Aucune suppression : on désactive
(les réservations déjà calculées conservent leur détail et leur version)."""
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from rest_framework.response import Response

from backoffice.common import BOView, audit_op, bad_request
from transport import pricing, versions
from transport.models import TransportBand, TransportConfig, TransportConfigVersion, TransportZone

MIN_REASON = 5
DAYS_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]


def _errors(errors: dict) -> Response:
    return Response({"code": "invalid", "detail": "Formulaire invalide.", "fields": errors}, status=400)


def _reason(request, errors: dict) -> str:
    value = str(request.data.get("reason") or "").strip()
    if len(value) < MIN_REASON:
        errors["reason"] = f"Un motif d'au moins {MIN_REASON} caractères est obligatoire."
    return value[:255]


def _date(raw, errors, key):
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        errors[key] = "Date invalide (AAAA-MM-JJ)."
        return None


def _time(raw, errors, key):
    try:
        h, m = str(raw).split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, TypeError):
        errors[key] = "Heure invalide (HH:MM)."
        return None


def _dec(raw, lo, hi, errors, key):
    try:
        v = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        errors[key] = "Nombre invalide."
        return None
    if not (Decimal(lo) <= v <= Decimal(hi)):
        errors[key] = f"Valeur attendue entre {lo} et {hi}."
        return None
    return v.quantize(Decimal("0.01"))


def _config_row(c: TransportConfig) -> dict:
    return {"enabled": c.enabled, "threshold_km": str(c.threshold_km), "currency": c.currency, "mode": c.mode, "mode_label": dict(TransportConfig.MODES)[c.mode],
            "fallback_flat_amount": c.fallback_flat_amount, "rounding_step": c.rounding_step, "rounding_method": c.rounding_method,
            "effective_from": c.effective_from, "version": c.version, "updated_at": c.updated_at}


def _band_row(b: TransportBand) -> dict:
    return {"id": b.pk, "name": b.name, "zone": b.zone_id, "zone_name": b.zone.name if b.zone_id else None, "start": b.start_time.strftime("%H:%M"),
            "end": b.end_time.strftime("%H:%M"), "weekdays": b.weekdays, "days_label": ", ".join(DAYS_FR[d] for d in sorted(b.weekdays or [])),
            "rate_per_km": str(b.rate_per_km), "is_active": b.is_active, "valid_from": b.valid_from, "valid_to": b.valid_to}


def _zone_row(z: TransportZone) -> dict:
    return {"id": z.pk, "name": z.name, "communes": z.communes, "is_active": z.is_active}


def _example(cfg: TransportConfig, km: float = 8.0):
    """Exemple chiffré avec les tarifs RÉELS configurés : rend le mode de calcul sans ambiguïté (km aller simple)."""
    out = []
    for b in TransportBand.objects.filter(is_active=True, zone__isnull=True).order_by("start_time")[:6]:
        probe = datetime.combine(date.today(), b.start_time, tzinfo=pricing.TZ)
        out.append({"band": b.name, "distance_km": km, "amount": pricing._round(Decimal(str(km)) * (2 if cfg.mode == TransportConfig.ROUND_TRIP_BILLED else 1) * b.rate_per_km, cfg),
                    "at": probe.strftime("%H:%M")})
    return out


class TransportOverview(BOView):
    bo_permission = "settings.manage"

    def get(self, request):
        cfg = TransportConfig.current()
        return Response({
            "config": _config_row(cfg), "modes": [{"value": v, "label": l} for v, l in TransportConfig.MODES],
            "zones": [_zone_row(z) for z in TransportZone.objects.order_by("name")],
            "bands": [_band_row(b) for b in TransportBand.objects.select_related("zone").order_by("start_time", "id")],
            "versions": [{"version": v.version, "changed_at": v.changed_at, "reason": v.reason, "changed_by": v.changed_by.get_full_name() or "Équipe" if v.changed_by_id else None}
                         for v in TransportConfigVersion.objects.select_related("changed_by")[:20]],
            "example": _example(cfg), "timezone": "Africa/Abidjan",
        })

    def put(self, request):
        cfg = TransportConfig.current()
        errors: dict = {}
        reason = _reason(request, errors)
        d = request.data
        values = {}
        if "enabled" in d:
            values["enabled"] = bool(d["enabled"])
        if "threshold_km" in d:
            values["threshold_km"] = _dec(d["threshold_km"], "0", "100", errors, "threshold_km")
        if "mode" in d:
            if d["mode"] not in dict(TransportConfig.MODES):
                errors["mode"] = "Mode de calcul inconnu."
            else:
                values["mode"] = d["mode"]
        if "fallback_flat_amount" in d:
            try:
                n = int(d["fallback_flat_amount"])
                if not 0 <= n <= 1_000_000:
                    raise ValueError
                values["fallback_flat_amount"] = n
            except (TypeError, ValueError):
                errors["fallback_flat_amount"] = "Montant entier attendu."
        if "rounding_step" in d:
            try:
                n = int(d["rounding_step"])
                if not 1 <= n <= 10_000:
                    raise ValueError
                values["rounding_step"] = n
            except (TypeError, ValueError):
                errors["rounding_step"] = "Entier entre 1 et 10000 attendu."
        if "rounding_method" in d:
            if d["rounding_method"] not in dict(TransportConfig.ROUND_METHODS):
                errors["rounding_method"] = "Méthode d'arrondi inconnue."
            else:
                values["rounding_method"] = d["rounding_method"]
        if "effective_from" in d:
            values["effective_from"] = _date(d["effective_from"], errors, "effective_from")
        if errors:
            return _errors(errors)
        changes = {k: {"old": str(getattr(cfg, k)), "new": str(v)} for k, v in values.items() if getattr(cfg, k) != v}
        if not changes:
            return Response(_config_row(cfg))
        for k, v in values.items():
            setattr(cfg, k, v)
        cfg.save()
        cfg = versions.new_version(request.user, reason)
        audit_op(request, "transport.config_updated", cfg, changes=changes, version=cfg.version, reason=reason)
        return Response(_config_row(cfg))


def _overlaps(candidate: dict, ignore_id=None) -> bool:
    for b in TransportBand.objects.filter(is_active=True, zone_id=candidate["zone_id"]).exclude(pk=ignore_id):
        if set(b.weekdays or []) & set(candidate["weekdays"]) and candidate["start"] < b.end_time and b.start_time < candidate["end"]:
            if (b.valid_from or date.min) <= (candidate["valid_to"] or date.max) and (candidate["valid_from"] or date.min) <= (b.valid_to or date.max):
                return True
    return False


def _band_payload(request, errors, current: TransportBand = None):
    d = request.data
    name = str(d.get("name", current.name if current else "")).strip()[:80]
    if not name:
        errors["name"] = "Nom obligatoire."
    start = _time(d.get("start", current.start_time.strftime("%H:%M") if current else ""), errors, "start")
    end = _time(d.get("end", current.end_time.strftime("%H:%M") if current else ""), errors, "end")
    if start and end and not start < end:
        errors["end"] = "L'heure de fin doit suivre l'heure de début (une tranche ne traverse pas minuit)."
    days = d.get("weekdays", current.weekdays if current else None)
    if not isinstance(days, list) or not days or not all(isinstance(x, int) and 0 <= x <= 6 for x in days):
        errors["weekdays"] = "Choisissez au moins un jour (0 = lundi … 6 = dimanche)."
    rate = _dec(d.get("rate_per_km", current.rate_per_km if current else None), "0", "100000", errors, "rate_per_km")
    zone = current.zone if current else None
    if "zone" in d:
        zone = TransportZone.objects.filter(pk=d["zone"]).first() if d["zone"] else None
        if d["zone"] and zone is None:
            errors["zone"] = "Zone inconnue."
    vf = _date(d.get("valid_from", current.valid_from.isoformat() if current and current.valid_from else None), errors, "valid_from")
    vt = _date(d.get("valid_to", current.valid_to.isoformat() if current and current.valid_to else None), errors, "valid_to")
    active = bool(d.get("is_active", current.is_active if current else True))
    if not errors and active and _overlaps({"zone_id": zone.pk if zone else None, "weekdays": days, "start": start, "end": end, "valid_from": vf, "valid_to": vt}, current.pk if current else None):
        errors["start"] = "Cette plage chevauche une tranche active de la même zone aux mêmes jours."
    return dict(name=name, start_time=start, end_time=end, weekdays=sorted(set(days)) if isinstance(days, list) else days, rate_per_km=rate, zone=zone, valid_from=vf, valid_to=vt, is_active=active)


class TransportBandCreate(BOView):
    bo_permission = "settings.manage"

    def post(self, request):
        errors: dict = {}
        reason = _reason(request, errors)
        data = _band_payload(request, errors)
        if errors:
            return _errors(errors)
        band = TransportBand.objects.create(**data)
        cfg = versions.new_version(request.user, reason)
        audit_op(request, "transport.band_created", band, version=cfg.version, rate_per_km=str(band.rate_per_km), reason=reason)
        return Response(_band_row(band), status=201)


class TransportBandUpdate(BOView):
    bo_permission = "settings.manage"

    def patch(self, request, pk):
        band = TransportBand.objects.select_related("zone").filter(pk=pk).first()
        if band is None:
            return bad_request("not_found", "Tranche introuvable.", 404)
        errors: dict = {}
        reason = _reason(request, errors)
        data = _band_payload(request, errors, band)
        if errors:
            return _errors(errors)
        before = _band_row(band)
        for k, v in data.items():
            setattr(band, k, v)
        band.save()
        cfg = versions.new_version(request.user, reason)
        audit_op(request, "transport.band_updated", band, version=cfg.version, before={k: str(before[k]) for k in ("rate_per_km", "start", "end", "is_active")}, reason=reason)
        return Response(_band_row(band))


def _zone_payload(request, errors, current: TransportZone = None):
    d = request.data
    name = str(d.get("name", current.name if current else "")).strip()[:80]
    if not name:
        errors["name"] = "Nom obligatoire."
    elif TransportZone.objects.filter(name__iexact=name).exclude(pk=current.pk if current else None).exists():
        errors["name"] = "Une zone porte déjà ce nom."
    communes = d.get("communes", current.communes if current else None)
    if not isinstance(communes, list) or not [c for c in communes if str(c).strip()]:
        errors["communes"] = "Indiquez au moins une commune ou ville."
        communes = []
    return dict(name=name, communes=[str(c).strip()[:100] for c in communes if str(c).strip()][:100], is_active=bool(d.get("is_active", current.is_active if current else True)))


class TransportZoneCreate(BOView):
    bo_permission = "settings.manage"

    def post(self, request):
        errors: dict = {}
        reason = _reason(request, errors)
        data = _zone_payload(request, errors)
        if errors:
            return _errors(errors)
        zone = TransportZone.objects.create(**data)
        cfg = versions.new_version(request.user, reason)
        audit_op(request, "transport.zone_created", zone, version=cfg.version, reason=reason)
        return Response(_zone_row(zone), status=201)


class TransportZoneUpdate(BOView):
    bo_permission = "settings.manage"

    def patch(self, request, pk):
        zone = TransportZone.objects.filter(pk=pk).first()
        if zone is None:
            return bad_request("not_found", "Zone introuvable.", 404)
        errors: dict = {}
        reason = _reason(request, errors)
        data = _zone_payload(request, errors, zone)
        if errors:
            return _errors(errors)
        for k, v in data.items():
            setattr(zone, k, v)
        zone.save()
        cfg = versions.new_version(request.user, reason)
        audit_op(request, "transport.zone_updated", zone, version=cfg.version, reason=reason)
        return Response(_zone_row(zone))
