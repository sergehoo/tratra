# settings/prod.py
import os
import re

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

# Vérification faciale (KYC biométrique) : jamais activée sans clé de chiffrement des captures ; un fournisseur HTTP exige une URL HTTPS et une clé.
if BIOMETRIC_ENABLED:
    if not BIOMETRIC_ENCRYPTION_KEY:
        raise ImproperlyConfigured('BIOMETRIC_ENCRYPTION_KEY must be configured when BIOMETRIC_ENABLED=true in production.')
    if BIOMETRIC_PROVIDER not in ('none', 'http'):
        raise ImproperlyConfigured('BIOMETRIC_PROVIDER must be "none" or "http" in production.')
    if BIOMETRIC_PROVIDER == 'http' and not (BIOMETRIC_API_URL.lower().startswith('https://') and BIOMETRIC_API_KEY):
        raise ImproperlyConfigured('BIOMETRIC_PROVIDER=http requires an https BIOMETRIC_API_URL and a BIOMETRIC_API_KEY.')

# URL publique du site web : encodée dans les QR (Tratra ID, QR de mission, équipements). Sans elle, les QR pointeraient
# vers http://localhost:3000 (valeur par défaut de base.py) et seraient inutilisables.
_require_production_setting('PUBLIC_WEB_URL')
if not PUBLIC_WEB_URL.lower().startswith('https://'):
    raise ImproperlyConfigured('PUBLIC_WEB_URL must use HTTPS in production.')

# SMS (OTP) : en production, uniquement des fournisseurs RÉELS avec leurs identifiants — jamais le
# journal « console » ni la boîte « locmem » (voir handy/sms.py). `SMS_BACKEND` accepte une liste ordonnée
# (« twilio,orange ») : le suivant prend la relève quand le précédent échoue ; TOUS doivent être configurés.
SMS_PROVIDERS = []
for _item in re.split(r'[,;\s]+', config('SMS_BACKEND', default='').strip().lower()):
    if _item and _item not in SMS_PROVIDERS:
        SMS_PROVIDERS.append(_item)
SMS_BACKEND = ','.join(SMS_PROVIDERS)
_SMS_REQUIRED = {
    'twilio': ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN'),
    'orange': (),
    'africastalking': ('AT_USERNAME', 'AT_API_KEY'),
}
if not SMS_PROVIDERS or any(_provider not in _SMS_REQUIRED for _provider in SMS_PROVIDERS):
    raise ImproperlyConfigured('SMS_BACKEND must be "twilio", "orange" or "africastalking" in production '
                               '(or an ordered list such as "twilio,orange" for automatic failover).')
for _provider in SMS_PROVIDERS:
    for _name in _SMS_REQUIRED[_provider]:
        _require_production_setting(_name)
if 'twilio' in SMS_PROVIDERS and not any(config(n, default='').strip() for n in (
        'TWILIO_MESSAGING_SERVICE_SID', 'TWILIO_FROM', 'TWILIO_PHONE_NUMBER')):
    raise ImproperlyConfigured('TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM is required in production.')
if 'orange' in SMS_PROVIDERS and not (
        config('ORANGE_SMS_AUTHORIZATION_HEADER', default='').strip()
        or all(config(n, default='').strip() for n in ('ORANGE_SMS_CLIENT_ID', 'ORANGE_SMS_CLIENT_SECRET'))):
    raise ImproperlyConfigured('ORANGE_SMS_CLIENT_ID and ORANGE_SMS_CLIENT_SECRET '
                               '(or ORANGE_SMS_AUTHORIZATION_HEADER) are required in production.')
if 'orange' in SMS_PROVIDERS:
    # Même règle que handy.sms.orange_sender : vide = 2250000 ; un numéro illisible rendrait TOUTE la chaîne inutilisable (Twilio compris).
    _orange_sender = re.sub(r'\D', '', re.sub(r'^(?:tel(?::|%3A))?\s*(?:\+|%2B)?', '',
                                              config('ORANGE_SMS_SENDER', default='').strip() or '2250000', flags=re.I))
    if not re.fullmatch(r'\d{5,15}', _orange_sender):
        raise ImproperlyConfigured('ORANGE_SMS_SENDER must be the Orange country sender number (digits, e.g. 2250000).')

# Double authentification des comptes d'administration : OBLIGATOIRE en production (Back-Office, /admin/, droits « personnel » de
# l'ancienne API). La désactiver exige BACKOFFICE_MFA_REQUIRED=0 explicite ; `check --deploy` le signale alors par un avertissement.
BACKOFFICE_MFA_REQUIRED = env_bool('BACKOFFICE_MFA_REQUIRED', True)
# Personnel historique sans rôle : le passe-droit global de l'ancienne API est FERMÉ par défaut en production
# (attribuer d'abord les rôles : manage.py assign_legacy_staff_roles ; voir docs/securite-admin.md).
LEGACY_STAFF_BYPASS = env_bool('LEGACY_STAFF_BYPASS', False)

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
