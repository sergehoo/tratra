# services/pricing.py
from decimal import Decimal
from django.utils import timezone
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point

BASES = {
  'menage': Decimal('2500'),
  'plomberie': Decimal('3000'),
  'electricite': Decimal('3500'),
}

def estimate_price(category_slug: str, minutes: int, artisan_loc, client_lat, client_lng):
    base = BASES.get(category_slug, Decimal('3000'))
    duration = Decimal(max(30, minutes)) / Decimal(60)  # min 30min
    surge = Decimal('1.20') if 18 <= timezone.localtime().hour <= 22 else Decimal('1.00')

    # distance (km)
    if artisan_loc:
        dist_m = Distance('location', Point(client_lng, client_lat, srid=4326))
        # si tu veux un calcul coté DB, passe par annotate avant; sinon calcule côté app si tu as 2 points
    distance_factor = Decimal('1.00')  # brancher calc réel si besoin

    total = (base * duration * surge * distance_factor).quantize(Decimal('1.'))
    return max(total, Decimal('1000'))  # floor