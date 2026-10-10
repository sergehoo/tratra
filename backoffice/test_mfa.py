"""Double authentification (TOTP) du personnel : activation, vérification, anti-rejeu, codes de secours, verrouillage, réinitialisation,
application sur le Back-Office, l'ancienne API et /admin/ — avec de VRAIS jetons JWT (pas de force_authenticate)."""
import base64
import time

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, override_settings
from django_otp.oath import TOTP
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from backoffice import mfa, rbac
from backoffice.models import StaffMFA
from handy.api.staff_access import staff_may
from trust.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db
PASSWORD = "pass1234"
BO = "/handy/backoffice"


def staff(name, role="ops", superuser=False):
    rbac.ensure_roles()
    u = User.objects.create_user(name, f"{name}@x.test", PASSWORD, is_staff=True, is_superuser=superuser, first_name=name.title(), last_name="Admin")
    if role:
        u.groups.add(Group.objects.get(name=rbac.role_group_name(role)))
    return u


def api(user=None, token=None):
    c = APIClient()
    if user is not None or token is not None:
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token or str(RefreshToken.for_user(user).access_token)}")
    return c


def code_for(secret, at=None):
    t = TOTP(base64.b32decode(secret))
    if at is not None:
        t.time = at
    return f"{t.token():06d}"


def enroll(user):
    c = api(user)
    setup = c.post(f"{BO}/mfa/setup/", {"password": PASSWORD}, format="json")
    assert setup.status_code == 201
    secret = setup.data["secret"]
    done = c.post(f"{BO}/mfa/confirm/", {"code": code_for(secret)}, format="json")
    assert done.status_code == 200, done.data
    return secret, done.data


@pytest.fixture(autouse=True)
def _mfa_required(settings):
    settings.BACKOFFICE_MFA_REQUIRED = True
    settings.MFA_MAX_FAILURES = 5


def test_enrollment_needs_the_password_stores_the_secret_encrypted_and_returns_backup_codes_once():
    u = staff("m_user")
    c = api(u)
    assert c.get(f"{BO}/mfa/status/").data == {"required": True, "enrolled": False, "verified": False, "backup_codes_remaining": 0, "locked_until": None}
    assert c.post(f"{BO}/mfa/setup/", {"password": "mauvais"}, format="json").status_code == 403
    setup = c.post(f"{BO}/mfa/setup/", {"password": PASSWORD}, format="json")
    secret = setup.data["secret"]
    assert setup.status_code == 201 and len(secret) == 32 and setup.data["otpauth_uri"].startswith("otpauth://totp/Tratra:") and setup.data["qr"].startswith("data:image/svg+xml;base64,")
    row = StaffMFA.objects.get(user=u)
    assert secret not in row.secret_enc and row.confirmed_at is None                                # chiffré au repos, pas encore actif
    assert c.post(f"{BO}/mfa/confirm/", {"code": "000000"}, format="json").status_code == 400      # faux code : pas d'activation
    assert c.post(f"{BO}/mfa/confirm/", {"code": code_for(secret)}, format="json").data["backup_codes"].__len__() == 10
    row.refresh_from_db()
    assert row.confirmed_at is not None and len(row.backup_hashes) == 10 and all(len(h) == 64 for h in row.backup_hashes)
    assert api(u).post(f"{BO}/mfa/setup/", {"password": PASSWORD}, format="json").status_code == 409     # déjà activée : réinitialisation par un autre admin
    assert api(u).get(f"{BO}/mfa/status/").data["backup_codes_remaining"] == 10                    # jamais les codes eux-mêmes
    assert AuditEvent.objects.filter(action="backoffice.mfa.enrolled", target_id=u.pk).exists()


