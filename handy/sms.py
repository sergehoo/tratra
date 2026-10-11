"""Envoi de SMS (OTP, alertes) via un ou plusieurs fournisseurs configurables, avec relève automatique.

Choix du fournisseur : variable d'environnement (ou réglage Django) `SMS_BACKEND` :

- ``twilio``        : API REST Twilio (aucun SDK requis). `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`
                      et soit `TWILIO_MESSAGING_SERVICE_SID`, soit `TWILIO_FROM` (alias `TWILIO_PHONE_NUMBER`).
- ``orange``        : API SMS d'Orange (OAuth2). `ORANGE_SMS_CLIENT_ID` + `ORANGE_SMS_CLIENT_SECRET` (ou
                      `ORANGE_SMS_AUTHORIZATION_HEADER` fourni par le portail Orange), `ORANGE_SMS_SENDER`
                      (« numéro d'expéditeur » du pays, défaut 2250000 pour la Côte d'Ivoire), `ORANGE_SMS_SENDER_NAME`
                      (nom d'expéditeur validé par Orange, facultatif), `ORANGE_SMS_RESOURCE_TYPE` (facultatif).
- ``africastalking``: API REST Africa's Talking. `AT_USERNAME`, `AT_API_KEY`, `AT_SENDER_ID`
                      (facultatif) ; `AT_SANDBOX=true` pour le bac à sable.
- ``console``       : journal local, DÉVELOPPEMENT UNIQUEMENT (aucun SMS réel). Refusé hors DEBUG.
- ``locmem``        : boîte d'envoi en mémoire (`sms.outbox`), TESTS uniquement. Refusé hors DEBUG.

**Relève automatique** : `SMS_BACKEND` accepte une liste ordonnée, ex. ``twilio,orange``. Le premier fournisseur
est essayé d'abord ; s'il échoue (injoignable, erreur 5xx, quota, identifiants ou contrat refusés, message refusé), le
suivant envoie le même SMS, et ainsi de suite. Un fournisseur en panne est mis de côté `SMS_FAILOVER_COOLDOWN` secondes
(60 par défaut, 0 = jamais) : les envois suivants passent directement au suivant au lieu d'attendre son délai d'attente.
Un fournisseur qui a peut-être envoyé malgré un délai dépassé peut provoquer un doublon : le même code arrive deux fois.
Tous les fournisseurs listés doivent être configurés (sinon refus au démarrage en production) ; `console` et `locmem`
ne se combinent avec aucun autre.

Sans `SMS_BACKEND` : « console » en développement (DEBUG), sinon AUCUN envoi (SMSNotConfigured) —
il n'existe donc jamais d'OTP « fictif » en production, où `tratra/settings/prod.py` exige en plus
un fournisseur réel et ses identifiants au démarrage.

Les erreurs ne contiennent jamais le texte du message (il porte le code OTP) ni le numéro complet.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import sys
from typing import List, Optional, Tuple

import requests
from decouple import config
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

REAL_BACKENDS = ("twilio", "orange", "africastalking")
LOCAL_BACKENDS = ("console", "locmem")

# Boîte d'envoi du backend « locmem » : [(numéro, message)].
outbox: List[Tuple[str, str]] = []


class SMSError(Exception):
    """Échec d'envoi (fournisseur indisponible, numéro refusé…)."""


class SMSNotConfigured(SMSError):
    """Aucun fournisseur SMS exploitable dans cet environnement."""


class SMSProviderUnavailable(SMSError):
    """Le fournisseur lui-même est en cause (injoignable, erreur serveur, quota) — pas ce numéro ni ce message."""


def _setting(name: str, default: str = "") -> str:
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = config(name, default=default)
    return str(value).strip()


def backend_names() -> List[str]:
    """Fournisseurs configurés, dans l'ordre d'essai (`SMS_BACKEND=twilio,orange`) ; sans doublon."""
    raw = _setting("SMS_BACKEND").lower()
    names: List[str] = []
    for item in re.split(r"[,;\s]+", raw):
        if item and item not in names:
            names.append(item)
    if not names and settings.DEBUG:
        names = ["console"]
    return names


