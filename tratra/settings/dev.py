# settings/dev.py

from .base import *

import os
import sys
from pathlib import Path
ALLOWED_HOSTS = ['*']

# Do not force macOS Homebrew paths in Linux CI/containers.  On a local macOS
# development machine, use the Homebrew path only when it actually exists;
# other environments retain Django's normal auto-discovery.
if os.getenv('GDAL_LIBRARY_PATH'):
    GDAL_LIBRARY_PATH = os.environ['GDAL_LIBRARY_PATH']
elif sys.platform == 'darwin':
    _gdal_homebrew = Path('/opt/homebrew/opt/gdal/lib/libgdal.dylib')
    if _gdal_homebrew.exists():
        GDAL_LIBRARY_PATH = str(_gdal_homebrew)
if os.getenv('GEOS_LIBRARY_PATH'):
    GEOS_LIBRARY_PATH = os.environ['GEOS_LIBRARY_PATH']
elif sys.platform == 'darwin':
    _geos_homebrew = Path('/opt/homebrew/opt/geos/lib/libgeos_c.dylib')
    if _geos_homebrew.exists():
        GEOS_LIBRARY_PATH = str(_geos_homebrew)

DEBUG = True

# En dev/test : stockage statique simple (pas de manifeste hashé prod).
# {% static %} renvoie /static/... sans exiger un collectstatic préalable.
STORAGES["staticfiles"] = {
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}

DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': config('DB_NAME', 'tratra'),
        'USER': config('DB_USER', 'postgres'),
        'PASSWORD': config('DB_PASSWORD', 'secret'),
        'HOST': config('DB_HOST', '127.0.0.1'),
        'PORT': config('DB_PORT', '5433'),
    }
}

SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
USE_X_FORWARDED_HOST = False
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",     # si front dev
    "http://127.0.0.1:3000",
]

# Sans Redis local (REDIS_URL absent) : les tâches Celery s'exécutent aussitôt, dans le processus.
# Le broker par défaut (hôte « redis ») est injoignable hors Docker et bloquait ~20 s à chaque
# changement de statut de réservation (serveur de développement et tests).
if not config('REDIS_URL', default=''):
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_BROKER_URL = 'memory://'
    CELERY_RESULT_BACKEND = 'cache+memory://'

# Développement et tests : couche de canaux EN MÉMOIRE (suivi en direct dans un seul processus daphne, sans Redis).
# CHANNELS_USE_REDIS=1 conserve la couche Redis de base.py (production : prod.py ne passe pas par ici).
if not config('CHANNELS_USE_REDIS', default=False, cast=bool):
    CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