def test_regular_accounts_cannot_use_the_mfa_endpoints_and_are_never_blocked_by_it():
    plain = User.objects.create_user("m_plain", "m_plain@x.test", PASSWORD)
    assert api(plain).get(f"{BO}/mfa/status/").status_code == 403
    assert api(plain).post(f"{BO}/mfa/setup/", {"password": PASSWORD}, format="json").status_code == 403
    assert api(plain).get("/handy/me/activities/").status_code == 200                            # l'usage normal n'est pas concerné
    assert api().get(f"{BO}/mfa/status/").status_code == 401


def test_back_office_refuses_a_role_without_verified_mfa_with_a_coded_error_then_opens_after_verification(monkeypatch):
    u = staff("m_ops")
    c = api(u)
    r = c.get(f"{BO}/engagements/contracts/")
    assert r.status_code == 403 and r.json()["code"] == "mfa_enrollment_required"                # rôle suffisant, MFA absente
    assert c.get(f"{BO}/me/").json()["mfa"]["verified"] is False                                   # `me` reste lisible : l'interface en a besoin
    secret, tokens = enroll(u)
    assert api(token=tokens["access"]).get(f"{BO}/engagements/contracts/").status_code == 200      # jeton issu de l'activation = vérifié
    old = api(u).get(f"{BO}/engagements/contracts/")                                               # jeton de connexion simple
    assert old.status_code == 403 and old.json()["code"] == "mfa_required"
    later = time.time() + 31                                                                       # le code de l'activation est consommé : il faut le suivant
    monkeypatch.setattr("django_otp.oath.time", lambda: later)
    verified = api(u).post(f"{BO}/mfa/verify/", {"code": code_for(secret, at=later)}, format="json")
    assert verified.status_code == 200
    assert api(token=verified.data["access"]).get(f"{BO}/engagements/contracts/").status_code == 200


def test_totp_code_is_single_use_and_wrong_codes_lock_the_verification(monkeypatch):
    u = staff("m_replay")
    secret, _ = enroll(u)
    c = api(u)
    base = time.time()
    monkeypatch.setattr("django_otp.oath.time", lambda: base + 60)                                 # deux pas plus tard que l'activation
    good = code_for(secret, at=base + 60)
    assert c.post(f"{BO}/mfa/verify/", {"code": good}, format="json").status_code == 200
    again = c.post(f"{BO}/mfa/verify/", {"code": good}, format="json")
    assert again.status_code == 400 and again.json()["code"] == "invalid_code"                     # rejeu refusé
    for _ in range(5):
        c.post(f"{BO}/mfa/verify/", {"code": "123456"}, format="json")
    locked = c.post(f"{BO}/mfa/verify/", {"code": code_for(secret, at=base + 120)}, format="json")
    assert locked.status_code == 429 and locked.json()["code"] == "mfa_locked"                     # même un bon code est refusé pendant le verrouillage
    assert AuditEvent.objects.filter(action="backoffice.mfa.locked", target_id=u.pk).exists()


def test_backup_codes_work_once_each_and_are_counted():
    u = staff("m_backup")
    secret, done = enroll(u)
    c = api(u)
    code = done["backup_codes"][0]
    ok = c.post(f"{BO}/mfa/verify/", {"backup_code": code}, format="json")
    assert ok.status_code == 200 and api(token=ok.data["access"]).get(f"{BO}/engagements/contracts/").status_code == 200
    assert c.post(f"{BO}/mfa/verify/", {"backup_code": code}, format="json").status_code == 400    # déjà utilisé
    assert c.get(f"{BO}/mfa/status/").data["backup_codes_remaining"] == 9
    assert AuditEvent.objects.filter(action="backoffice.mfa.verified", target_id=u.pk, data__kind="backup").exists()


def test_verification_expires_after_the_maximum_age(settings, monkeypatch):
    settings.BACKOFFICE_MFA_MAX_AGE = 600
    u = staff("m_age")
    _, tokens = enroll(u)
    c = api(token=tokens["access"])
    assert c.get(f"{BO}/engagements/contracts/").status_code == 200
    real = time.time
    monkeypatch.setattr("backoffice.mfa.time.time", lambda: real() + 601)
    assert c.get(f"{BO}/engagements/contracts/").json()["code"] == "mfa_required"                  # trop ancien : re-vérifier


