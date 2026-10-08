# services/matching.py
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.utils import timezone
from handy.models import HandymanProfile, TimeOff

def match_artisans(lat: float, lng: float, category_id: int, radius_km=15, limit=10):
    origin = Point(lng, lat, srid=4326)
    now = timezone.now()
    # artisans actuellement en congé/absence -> exclus du matching
    on_timeoff = TimeOff.objects.filter(start__lte=now, end__gte=now).values_list('handyman_id', flat=True)
    qs = (HandymanProfile.objects
          .filter(is_approved=True, online=True, skills__id=category_id, location__isnull=False)
          .exclude(id__in=on_timeoff)
          .annotate(distance=Distance('location', origin))
          .filter(distance__lte=radius_km*1000)
          .order_by('distance','-rating','-completed_jobs')[:limit])
    return qs