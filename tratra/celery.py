# tratra/celery.py
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tratra.settings")  # ou .dev selon ton env

app = Celery("tratra")

# lit les variables CELERY_... depuis le settings Django
app.config_from_object("django.conf:settings", namespace="CELERY")

# auto-discovery des tasks.py dans toutes les apps installées
app.autodiscover_tasks()