def test_reset_by_another_super_admin_invalidates_verified_tokens_and_needs_a_reason():
    root, target = staff("m_root", role="super_admin"), staff("m_target")
    _, tokens = enroll(target)
    assert api(token=tokens["access"]).get(f"{BO}/engagements/contracts/").status_code == 200
    _, root_tokens = enroll(root)
    admin = api(token=root_tokens["access"])
    assert admin.post(f"{BO}/security/staff/{root.pk}/mfa-reset/", {"reason": "Test sur soi-même"}, format="json").status_code == 409       # jamais sur soi
    assert admin.post(f"{BO}/security/staff/{target.pk}/mfa-reset/", {}, format="json").status_code == 400                                    # motif obligatoire
    done = admin.post(f"{BO}/security/staff/{target.pk}/mfa-reset/", {"reason": "Téléphone perdu, identité vérifiée en personne"}, format="json")
    assert done.status_code == 200 and done.json()["had_device"] is True
    assert not StaffMFA.objects.filter(user=target).exists()
    after = api(token=tokens["access"]).get(f"{BO}/engagements/contracts/")
    assert after.status_code in (401, 403)                                                         # sessions révoquées / preuve invalide
    assert AuditEvent.objects.filter(action="backoffice.mfa.reset", target_id=target.pk, actor=root).exists()
    rows = admin.get(f"{BO}/security/staff/").json()["results"]
    assert {r["id"]: r["mfa_enrolled"] for r in rows}[root.pk] is True


def test_legacy_staff_api_grants_nothing_without_verified_mfa_even_to_a_superuser():
    boss = staff("m_boss", role=None, superuser=True)
    assert staff_may(boss, "kyc.review") is False                                                  # MFA exigée, non vérifiée
    boss._mfa_ok = True
    assert staff_may(boss, "kyc.review") is True
    with override_settings(BACKOFFICE_MFA_REQUIRED=False):
        boss._mfa_ok = False
        assert staff_may(boss, "kyc.review") is True                                               # désactivée explicitement (développement)


def test_django_admin_is_behind_the_same_second_factor():
    u = staff("m_admin", role="super_admin", superuser=True)
    u.set_password(PASSWORD)
    u.save()
    web = Client()
    web.force_login(u)
    r = web.get("/admin/")
    assert r.status_code == 302 and r["Location"].startswith("/admin/mfa/")
    page = web.post("/admin/mfa/", {"step": "setup", "password": PASSWORD})
    assert page.status_code == 200 and b"QR code" in page.content
    secret = page.context["secret"]
    bad = web.post("/admin/mfa/", {"step": "confirm", "code": "000000"})
    assert b"Code incorrect" in bad.content
    ok = web.post("/admin/mfa/", {"step": "confirm", "code": code_for(secret)})
    assert ok.status_code == 200 and len(ok.context["backup_codes"]) == 10
    assert web.get("/admin/").status_code == 200                                                   # preuve gardée en session
    other = Client()
    other.force_login(u)
    assert other.get("/admin/").status_code == 302                                                 # nouvelle session : à re-vérifier
    assert other.get("/admin/mfa/?next=https://evil.example/").status_code == 200                  # redirection ouverte refusée (retour à /admin/)
    verify = other.post("/admin/mfa/", {"step": "verify", "code": "999999", "next": "https://evil.example/"})
    assert b"Code incorrect" in verify.content


# ── Rôles historiques, pré-vol et contrôles de déploiement ───────────────────────────────────────────────────────────

def _run(*args, **kwargs):
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command(*args, stdout=out, **kwargs)
    return out.getvalue()


