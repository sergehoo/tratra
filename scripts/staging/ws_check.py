#!/usr/bin/env python3
"""Vérifie le WebSocket du suivi live d'un environnement (staging) avec la bibliothèque standard uniquement.

  1. SANS billet : la poignée de main doit être REFUSÉE (HTTP 403) — prouve que la pile WebSocket est attachée à ASGI et
     routée par le reverse proxy (un 404/500/502 révèle un problème de routage Traefik ou d'import ASGI).
  2. AVEC billet (--booking et TRATRA_TOKEN) : POST /bookings/<id>/live/ticket/ → connexion → premier message « state »
     → ping applicatif → « pong ».

Le jeton d'accès se passe par la variable d'environnement TRATRA_TOKEN (jamais en argument : historique du shell) et n'est
jamais affiché.

Exemples :
  python3 ws_check.py --api https://api-staging.example.com/handy
  TRATRA_TOKEN=... python3 ws_check.py --api https://api-staging.example.com/handy --booking 42
Code de sortie : 0 = tout est conforme, 1 = anomalie.
"""
import argparse
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class Conn:
    """Socket + octets déjà lus (un objet socket ne peut pas porter d'attribut)."""

    def __init__(self, sock, rest=b""):
        self.sock, self.rest = sock, rest

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _open(url, timeout=10):
    u = urlparse(url)
    tls = u.scheme in ("wss", "https")
    host, port = u.hostname, u.port or (443 if tls else 80)
    raw = socket.create_connection((host, port), timeout=timeout)
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if tls else raw
    return sock, u


def handshake(url, timeout=10):
    """Renvoie (statut HTTP, socket ouverte ou None, en-têtes)."""
    sock, u = _open(url, timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    target = u.path + (f"?{u.query}" if u.query else "")
    host = u.hostname + (f":{u.port}" if u.port else "")
    request = (
        f"GET {target} HTTP/1.1\r\nHost: {host}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n"
        f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\nOrigin: https://{u.hostname}\r\n\r\n"
    )
    sock.sendall(request.encode())
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.decode("latin1").split("\r\n")
    status = int(lines[0].split()[1]) if lines and len(lines[0].split()) > 1 else 0
    headers = {k.strip().lower(): v.strip() for k, v in (ln.split(":", 1) for ln in lines[1:] if ":" in ln)}
    if status == 101:
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expected:
            sock.close()
            return 0, None, headers
        return 101, Conn(sock, rest), headers
    sock.close()
    return status, None, headers


def send_text(conn, text):
    payload = text.encode()
    mask = os.urandom(4)
    length = len(payload)
    header = bytes([0x81])
    header += bytes([0x80 | length]) if length < 126 else bytes([0x80 | 126]) + struct.pack(">H", length)
    conn.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


def _read_exact(conn, n):
    buf = conn.rest
    while len(buf) < n:
        chunk = conn.sock.recv(4096)
        if not chunk:
            raise ConnectionError("connexion fermée par le serveur")
        buf += chunk
    conn.rest = buf[n:]
    return buf[:n]


def read_text(conn):
    """Lit la prochaine trame texte (ignore ping/pong de contrôle)."""
    while True:
        b1, b2 = _read_exact(conn, 2)
        opcode, length = b1 & 0x0F, b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", _read_exact(conn, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", _read_exact(conn, 8))[0]
        payload = _read_exact(conn, length)
        if opcode == 0x1:
            return payload.decode()
        if opcode == 0x8:
            raise ConnectionError(f"fermeture demandée par le serveur (code {struct.unpack('>H', payload[:2])[0] if payload else '?'})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", required=True, help="base de l'API, ex. https://api-staging.example.com/handy")
    ap.add_argument("--booking", type=int, help="identifiant d'une réservation dont le jeton (TRATRA_TOKEN) est participant")
    args = ap.parse_args()

    base = args.api.rstrip("/")
    root = urlparse(base)
    ws_scheme = "wss" if root.scheme == "https" else "ws"
    ws_base = f"{ws_scheme}://{root.netloc}"
    failures = []

    # 1) Refus sans billet (la pile WebSocket répond, c'est le consommateur qui refuse)
    for path in ("/ws/live/1/", "/ws/chat/1/"):
        status, sock, _ = handshake(f"{ws_base}{path}")
        if sock:
            sock.close()
        ok = status == 403
        print(f"[{'OK ' if ok else 'ERR'}] sans billet {path} -> HTTP {status} (attendu 403)")
        if not ok:
            failures.append(path)

    # 2) Parcours authentifié
    if args.booking:
        token = os.environ.get("TRATRA_TOKEN", "")
        if not token:
            print("[ERR] TRATRA_TOKEN absent : impossible de tester le billet")
            return 1
        req = urllib.request.Request(f"{base}/bookings/{args.booking}/live/ticket/", data=b"{}", method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                ticket = json.load(r)
        except urllib.error.HTTPError as e:
            print(f"[ERR] billet refusé : HTTP {e.code}")
            return 1
        url = f"{ws_base}{ticket['path']}?ticket={urllib.request.quote(ticket['ticket'], safe='')}"
        status, sock, _ = handshake(url)
        if status != 101 or not sock:
            print(f"[ERR] poignée de main avec billet -> HTTP {status} (attendu 101)")
            return 1
        try:
            first = json.loads(read_text(sock))
            ok = first.get("type") == "state"
            print(f"[{'OK ' if ok else 'ERR'}] avec billet : 101 puis message « {first.get('type')} » (phase {first.get('state', {}).get('phase')})")
            if not ok:
                failures.append("state")
            send_text(sock, json.dumps({"type": "ping"}))
            pong = json.loads(read_text(sock))
            ok = pong.get("type") == "pong"
            print(f"[{'OK ' if ok else 'ERR'}] ping applicatif -> {pong.get('type')}")
            if not ok:
                failures.append("pong")
        finally:
            sock.close()

    print("RÉSULTAT :", "CONFORME" if not failures else f"ANOMALIES : {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
