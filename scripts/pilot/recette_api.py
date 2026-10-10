#!/usr/bin/env python3
"""Recette du PILOTE par l'API HTTP : client → réservation → artisan → mission → messages → paiement en espèces → avis,
puis contrat de longue durée (besoin → candidature → contrat → échéance → paiement déclaré puis confirmé).

Bibliothèque standard uniquement (aucune installation). Le MÊME scénario tourne dans la suite de tests (`handy/test_recette_pilote.py`,
sans réseau) et contre une vraie pile (locale, rehearsal Docker ou staging) :

    RECETTE_CLIENT=<identifiant ou +225…>  RECETTE_ARTISAN=<…>  RECETTE_PASSWORD=<mot de passe>  \\
    python3 scripts/pilot/recette_api.py --api https://api-staging.exemple.ci/handy [--only booking|contract]

Les comptes doivent EXISTER (inscription + OTP + KYC approuvé = étapes humaines, voir docs/recette-pilote.md) ; l'artisan doit avoir un service
publié. Aucun mot de passe n'est affiché ni journalisé. La recette laisse des données de test (réservations, contrat) : utiliser des comptes de
recette dédiés, jamais de vrais clients. Code de sortie 0 si tout est vert, 1 au premier écart (avec l'étape et la réponse du serveur).
"""
import argparse
import base64
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

# PNG 1×1 : justificatif minimal valide (le serveur le réencode).
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
WEEK = [{"weekday": d, "start": "08:00", "end": "12:00"} for d in range(0, 5)]


class Resp:
    def __init__(self, status: int, data: Any, headers: Optional[Dict[str, str]] = None, raw: bytes = b""):
        self.status, self.data, self.headers, self.raw = status, data, {k.lower(): v for k, v in (headers or {}).items()}, raw

    def __repr__(self):
        return f"<{self.status} {json.dumps(self.data, ensure_ascii=False, default=str)[:300]}>"


class RecetteFailure(AssertionError):
    pass


class HttpTransport:
    """Transport HTTP réel (urllib). `base` = racine de l'API, ex. https://api.exemple.ci/handy."""

    def __init__(self, base: str, timeout: int = 30):
        self.base, self.timeout = base.rstrip("/"), timeout

    def request(self, method: str, path: str, *, json_body=None, fields: Optional[Dict[str, str]] = None, files: Optional[Dict[str, Tuple[str, bytes, str]]] = None,
                headers: Optional[Dict[str, str]] = None, token: Optional[str] = None) -> Resp:
        h = {"Accept": "application/json", **(headers or {})}
        body = None
        if token:
            h["Authorization"] = f"Bearer {token}"
        if files is not None:
            boundary = uuid.uuid4().hex
            parts = []
            for k, v in (fields or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
            for k, (name, content, ctype) in (files or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + content + b"\r\n")
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)
            h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif json_body is not None:
            body = json.dumps(json_body).encode()
            h["Content-Type"] = "application/json"
        url = path if path.startswith("http") else f"{self.base}{path}"
        req = urlrequest.Request(url, data=body, method=method, headers=h)
        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as r:
                raw, status, hdrs = r.read(), r.status, dict(r.headers)
        except urlerror.HTTPError as exc:
            raw, status, hdrs = exc.read(), exc.code, dict(exc.headers)
        try:
            data = json.loads(raw.decode("utf-8")) if raw and "json" in hdrs.get("Content-Type", hdrs.get("content-type", "")) else None
        except ValueError:
            data = None
        return Resp(status, data, hdrs, raw)


