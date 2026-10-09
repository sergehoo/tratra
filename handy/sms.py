"""Envoi de SMS (OTP, alertes) via un fournisseur configurable.

Choix du fournisseur : variable d'environnement (ou réglage Django) `SMS_BACKEND` :

- ``twilio``        : API REST Twilio (aucun SDK requis). `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`
                      et soit `TWILIO_MESSAGING_SERVICE_SID`, soit `TWILIO_FROM` (alias `TWILIO_PHONE_NUMBER`).
- ``africastalking``: API REST Africa's Talking. `AT_USERNAME`, `AT_API_KEY`, `AT_SENDER_ID`
                      (facultatif) ; `AT_SANDBOX=true` pour le bac à sable.
- ``console``       : journal local, DÉVELOPPEMENT UNIQUEMENT (aucun SMS réel). Refusé hors DEBUG.
- ``locmem``        : boîte d'envoi en mémoire (`sms.outbox`), TESTS uniquement. Refusé hors DEBUG.

Sans `SMS_BACKEND` : « console » en développement (DEBUG), sinon AUCUN envoi (SMSNotConfigured) —
il n'existe donc jamais d'OTP « fictif » en production, où `tratra/settings/prod.py` exige en plus
un fournisseur réel et ses identifiants au démarrage.

Les erreurs ne contiennent jamais le texte du message (il porte le code OTP) ni le numéro complet.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import List, Optional, Tuple

import requests
from decouple import config
from django.conf import settings

logger = logging.getLogger(__name__)

REAL_BACKENDS = ("twilio", "africastalking")
LOCAL_BACKENDS = ("console", "locmem")

# Boîte d'envoi du backend « locmem » : [(numéro, message)].
outbox: List[Tuple[str, str]] = []


class SMSError(Exception):
    """Échec d'envoi (fournisseur indisponible, numéro refusé…)."""


class SMSNotConfigured(SMSError):
    """Aucun fournisseur SMS exploitable dans cet environnement."""


def _setting(name: str, default: str = "") -> str:
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = config(name, default=default)
    return str(value).strip()


def backend_name() -> str:
    name = _setting("SMS_BACKEND").lower()
    if not name:
        name = "console" if settings.DEBUG else ""
    return name


def mask(msisdn: str) -> str:
    return f"{msisdn[:4]}••••{msisdn[-2:]}" if len(msisdn) > 7 else "••••"


def normalize_msisdn(raw: Optional[str]) -> str:
    """Numéro au format E.164 (+225…) ; lève SMSError si invalide.

    Un numéro national (sans indicatif) reçoit `SMS_DEFAULT_COUNTRY_CODE` (225 par défaut)."""
    value = re.sub(r"[\s.\-()]", "", raw or "")
    if value.startswith("00"):
        value = "+" + value[2:]
    if not value.startswith("+"):
        # 10 chiffres = numéro national (plan ivoirien : le 0 initial fait partie du numéro).
        value = "+" + (_setting("SMS_DEFAULT_COUNTRY_CODE", "225") if len(value) == 10 else "") + value
    if not re.fullmatch(r"\+[1-9]\d{7,14}", value):
        raise SMSError("Numéro de téléphone invalide.")
    return value


class ConsoleBackend:
    exposes_code = True  # dev : le code est aussi renvoyé par l'API (réglage DEBUG)

    def send(self, msisdn: str, message: str) -> None:
        logger.warning("SMS (console, dev) -> %s : %s", mask(msisdn), message)


class LocmemBackend:
    exposes_code = False

    def send(self, msisdn: str, message: str) -> None:
        outbox.append((msisdn, message))


