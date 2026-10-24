"""Réglages des TESTS DE CHARGE (DJANGO_ENV=loadtest) : jamais la production, jamais un vrai SMS ni un vrai push.

Base dédiée et jetable (`LOADTEST_DB_NAME`, nom commençant obligatoirement par « tratra_loadtest »), DEBUG coupé (comme en production :
DEBUG garde chaque requête SQL en mémoire et fausserait les mesures), SMS et push neutralisés à la source, anti-robot et limites de débit
relevés (on mesure la capacité, pas les protections). Mode d'emploi : docs/scalabilite-30m.md."""
import os

from django.core.exceptions import ImproperlyConfigured

from .dev import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '[::1]']

LOADTEST_DB_NAME = os.getenv('LOADTEST_DB_NAME', 'tratra_loadtest')
if not LOADTEST_DB_NAME.startswith('tratra_loadtest'):
    raise ImproperlyConfigured('LOADTEST_DB_NAME doit commencer par « tratra_loadtest » (base jetable dédiée aux mesures).')
DATABASES['default']['NAME'] = LOADTEST_DB_NAME  # noqa: F405
DATABASES['default']['CONN_MAX_AGE'] = int(os.getenv('LOADTEST_CONN_MAX_AGE', '0'))  # noqa: F405
DATABASES['default']['TEST'] = {'NAME': 'test_' + LOADTEST_DB_NAME}  # noqa: F405

# Aucun SMS, aucun push : interrupteur général, fournisseurs et identifiants vidés (même si le .env local en contient).
SMS_ENABLED = False
SMS_OTP_SIGNUP_ENABLED = SMS_RECOVERY_ENABLED = SMS_ALERTS_ENABLED = False
SMS_BACKEND = ''
for _name in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER', 'TWILIO_MESSAGING_SERVICE_SID', 'TWILIO_FROM',
              'AT_USERNAME', 'AT_API_KEY', 'ORANGE_CLIENT_ID', 'ORANGE_CLIENT_SECRET'):
    globals()[_name] = ''
FCM_CREDENTIALS_FILE = FCM_CREDENTIALS_JSON = FCM_PROJECT_ID = ''
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
ADMINS = []
SENTRY_DSN = ''
TURNSTILE_SECRET_KEY = ''

# Limites de débit relevées : un test de charge depuis une seule adresse serait sinon refusé en quelques secondes.
REST_FRAMEWORK = {**REST_FRAMEWORK, 'DEFAULT_THROTTLE_RATES': {k: '1000000/min' for k in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']}}  # noqa: F405
AXES_ENABLED = False

# Redis DÉDIÉ aux mesures (jamais celui d'un autre projet) : cache, broker Celery et couche Channels. Sans lui : cache local et
# tâches gardées en mémoire (non exécutées : on mesure le chemin de la requête, comme en production où le push est asynchrone).
LOADTEST_REDIS_URL = os.getenv('LOADTEST_REDIS_URL', '')
if LOADTEST_REDIS_URL:
    from urllib.parse import urlsplit as _split

    _r = _split(LOADTEST_REDIS_URL)
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': f'{_r.scheme}://{_r.netloc}/1',
                          'KEY_PREFIX': 'tratra', 'OPTIONS': {'socket_connect_timeout': 2, 'socket_timeout': 2}}}
    CELERY_BROKER_URL = CELERY_RESULT_BACKEND = f'{_r.scheme}://{_r.netloc}/0'
    CELERY_TASK_ALWAYS_EAGER = False
    CHANNEL_LAYERS = {'default': {'BACKEND': 'channels_redis.core.RedisChannelLayer',
                                  'CONFIG': {'hosts': [f'{_r.scheme}://{_r.netloc}/2']}}}
else:
    CELERY_TASK_ALWAYS_EAGER = False
    CELERY_BROKER_URL = 'memory://'
    CELERY_RESULT_BACKEND = 'cache+memory://'

INSTALLED_APPS = [*INSTALLED_APPS, 'loadtest']  # noqa: F405
LOGGING = {'version': 1, 'disable_existing_loggers': False,
           'handlers': {'console': {'class': 'logging.StreamHandler'}},
           'root': {'handlers': ['console'], 'level': os.getenv('LOADTEST_LOG_LEVEL', 'ERROR')}}
