# settings/prod.py
import os

from decouple import config
from django.core.exceptions import ImproperlyConfigured

from .base import *


def _production_list(name):
    return [item.strip() for item in config(name, default='').split(',') if item.strip()]


def _require_production_setting(name):
    value = config(name, default='').strip()
    if not value:
        raise ImproperlyConfigured(f'{name} must be explicitly configured in production.')
    return value

# SECURITY: jamais de debug en production.
DEBUG = False

if SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('A non-development SECRET_KEY is required in production.')

ALLOWED_HOSTS = _production_list('ALLOWED_HOSTS')
if not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('ALLOWED_HOSTS must explicitly list production hosts and cannot contain *.')

# Production requires an external private object store.  This avoids silently
# persisting identity documents in an ephemeral container volume.
if not MINIO_ENABLED:
    raise ImproperlyConfigured('MINIO_ENABLED=true is required in production.')

_configured_kyc_bucket = _require_production_setting('KYC_STORAGE_BUCKET_NAME')
if _configured_kyc_bucket == AWS_STORAGE_BUCKET_NAME:
    raise ImproperlyConfigured('KYC_STORAGE_BUCKET_NAME must be distinct from AWS_STORAGE_BUCKET_NAME.')
if not AWS_S3_ENDPOINT_URL.lower().startswith('https://'):
    raise ImproperlyConfigured('AWS_S3_ENDPOINT_URL must use HTTPS in production.')
if not AWS_S3_VERIFY:
    raise ImproperlyConfigured('AWS_S3_VERIFY must remain enabled in production.')

# SMS (OTP) : en production, uniquement un fournisseur RÉEL avec ses identifiants — jamais le
# journal « console » ni la boîte « locmem » (voir handy/sms.py).
SMS_BACKEND = config('SMS_BACKEND', default='').strip().lower()
_SMS_REQUIRED = {
    'twilio': ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN'),
    'africastalking': ('AT_USERNAME', 'AT_API_KEY'),
}
if SMS_BACKEND not in _SMS_REQUIRED:
    raise ImproperlyConfigured('SMS_BACKEND must be "twilio" or "africastalking" in production.')
for _name in _SMS_REQUIRED[SMS_BACKEND]:
    _require_production_setting(_name)
if SMS_BACKEND == 'twilio' and not any(config(n, default='').strip() for n in (
        'TWILIO_MESSAGING_SERVICE_SID', 'TWILIO_FROM', 'TWILIO_PHONE_NUMBER')):
    raise ImproperlyConfigured('TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM is required in production.')

# Derrière Traefik (terminaison TLS) : on force HTTPS et on fait confiance à
# l'en-tête de proto transmis par le reverse proxy.
SECURE_SSL_REDIRECT = True
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Durcissement cookies / transport
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

CSRF_TRUSTED_ORIGINS = _production_list('CSRF_TRUSTED_ORIGINS')
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = _production_list('CORS_ALLOWED_ORIGINS')

# The interactive schema may contain operational details and is not a public
# production endpoint.  API access remains controlled by its own permissions.
SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,
    'SERVE_PERMISSIONS': ['rest_framework.permissions.IsAdminUser'],
}
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
