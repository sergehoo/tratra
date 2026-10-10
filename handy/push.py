"""Push mobile via Firebase Cloud Messaging (API HTTP v1) — sans dépendance supplémentaire (PyJWT + requests).

Configuration (aucun identifiant n'est versionné) :
  FCM_CREDENTIALS_FILE  chemin du JSON de compte de service Firebase (ou FCM_CREDENTIALS_JSON : son contenu)
  FCM_PROJECT_ID        facultatif : sinon `project_id` du JSON
Sans configuration : aucun envoi, aucune erreur — la notification in-app reste la source fiable.

Les appareils sont ceux que l'application enregistre via POST /devices/ (`handy.Device`) ; un jeton refusé par FCM
(désinstallation, jeton périmé) est supprimé."""
import json
import logging
import threading
import time
from typing import Dict, Optional

import jwt
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TIMEOUT = 5
_lock = threading.Lock()
_token: Dict[str, object] = {"value": None, "exp": 0.0}


def _credentials() -> Optional[Dict]:
    raw = getattr(settings, "FCM_CREDENTIALS_JSON", "") or ""
    path = getattr(settings, "FCM_CREDENTIALS_FILE", "") or ""
    try:
        if raw:
            data = json.loads(raw)
        elif path:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        else:
            return None
    except (OSError, ValueError):
        logger.error("Identifiants FCM illisibles : push désactivé.")
        return None
    return data if data.get("private_key") and data.get("client_email") else None


def project_id() -> str:
    creds = _credentials() or {}
    return getattr(settings, "FCM_PROJECT_ID", "") or creds.get("project_id", "")


def is_configured() -> bool:
    return _credentials() is not None and bool(project_id())


def reset_cache() -> None:
    with _lock:
        _token.update(value=None, exp=0.0)


def _access_token(force: bool = False) -> Optional[str]:
    """Jeton OAuth2 (grant « jwt-bearer » du compte de service), mis en cache jusqu'à son expiration."""
    with _lock:
        if not force and _token["value"] and float(_token["exp"]) - 60 > time.time():
            return str(_token["value"])
        creds = _credentials()
        if creds is None:
            return None
        now = int(time.time())
        token_uri = creds.get("token_uri") or "https://oauth2.googleapis.com/token"
        assertion = jwt.encode({"iss": creds["client_email"], "scope": SCOPE, "aud": token_uri, "iat": now, "exp": now + 3600},
                               creds["private_key"], algorithm="RS256")
        try:
            r = requests.post(token_uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
                              timeout=TIMEOUT)
            r.raise_for_status()
            body = r.json()
            _token.update(value=body["access_token"], exp=time.time() + int(body.get("expires_in", 3600)))
            return str(_token["value"])
        except Exception:
            logger.warning("Jeton OAuth FCM indisponible.", exc_info=True)
            return None


def _stringify(data: Optional[Dict]) -> Dict[str, str]:
    return {str(k): str(v) for k, v in (data or {}).items()}  # FCM exige des valeurs textuelles


def send_to_user(user_id: int, title: str, body: str, data: Optional[Dict] = None) -> Dict:
    """Envoie la notification aux appareils mobiles du compte. Ne lève jamais d'exception."""
    result = {"sent": 0, "removed": 0, "skipped": None}
    try:
        if not is_configured():
            result["skipped"] = "not_configured"
            return result
        from handy.models import Device

        devices = list(Device.objects.filter(user_id=user_id, device_type__in=("android", "ios")))
        if not devices:
            result["skipped"] = "no_device"
            return result
        token = _access_token()
        if token is None:
            result["skipped"] = "no_access_token"
            return result
        url = f"https://fcm.googleapis.com/v1/projects/{project_id()}/messages:send"
        for device in devices:
            message = {"message": {"token": device.device_token, "notification": {"title": title, "body": body},
                                   "data": _stringify(data), "android": {"priority": "high"},
                                   "apns": {"headers": {"apns-priority": "10"}}}}
            r = requests.post(url, json=message, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
            if r.status_code == 401:  # jeton expiré côté Google : un seul nouvel essai
                token = _access_token(force=True) or token
                r = requests.post(url, json=message, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
            if r.status_code == 200:
                result["sent"] += 1
            elif r.status_code in (400, 404) and _is_dead_token(r):
                device.delete()
                result["removed"] += 1
            else:
                logger.warning("FCM : refus %s pour l'appareil #%s", r.status_code, device.pk)
    except Exception:
        logger.warning("Push FCM non envoyé.", exc_info=True)
    return result


def _is_dead_token(response) -> bool:
    try:
        text = json.dumps(response.json())
    except ValueError:
        text = response.text or ""
    return "UNREGISTERED" in text or "INVALID_ARGUMENT" in text or "NOT_FOUND" in text
