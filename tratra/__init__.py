from .celery import app as celery  # <-- expose un attribut "celery" pour contenter Celery
# Optionnel : aussi l’alias habituel
from .celery import app as celery_app

__all__ = ("celery", "celery_app")