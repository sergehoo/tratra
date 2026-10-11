"""Historique des modifications : chaque changement de configuration, de zone ou de tranche crée une nouvelle version (instantané)."""
from django.db import transaction

from transport.models import TransportBand, TransportConfig, TransportConfigVersion, TransportZone


def snapshot(cfg: TransportConfig) -> dict:
    return {
        "config": {"enabled": cfg.enabled, "threshold_km": str(cfg.threshold_km), "currency": cfg.currency, "mode": cfg.mode,
                   "fallback_flat_amount": cfg.fallback_flat_amount, "rounding_step": cfg.rounding_step, "rounding_method": cfg.rounding_method,
                   "effective_from": cfg.effective_from.isoformat() if cfg.effective_from else None},
        "zones": [{"id": z.pk, "name": z.name, "communes": z.communes, "is_active": z.is_active} for z in TransportZone.objects.order_by("id")],
        "bands": [{"id": b.pk, "name": b.name, "zone": b.zone_id, "start": b.start_time.strftime("%H:%M"), "end": b.end_time.strftime("%H:%M"),
                   "weekdays": b.weekdays, "rate_per_km": str(b.rate_per_km), "is_active": b.is_active,
                   "valid_from": b.valid_from.isoformat() if b.valid_from else None, "valid_to": b.valid_to.isoformat() if b.valid_to else None}
                  for b in TransportBand.objects.order_by("start_time", "id")],
    }


@transaction.atomic
def new_version(actor, reason: str) -> TransportConfig:
    """À appeler APRÈS une modification : incrémente la version de la configuration et enregistre l'instantané."""
    cfg = TransportConfig.objects.select_for_update().order_by("id").first() or TransportConfig.objects.create()
    cfg.version += 1
    cfg.updated_by = actor
    cfg.save(update_fields=["version", "updated_by", "updated_at"])
    TransportConfigVersion.objects.create(version=cfg.version, snapshot=snapshot(cfg), changed_by=actor, reason=reason[:255])
    return cfg