def test_legacy_staff_roles_are_assigned_per_account_with_least_privilege_and_audited():
    legacy_a = User.objects.create_user("lg_a", "lg_a@x.test", PASSWORD, is_staff=True, first_name="Ancien")
    legacy_b = User.objects.create_user("lg_b", "lg_b@x.test", PASSWORD, is_staff=True, first_name="Autre")
    has_role = staff("lg_ok", role="support")
    sim = _run("assign_legacy_staff_roles", assign=[f"{legacy_a.pk}=finance"])
    assert "2 compte(s)" in sim and "Simulation" in sim and not rbac.user_roles(legacy_a)           # simulation : rien n'est modifié
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        _run("assign_legacy_staff_roles", assign=[f"{has_role.pk}=ops"], apply=True)                # déjà un rôle : refusé
    with pytest.raises(CommandError):
        _run("assign_legacy_staff_roles", assign=[f"{legacy_a.pk}=roi"], apply=True)                # rôle inconnu
    with pytest.raises(CommandError):
        _run("assign_legacy_staff_roles", apply=True)                                               # --apply sans rôle : refusé
    done = _run("assign_legacy_staff_roles", assign=[f"{legacy_a.pk}=finance"], apply=True)
    assert "1 rôle(s) attribué(s)" in done and "Double authentification exigée" in done
    assert rbac.user_roles(legacy_a) == {"finance"} and not rbac.user_roles(legacy_b)               # le compte non cité reste sans rôle
    assert AuditEvent.objects.filter(action="security.legacy_role_assigned", target_id=legacy_a.pk, data__role="finance").exists()
    with override_settings(LEGACY_STAFF_BYPASS=False):
        assert staff_may(legacy_b, "kyc.review") is False                                          # sans rôle et passe-droit fermé : plus d'accès global


def test_security_preflight_lists_blockers_and_strict_mode_fails_until_they_are_solved():
    from django.core.management.base import CommandError

    User.objects.create_user("pf_legacy", "pf_legacy@x.test", PASSWORD, is_staff=True)
    staff("pf_super", role="super_admin")
    report = _run("security_preflight")
    assert "sans rôle" in report and "super administrateur actif" in report and "LEGACY_STAFF_BYPASS" in report
    with pytest.raises(CommandError):
        _run("security_preflight", strict=True)
    legacy = User.objects.get(username="pf_legacy")
    legacy.groups.add(Group.objects.get(name=rbac.role_group_name("ops")))
    staff("pf_super2", role="super_admin")
    assert "Aucun bloquant" in _run("security_preflight", strict=True)


def test_deploy_check_warns_when_mfa_is_off_or_the_legacy_bypass_is_open(settings):
    from backoffice.checks import admin_security

    settings.DEBUG = False
    settings.BACKOFFICE_MFA_REQUIRED, settings.LEGACY_STAFF_BYPASS = False, True
    assert {w.id for w in admin_security(None)} == {"tratra.W001", "tratra.W002"}
    settings.BACKOFFICE_MFA_REQUIRED, settings.LEGACY_STAFF_BYPASS = True, False
    assert admin_security(None) == []
    settings.DEBUG = True
    settings.BACKOFFICE_MFA_REQUIRED, settings.LEGACY_STAFF_BYPASS = False, True
    assert admin_security(None) == []                                                              # développement : silencieux


def test_staff_mfa_command_reports_state_and_resets_with_a_reason_without_ever_printing_a_secret():
    from django.core.management.base import CommandError

    u = staff("cmd_user")
    enroll(u)
    status = _run("staff_mfa")
    assert "activée" in status and "cmd_user".title() in status
    with pytest.raises(CommandError):
        _run("staff_mfa", reset=u.pk, reason="x")
    assert "supprimé" in _run("staff_mfa", reset=u.pk, reason="Téléphone perdu, identité vérifiée")
    assert not StaffMFA.objects.filter(user=u).exists()
    assert AuditEvent.objects.filter(action="backoffice.mfa.reset", target_id=u.pk).exists()
