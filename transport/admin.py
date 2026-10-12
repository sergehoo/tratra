from django.contrib import admin

from handy.admin_utils import ReadOnlyConfigAdmin
from transport.models import TransportBand, TransportConfig, TransportConfigVersion, TransportZone

# Consultation seule : les tarifs de transport se modifient dans le Back-Office (Administration > Réglages > Transport) pour que chaque
# changement exige un motif, crée une version et laisse une trace d'audit. Les réservations conservent le calcul qui les concerne.


@admin.register(TransportConfig)
class TransportConfigAdmin(ReadOnlyConfigAdmin, admin.ModelAdmin):
    list_display = ('__str__', 'enabled', 'threshold_km', 'mode', 'fallback_flat_amount', 'effective_from', 'version', 'updated_at')


@admin.register(TransportZone)
class TransportZoneAdmin(ReadOnlyConfigAdmin, admin.ModelAdmin):
    list_display = ('name', 'is_active')
    search_fields = ('name',)


@admin.register(TransportBand)
class TransportBandAdmin(ReadOnlyConfigAdmin, admin.ModelAdmin):
    list_display = ('name', 'zone', 'start_time', 'end_time', 'weekdays', 'rate_per_km', 'is_active', 'valid_from', 'valid_to')
    list_filter = ('is_active', 'zone')


@admin.register(TransportConfigVersion)
class TransportConfigVersionAdmin(ReadOnlyConfigAdmin, admin.ModelAdmin):
    list_display = ('version', 'changed_at', 'changed_by', 'reason')
    search_fields = ('reason',)