def backend_name() -> str:
    """Fournisseur(s) configuré(s) sous forme de texte : « twilio » ou « twilio,orange »."""
    return ",".join(backend_names())


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
            raise SMSProviderUnavailable(f"Twilio injoignable ({type(exc).__name__}).") from None
        if r.status_code >= 300:
            code = ""
            try:
                code = f" (code {r.json().get('code')})"
            except (ValueError, AttributeError):  # corps non JSON, ou JSON qui n'est pas un objet
                pass
            if r.status_code in (401, 403):
                # Identifiants/compte refusés : défaut de configuration serveur, pas une erreur de l'utilisateur.
                raise SMSNotConfigured(f"Twilio a refusé les identifiants : HTTP {r.status_code}{code}.")
            if r.status_code == 429 or r.status_code >= 500:
                raise SMSProviderUnavailable(f"Twilio indisponible : HTTP {r.status_code}{code}.")
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
            raise SMSProviderUnavailable(f"Africa's Talking injoignable ({type(exc).__name__}).") from None
        if r.status_code in (401, 403):
            raise SMSNotConfigured(f"Africa's Talking a refusé les identifiants : HTTP {r.status_code}.")
        if r.status_code == 429 or r.status_code >= 500:
            raise SMSProviderUnavailable(f"Africa's Talking indisponible : HTTP {r.status_code}.")
        if r.status_code >= 300:
            raise SMSError(f"Africa's Talking a refusé l'envoi : HTTP {r.status_code}.")
        try:
            recipients = r.json()["SMSMessageData"]["Recipients"]
            accepted = bool(recipients) and all(int(x.get("statusCode", 0)) in (100, 101, 102) for x in recipients)
        except (ValueError, KeyError, TypeError, AttributeError):
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


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:  # noqa: BLE001 - le cache ne doit jamais empêcher un envoi
        return None


def _cache_set(key: str, value, ttl: int) -> None:
    try:
        cache.set(key, value, ttl)
    except Exception:  # noqa: BLE001
        pass


def _cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:  # noqa: BLE001
        pass


def orange_sender(raw: str) -> str:
    """Numéro d'expéditeur Orange, en chiffres : vide = 2250000 (Côte d'Ivoire) ; accepte « +225 0000 », « tel:+2250000 »
    et la forme encodée de la documentation « tel%3A%2B2250000 ». (Même règle dans tratra/settings/prod.py et scripts/check_env.py.)"""
    value = re.sub(r"^(?:tel(?::|%3A))?\s*(?:\+|%2B)?", "", (raw or "").strip() or "2250000", flags=re.I)
    return re.sub(r"\D", "", value)


