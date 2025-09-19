# settings/prod.py
import os
from .base import *

DEBUG = True
SECURE_SSL_REDIRECT = False
# pour le retour en HTTPS strict
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CSRF_TRUSTED_ORIGINS = [
    "http://www.tratra.net",
    "https://media.tratra.net",
    "http://media.tratra.net",
    "http://tratra.net",
    "https://tratra.net",
]
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT'),
    }
}