class Recette:
    def __init__(self, transport, client: Tuple[str, str], artisan: Tuple[str, str], *, tick: Optional[Callable[[], None]] = None,
                 log: Callable[[str], None] = print, today: Optional[date] = None):
        self.t, self.creds, self.tick, self.log = transport, {"client": client, "artisan": artisan}, tick, log
        self.today = today or date.today()
        self.tokens: Dict[str, str] = {}
        self.results: List[Tuple[str, bool, str]] = []
        self.state: Dict[str, Any] = {}

    # ── Outils ──────────────────────────────────────────────────────────────────────────────────────────────────────
    def call(self, who: Optional[str], method: str, path: str, **kw) -> Resp:
        return self.t.request(method, path, token=self.tokens.get(who) if who else None, **kw)

    def check(self, label: str, ok: bool, resp: Any = None) -> None:
        self.results.append((label, bool(ok), "" if ok else repr(resp)))
        self.log(f"  [{'ok' if ok else 'ÉCHEC'}] {label}" + ("" if ok else f"\n        réponse : {resp!r}"))
        if not ok:
            raise RecetteFailure(label)

    def section(self, title: str) -> None:
        self.log(f"\n== {title}")

    @staticmethod
    def items(resp: Resp) -> list:
        d = resp.data
        return d.get("results", []) if isinstance(d, dict) else (d or [])

    def notified(self, who: str, ntype: str, booking: Optional[int] = None) -> bool:
        r = self.call(who, "GET", f"/notifications/?type={ntype}")
        return r.status == 200 and any(n.get("notification_type") == ntype and (booking is None or (n.get("data") or {}).get("id") == booking) for n in self.items(r))

    # ── Scénario ────────────────────────────────────────────────────────────────────────────────────────────────────
    def run(self, only: str = "all") -> List[Tuple[str, bool, str]]:
        self.login()
        if only in ("all", "booking"):
            self.booking_journey()
        if only in ("all", "contract"):
            self.contract_journey()
        self.log(f"\nRecette terminée : {sum(1 for _, ok, _ in self.results if ok)}/{len(self.results)} contrôles verts.")
        return self.results

    def login(self) -> None:
        self.section("Connexion des comptes de recette")
        for who, (ident, pw) in self.creds.items():
            r = self.t.request("POST", "/auth/login/", json_body={"username": ident, "password": pw})
            self.check(f"connexion {who}", r.status == 200 and isinstance(r.data, dict) and r.data.get("access"), Resp(r.status, {k: v for k, v in (r.data or {}).items() if k != "access" and k != "refresh"}))
            self.tokens[who] = r.data["access"]
            me = self.call(who, "GET", "/users/me/")
            self.check(f"profil {who} lisible", me.status == 200 and me.data.get("id"), me)
            self.state[f"{who}_id"] = me.data["id"]

    def booking_journey(self) -> None:
        self.section("Réservation : client → artisan → mission")
        r = self.call("artisan", "GET", "/me/services/")
        services = [s for s in self.items(r) if s.get("published")]
        self.check("l'artisan a un service PUBLIÉ", r.status == 200 and services, r)
        svc = services[0]
        detail = self.call("client", "GET", f"/services/{svc['id']}/")
        self.check("le client voit le service dans le catalogue", detail.status == 200 and detail.data.get("id") == svc["id"], detail)
        category = detail.data.get("category") if isinstance(detail.data.get("category"), int) else (detail.data.get("category_detail") or {}).get("id")
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        price = str(svc.get("price") or "7000").split(".")[0]
        body = {"handyman": self.state["artisan_id"], "service": svc["id"], "booking_date": start.isoformat(), "end_date": (start + timedelta(hours=1)).isoformat(),
                "address": "Recette — Cocody", "city": "Abidjan", "postal_code": "00225", "description": "Réservation de recette (à ignorer).",
                "proposed_price": price, "type": "scheduled", "minutes": 60, "category_id": category}
        r = self.call("client", "POST", "/bookings/", json_body=body, headers={"Idempotency-Key": f"recette-{uuid.uuid4().hex[:12]}"})
        self.check("le client crée la réservation (statut « en attente »)", r.status == 201 and r.data.get("status") == "pending", r)
        bid = self.state["booking"] = r.data["id"]
        self.check("l'artisan est notifié de la demande", self.notified("artisan", "booking_request", bid))

        for status, who, label in (("confirmed", "artisan", "l'artisan accepte la mission"), ("in_progress", "artisan", "l'artisan démarre l'intervention")):
            cur = self.call(who, "GET", f"/bookings/{bid}/")
            r = self.call(who, "POST", f"/bookings/{bid}/transition/", json_body={"status": status, "expected_version": cur.data.get("version")},
                          headers={"Idempotency-Key": f"recette-{status}-{uuid.uuid4().hex[:8]}"})
            self.check(label, r.status == 200 and r.data.get("status") == status, r)
        self.check("le client est notifié (acceptée, démarrée)", self.notified("client", "booking_confirmed", bid) and self.notified("client", "booking_started", bid))

        self.section("Messages")
        r = self.call("client", "POST", "/me/conversations/", json_body={"booking": bid})
        self.check("le client ouvre la conversation de la réservation", r.status in (200, 201) and r.data.get("id"), r)
        cid = r.data["id"]
        r = self.call("client", "POST", "/messages/", json_body={"conversation": cid, "sender": self.state["client_id"], "content": "Le portail est ouvert."})
        self.check("le client envoie un message", r.status in (200, 201), r)
        r = self.call("artisan", "GET", f"/me/conversations/{cid}/messages/")
        self.check("l'artisan lit le message", r.status == 200 and any(m.get("content") == "Le portail est ouvert." for m in self.items(r)), r)
        self.check("l'artisan est notifié du message", self.notified("artisan", "message_received"))

        self.section("Paiement en espèces : déclaré, confirmé par l'autre partie")
        r = self.call("client", "GET", f"/bookings/{bid}/payment/")
        self.check("l'état du paiement est lisible (espèces, rien de déclaré)", r.status == 200 and r.data["cash"]["state"] == "none" and r.data["cash"]["can_declare"] is True and r.data["cash"]["verification"] == "manual", r)
        r = self.call("artisan", "POST", f"/bookings/{bid}/payment/cash/", fields={"amount": price, "note": "Remis à la fin de l'intervention"}, files={"receipt": ("recu.png", PNG, "image/png")},
                      headers={"Idempotency-Key": f"recette-cash-{uuid.uuid4().hex[:8]}"})
        self.check("l'artisan déclare les espèces reçues (justificatif joint)", r.status == 201 and r.data["declaration"]["status"] == "declared", r)
        did = r.data["declaration"]["id"]
        self.check("l'artisan ne peut pas confirmer sa propre déclaration", self.call("artisan", "POST", f"/payments/cash/{did}/respond/", json_body={"confirm": True}).status == 403)
        self.check("le client est invité à confirmer", self.notified("client", "cash_declared", bid))
        r = self.call("client", "GET", f"/payments/cash/{did}/receipt/")
        self.check("le client lit le justificatif privé", r.status == 200 and r.headers.get("cache-control") == "private, no-store" and r.headers.get("x-content-type-options") == "nosniff", Resp(r.status, None, r.headers))
        r = self.call("client", "POST", f"/payments/cash/{did}/respond/", json_body={"confirm": True})
        self.check("le client confirme : réglé en espèces, jamais « vérifié par un prestataire »", r.status == 200 and r.data["cash"]["state"] == "paid" and r.data["cash"]["verification"] == "manual", r)
        r = self.call("client", "GET", f"/bookings/{bid}/payment/")
        self.check("aucune vérification prestataire n'est affichée", "provider_verified" not in json.dumps(r.data) or r.data["payment"] is None or r.data["payment"]["provider_verified_at"] is None, r)
        self.check("l'artisan est informé de la confirmation", self.notified("artisan", "cash_confirmed", bid))

        self.section("Fin de mission et avis")
        cur = self.call("artisan", "GET", f"/bookings/{bid}/")
        r = self.call("artisan", "POST", f"/bookings/{bid}/transition/", json_body={"status": "completed", "expected_version": cur.data.get("version")},
                      headers={"Idempotency-Key": f"recette-done-{uuid.uuid4().hex[:8]}"})
        self.check("l'artisan termine la mission", r.status == 200 and r.data.get("status") == "completed", r)
        self.check("le client est invité à laisser un avis", self.notified("client", "booking_completed", bid))
        r = self.call("client", "POST", "/reviews/", json_body={"booking": bid, "rating": 5, "comment": "Travail soigné et ponctuel (recette)."})
        self.check("le client publie son avis", r.status == 201 and r.data.get("rating") == 5, r)
        rid = r.data["id"]
        r = self.call("artisan", "POST", f"/reviews/{rid}/reply/", json_body={"text": "Merci pour ce retour."})
        self.check("l'artisan répond à l'avis", r.status in (200, 201), r)
        self.check("l'artisan est notifié de l'avis", self.notified("artisan", "review_received"))

    def contract_journey(self) -> None:
        self.section("Contrat de longue durée : besoin → candidature → contrat → échéance")
        E = "/engagements"
        r = self.call("artisan", "GET", "/me/services/")
        services = [s for s in self.items(r) if s.get("published")]
        self.check("l'artisan a un service publié (catégorie du besoin)", r.status == 200 and services, r)
        detail = self.call("client", "GET", f"/services/{services[0]['id']}/")
        category = detail.data.get("category") if isinstance(detail.data.get("category"), int) else (detail.data.get("category_detail") or {}).get("id")
        start = (self.today + timedelta(days=1)).isoformat()
        body = {"category": category, "title": "Gardiennage de recette", "description": "Surveillance de la résidence, rondes et accueil des visiteurs.", "mission_type": "long_term",
                "work_relationship": "independent", "city": "Abidjan", "start_date": start, "schedule": WEEK, "amount": "180000", "period": "monthly", "conditions": "Tenue fournie."}
        r = self.call("client", "POST", f"{E}/postings/", json_body=body, headers={"Idempotency-Key": f"recette-posting-{uuid.uuid4().hex[:8]}"})
        self.check("le donneur d'ordre crée son besoin (brouillon)", r.status == 201 and r.data.get("status") == "draft", r)
        pid = r.data["id"]
        self.check("le prestataire ne voit pas le brouillon", self.call("artisan", "GET", f"{E}/postings/{pid}/").status == 404)
        r = self.call("client", "POST", f"{E}/postings/{pid}/publish/")
        self.check("le besoin est publié", r.status == 200 and r.data.get("status") == "open", r)
        r = self.call("artisan", "POST", f"{E}/postings/{pid}/apply/", json_body={"message": "Dix ans d'expérience.", "proposed_amount": "175000"})
        self.check("le prestataire candidate", r.status == 201, r)
        aid = r.data["id"]
        r = self.call("client", "POST", f"{E}/applications/{aid}/decision/", json_body={"decision": "select"})
        self.check("le donneur d'ordre retient la candidature", r.status == 200 and r.data.get("status") == "selected", r)
        r = self.call("client", "POST", f"{E}/contracts/", json_body={"application": aid, "notice_period_days": 10, "payment_day": 5})
        self.check("le contrat est créé en brouillon", r.status == 201 and r.data.get("status") == "draft", r)
        cid = self.state["contract"] = r.data["id"]
        self.check("le brouillon est invisible du prestataire", self.call("artisan", "GET", f"{E}/contracts/{cid}/").status == 404)
        r = self.call("client", "POST", f"{E}/contracts/{cid}/propose/")
        self.check("le contrat est proposé", r.status == 200 and r.data.get("status") == "pending_acceptance", r)
        self.check("le prestataire est notifié", self.notified("artisan", "contract_proposed"))
        d = self.call("artisan", "GET", f"{E}/contracts/{cid}/")
        self.check("le prestataire lit les conditions exactes (empreinte)", d.status == 200 and d.data.get("terms_hash") and "accept" in d.data.get("actions", []), d)
        r = self.call("artisan", "POST", f"{E}/contracts/{cid}/accept/", json_body={"terms_hash": d.data["terms_hash"]}, headers={"Idempotency-Key": f"recette-accept-{uuid.uuid4().hex[:8]}"})
        self.check("le prestataire accepte sur l'empreinte exacte", r.status == 200 and r.data.get("status") in ("accepted", "active"), r)
        if self.tick:
            self.tick()
        r = self.call("client", "GET", f"{E}/contracts/{cid}/installments/")
        insts = self.items(r)
        if not insts:
            self.log("  [à faire] aucune échéance générée tout de suite : la tâche horaire `engagements-tick` les crée (≤ 1 h). Relancer `--only contract` après le tick,")
            self.log("            ou le déclencher : manage.py shell -c \"from engagements import tasks; tasks.run()\". Étapes suivantes (paiement d'échéance) NON vérifiées.")
            return
        self.check("l'échéance du premier mois est générée automatiquement", r.status == 200 and insts[0].get("total") == "175000.00", r)
        inst = insts[0]
        r = self.call("client", "POST", f"{E}/installments/{inst['id']}/payments/", fields={"amount": "50000", "method": "mobile_money", "reference": "OM-RECETTE", "paid_on": self.today.isoformat()},
                      files={"evidence": ("recu.pdf", PDF, "application/pdf")}, headers={"Idempotency-Key": f"recette-pay-{uuid.uuid4().hex[:8]}"})
        self.check("le donneur d'ordre déclare un acompte (justificatif PDF facultatif joint)", r.status == 201 and r.data.get("status") == "declared", r)
        pay = r.data
        self.check("niveau de preuve : déclaré, jamais « vérifié »", pay["trust"]["level"] == "declared" and pay["trust"]["verified"] is False, pay)
        self.check("l'auteur ne confirme pas son paiement", self.call("client", "POST", f"{E}/payments/{pay['id']}/respond/", json_body={"confirm": True}).status == 403)
        self.check("le prestataire est invité à confirmer", self.notified("artisan", "payment_declared"))
        r = self.call("artisan", "POST", f"{E}/payments/{pay['id']}/respond/", json_body={"confirm": True})
        self.check("le prestataire confirme : confirmé, jamais « vérifié par un prestataire »", r.status == 200 and r.data["status"] == "confirmed" and r.data["trust"]["level"] == "confirmed" and r.data["trust"]["verified"] is False, r)
        h = self.call("client", "GET", f"{E}/contracts/{cid}/history/")
        self.check("l'historique du contrat est complet", h.status == 200 and len(self.items(h)) >= 4, h)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Recette du pilote par l'API HTTP.")
    p.add_argument("--api", required=True, help="Racine de l'API, ex. https://api-staging.exemple.ci/handy")
    p.add_argument("--only", choices=("all", "booking", "contract"), default="all")
    a = p.parse_args(argv)
    if not a.api.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        print("Refus : l'API doit être en HTTPS (HTTP uniquement pour localhost).", file=sys.stderr)
        return 2
    env = {k: os.environ.get(k, "") for k in ("RECETTE_CLIENT", "RECETTE_ARTISAN", "RECETTE_PASSWORD")}
    if not all(env.values()):
        print("Définir RECETTE_CLIENT, RECETTE_ARTISAN et RECETTE_PASSWORD (comptes de recette existants).", file=sys.stderr)
        return 2
    rec = Recette(HttpTransport(a.api), (env["RECETTE_CLIENT"], env["RECETTE_PASSWORD"]), (env["RECETTE_ARTISAN"], env["RECETTE_PASSWORD"]))
    try:
        rec.run(a.only)
    except RecetteFailure as exc:
        print(f"\nRECETTE EN ÉCHEC à l'étape : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