class OrangeBackend:
    """API SMS d'Orange : jeton OAuth2 (`client_credentials`, valable 1 h, mis en cache) puis
    `POST /smsmessaging/v1/outbound/tel:+<expéditeur>/requests` (réponse 201)."""

    exposes_code = False
    API = "https://api.orange.com"

    def __init__(self):
        header = _setting("ORANGE_SMS_AUTHORIZATION_HEADER")
        client_id, client_secret = _setting("ORANGE_SMS_CLIENT_ID"), _setting("ORANGE_SMS_CLIENT_SECRET")
        if header:
            self._authorization = header if header.lower().startswith("basic ") else f"Basic {header}"
        elif client_id and client_secret:
            self._authorization = "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        else:
            raise SMSNotConfigured("Orange : ORANGE_SMS_CLIENT_ID et ORANGE_SMS_CLIENT_SECRET "
                                   "(ou ORANGE_SMS_AUTHORIZATION_HEADER) sont requis.")
        self.sender = orange_sender(_setting("ORANGE_SMS_SENDER"))
        if not re.fullmatch(r"\d{5,15}", self.sender):
            raise SMSNotConfigured("Orange : ORANGE_SMS_SENDER doit contenir le numéro d'expéditeur du pays (ex. 2250000).")
        self.sender_name = _setting("ORANGE_SMS_SENDER_NAME")
        self.resource_type = _setting("ORANGE_SMS_RESOURCE_TYPE")
        # Le jeton est propre à ces identifiants : la rotation des secrets n'en réutilise jamais un ancien.
        self._token_key = "sms:orange:token:" + hashlib.sha256(self._authorization.encode()).hexdigest()[:16]

    def _token(self, force: bool = False) -> str:
        if not force:
            cached = _cache_get(self._token_key)
            if cached:
                return cached
        try:
            r = requests.post(f"{self.API}/oauth/v3/token", data={"grant_type": "client_credentials"},
                              headers={"Authorization": self._authorization, "Accept": "application/json"},
                              timeout=_timeout())
        except requests.RequestException as exc:
            raise SMSProviderUnavailable(f"Orange (jeton) injoignable ({type(exc).__name__}).") from None
        if r.status_code in (400, 401, 403):
            raise SMSNotConfigured(f"Orange a refusé les identifiants : HTTP {r.status_code}.")
        if r.status_code == 429 or r.status_code >= 500:
            raise SMSProviderUnavailable(f"Orange (jeton) indisponible : HTTP {r.status_code}.")
        if r.status_code >= 300:
            raise SMSError(f"Orange a refusé la demande de jeton : HTTP {r.status_code}.")
        try:
            body = r.json()
            token = str(body["access_token"])
            ttl = int(body.get("expires_in", 3600))
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            raise SMSProviderUnavailable("Orange : réponse de jeton illisible.") from None
        _cache_set(self._token_key, token, max(30, ttl - 120))
        return token

    @staticmethod
    def _error_code(response) -> str:
        """Code d'erreur Orange (ex. SVC0002, POL1009) — jamais le texte, qui peut reprendre le numéro ou le message."""
        try:
            error = response.json().get("requestError", {})
            for kind in ("serviceException", "policyException"):
                code = str((error.get(kind) or {}).get("messageId", ""))
                if re.fullmatch(r"[A-Z]{3}\d{4}", code):
                    return f" (code {code})"
        except (ValueError, AttributeError):
            pass
        return ""

    def send(self, msisdn: str, message: str) -> None:
        url = f"{self.API}/smsmessaging/v1/outbound/tel%3A%2B{self.sender}/requests"
        params = {"resource_type_parameter_management": self.resource_type} if self.resource_type else None
        request = {"address": f"tel:{msisdn}", "senderAddress": f"tel:+{self.sender}",
                   "outboundSMSTextMessage": {"message": message}}
        if self.sender_name:
            request["senderName"] = self.sender_name
        body = {"outboundSMSMessageRequest": request}
        for attempt in (1, 2):
            token = self._token(force=attempt == 2)
            try:
                r = requests.post(url, json=body, params=params, timeout=_timeout(),
                                  headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
            except requests.RequestException as exc:
                raise SMSProviderUnavailable(f"Orange injoignable ({type(exc).__name__}).") from None
            if r.status_code == 401 and attempt == 1:
                _cache_delete(self._token_key)  # jeton expiré ou révoqué : un seul renouvellement, puis on réessaie
                continue
            break
        code = self._error_code(r) if r.status_code >= 300 else ""
        if r.status_code in (401, 403):
            raise SMSNotConfigured(f"Orange a refusé la requête (identifiants, contrat ou solde) : HTTP {r.status_code}{code}.")
        if r.status_code == 429 or r.status_code >= 500:
            raise SMSProviderUnavailable(f"Orange indisponible : HTTP {r.status_code}{code}.")
        if r.status_code >= 300:
            raise SMSError(f"Orange a refusé l'envoi : HTTP {r.status_code}{code}.")
        logger.info("SMS envoyé via Orange -> %s", mask(msisdn))


def _failover_cooldown() -> int:
    try:
        return max(0, int(_setting("SMS_FAILOVER_COOLDOWN", "60")))
    except ValueError:
        return 60


class FailoverBackend:
    """Essaie les fournisseurs dans l'ordre configuré ; le suivant prend la relève dès qu'un échec survient.

    Un fournisseur en cause lui-même (injoignable, 5xx, quota, identifiants refusés) est mis de côté quelques secondes :
    les envois suivants le tentent en dernier au lieu d'attendre son délai d'attente à chaque fois."""

    exposes_code = False

    def __init__(self, providers: List[Tuple[str, object]]):
        self.providers = providers

    @staticmethod
    def _down_key(name: str) -> str:
        return f"sms:down:{name}"

    def _ordered(self) -> List[Tuple[str, object]]:
        healthy = [p for p in self.providers if not _cache_get(self._down_key(p[0]))]
        sidelined = [p for p in self.providers if p not in healthy]
        return healthy + sidelined  # jamais d'impasse : les fournisseurs écartés restent le dernier recours

    def send(self, msisdn: str, message: str):
        failures: List[Tuple[str, SMSError]] = []
        for name, backend in self._ordered():
            try:
                backend.send(msisdn, message)
            except Exception as exc:  # noqa: BLE001 - un fournisseur qui plante ne doit jamais empêcher la relève
                if not isinstance(exc, SMSError):
                    # Le texte de l'exception peut contenir une URL ou un identifiant : seul son TYPE est conservé.
                    exc = SMSProviderUnavailable(f"erreur inattendue ({type(exc).__name__}).")
                failures.append((name, exc))
                cooldown = _failover_cooldown()
                if cooldown and isinstance(exc, (SMSNotConfigured, SMSProviderUnavailable)):
                    _cache_set(self._down_key(name), 1, cooldown)
                logger.warning("SMS : %s a échoué (%s), relève par le fournisseur suivant.", name, type(exc).__name__)
                continue
            if failures:
                logger.warning("SMS livré via %s après l'échec de : %s.", name, ", ".join(n for n, _ in failures))
            return backend
        detail = " | ".join(f"{name} : {exc}" for name, exc in failures)
        if all(isinstance(exc, SMSNotConfigured) for _, exc in failures):
            raise SMSNotConfigured(f"Tous les fournisseurs SMS ont refusé la configuration. {detail}")
        raise SMSError(f"Tous les fournisseurs SMS ont échoué. {detail}")


_FACTORIES = {"twilio": TwilioBackend, "orange": OrangeBackend, "africastalking": AfricasTalkingBackend}


def get_backend():
    """Fournisseur actif (ou chaîne de relève). Lève SMSNotConfigured s'il n'y en a aucun d'utilisable ici."""
    names = backend_names()
    if not names:
        raise SMSNotConfigured("Aucun fournisseur SMS configuré (SMS_BACKEND).")
    local = [n for n in names if n in LOCAL_BACKENDS]
    if local:
        if len(names) > 1:
            raise SMSNotConfigured(f"Le fournisseur SMS « {local[0]} » ne se combine avec aucun autre.")
        if not (settings.DEBUG or _is_test_run()):
            raise SMSNotConfigured(f"Le fournisseur SMS « {names[0]} » est réservé au développement et aux tests.")
        return ConsoleBackend() if names[0] == "console" else LocmemBackend()
    unknown = [n for n in names if n not in _FACTORIES]
    if unknown:
        raise SMSNotConfigured(f"Fournisseur SMS inconnu : « {unknown[0]} » (attendus : {', '.join(REAL_BACKENDS)}).")
    providers = [(n, _FACTORIES[n]()) for n in names]
    return providers[0][1] if len(providers) == 1 else FailoverBackend(providers)


def send_sms(msisdn: Optional[str], message: str):
    """Envoie un SMS ; lève SMSError (ou SMSNotConfigured) en cas d'échec. Renvoie le fournisseur qui a livré."""
    number = normalize_msisdn(msisdn)
    backend = get_backend()
    try:
        delivered_by = backend.send(number, message)
    except SMSError:
        raise
    except Exception as exc:  # noqa: BLE001 - 502 propre (et code OTP invalidé) plutôt qu'un 500 qui laisserait le code valide
        logger.error("SMS : erreur inattendue d'un fournisseur (%s).", type(exc).__name__)
        raise SMSProviderUnavailable(f"Erreur inattendue du fournisseur SMS ({type(exc).__name__}).") from None
    return delivered_by if delivered_by is not None else backend
