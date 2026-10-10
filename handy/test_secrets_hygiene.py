"""Aucun secret Firebase / signature / fournisseur dans Git : règles d'exclusion présentes et fichiers SUIVIS balayés (clés privées PEM,
clés Google, comptes de service, jetons Stripe/AWS/Twilio/Slack/GitHub). Les valeurs de test fabriquées à l'exécution ne sont pas des secrets."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IGNORED = ("google-services.json", "GoogleService-Info.plist", "*firebase-adminsdk*.json", "*service-account*.json", "fcm-*.json", "*.p8", "*.p12", "*.mobileprovision", "*.jks", "*.keystore")
PATTERNS = {
    "clé privée PEM": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "clé API Google": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "compte de service Google": re.compile(r'"type"\s*:\s*"service_account"'),
    "clé AWS": re.compile(r"AKIA[0-9A-Z]{16}"),
    "clé Stripe live": re.compile(r"[sr]k_live_[0-9A-Za-z]{10,}"),
    "SID Twilio": re.compile(r"\bAC[0-9a-f]{32}\b"),
    "jeton Slack": re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    "jeton GitHub": re.compile(r"gh[pousr]_[0-9A-Za-z]{30,}"),
}
# Fichiers de TEST qui fabriquent une fausse clé à l'exécution (jamais une vraie valeur).
ALLOWED = {"handy/test_push.py": {"compte de service Google"}, "handy/test_secrets_hygiene.py": set(PATTERNS)}
SKIP_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".zip", ".gz", ".lock", ".svg", ".webp", ".mp4")


@pytest.mark.parametrize("name", [".gitignore", ".dockerignore"])
def test_credential_files_are_excluded_from_git_and_images(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    missing = [p for p in IGNORED if p not in text]
    assert missing == []


def test_tracked_files_contain_no_secret():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("dépôt Git indisponible (image sans historique)")
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    found = []
    for rel in files:
        if rel.endswith(SKIP_SUFFIX) or "node_modules/" in rel or rel.endswith("package-lock.json"):
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text) and label not in ALLOWED.get(rel, set()):
                found.append((rel, label))
    assert found == []


def test_no_firebase_or_signing_file_is_tracked():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("dépôt Git indisponible")
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    bad = [f for f in files if re.search(r"(google-services\.json|GoogleService-Info\.plist|firebase-adminsdk|service-account.*\.json|\.p8|\.p12|\.mobileprovision|\.jks|\.keystore)$", f)]
    assert bad == []