class TwilioBackend:
    exposes_code = False

    def __init__(self):
        self.sid = _setting("TWILIO_ACCOUNT_SID")
        self.token = _setting("TWILIO_AUTH_TOKEN")
        self.service = _setting("TWILIO_MESSAGING_SERVICE_SID")
        self.sender = _setting("TWILIO_FROM") or _setting("TWILIO_PHONE_NUMBER")
        if not (self.sid and self.token and (self.service or self.sender)):
            raise SMSNotConfigured("Twilio : TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN et TWILIO_MESSAGING_SERVICE_SID "
                                   "(ou TWILIO_FROM / TWILIO_PHONE_NUMBER) sont requis.")

    def send(self, msisdn: str, message: str) -> None:
        data = {"To": msisdn, "Body": message}
        data["MessagingServiceSid" if self.service else "From"] = self.service or self.sender
        try:
            r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
                              data=data, auth=(self.sid, self.token), timeout=_timeout())
        except requests.RequestException as exc:
            raise SMSError(f"Twilio injoignable ({type(exc).__name__}).") from None
        if r.status_code >= 300:
            code = ""
            try:
                code = f" (code {r.json().get('code')})"
            except ValueError:
                pass
            if r.status_code in (401, 403):
                # Identifiants/compte refusés : défaut de configuration serveur, pas une erreur de l'utilisateur.
                raise SMSNotConfigured(f"Twilio a refusé les identifiants : HTTP {r.status_code}{code}.")
            raise SMSError(f"Twilio a refusé l'envoi : HTTP {r.status_code}{code}.")
        logger.info("SMS envoyé via Twilio -> %s", mask(msisdn))


class AfricasTalkingBackend:
    exposes_code = False

    def __init__(self):
        self.username = _setting("AT_USERNAME")
        self.api_key = _setting("AT_API_KEY")
        self.sender = _setting("AT_SENDER_ID")
        self.sandbox = _setting("AT_SANDBOX").lower() in ("1", "true", "yes")
        if not (self.username and self.api_key):
            raise SMSNotConfigured("Africa's Talking : AT_USERNAME et AT_API_KEY sont requis.")

    def send(self, msisdn: str, message: str) -> None:
        host = "api.sandbox.africastalking.com" if self.sandbox else "api.africastalking.com"
        data = {"username": self.username, "to": msisdn, "message": message}
        if self.sender:
            data["from"] = self.sender
        try:
            r = requests.post(f"https://{host}/version1/messaging", data=data, timeout=_timeout(),
                              headers={"apiKey": self.api_key, "Accept": "application/json"})
        except requests.RequestException as exc:
            raise SMSError(f"Africa's Talking injoignable ({type(exc).__name__}).") from None
        if r.status_code in (401, 403):
            raise SMSNotConfigured(f"Africa's Talking a refusé les identifiants : HTTP {r.status_code}.")
        if r.status_code >= 300:
            raise SMSError(f"Africa's Talking a refusé l'envoi : HTTP {r.status_code}.")
        try:
            recipients = r.json()["SMSMessageData"]["Recipients"]
            accepted = bool(recipients) and all(int(x.get("statusCode", 0)) in (100, 101, 102) for x in recipients)
        except (ValueError, KeyError, TypeError):
            accepted = False
        if not accepted:
            raise SMSError("Africa's Talking n'a pas accepté le message.")
        logger.info("SMS envoyé via Africa's Talking -> %s", mask(msisdn))


def _is_test_run() -> bool:
    return "pytest" in sys.modules or "test" in sys.argv[:2]


def _timeout() -> int:
    try:
        return max(1, int(_setting("SMS_TIMEOUT", "10")))
    except ValueError:
        return 10


def get_backend():
    """Fournisseur actif. Lève SMSNotConfigured s'il n'y en a aucun d'utilisable ici."""
    name = backend_name()
    if name in LOCAL_BACKENDS:
        if not (settings.DEBUG or _is_test_run()):
            raise SMSNotConfigured(f"Le fournisseur SMS « {name} » est réservé au développement et aux tests.")
        return ConsoleBackend() if name == "console" else LocmemBackend()
    if name == "twilio":
        return TwilioBackend()
    if name == "africastalking":
        return AfricasTalkingBackend()
    raise SMSNotConfigured("Aucun fournisseur SMS configuré (SMS_BACKEND).")


def send_sms(msisdn: Optional[str], message: str):
    """Envoie un SMS ; lève SMSError (ou SMSNotConfigured) en cas d'échec. Renvoie le backend utilisé."""
    number = normalize_msisdn(msisdn)
    backend = get_backend()
    backend.send(number, message)
    return backend
