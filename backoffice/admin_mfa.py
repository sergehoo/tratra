"""Double authentification de `/admin/` (Django admin) : même appareil et mêmes règles que le Back-Office.

Un middleware redirige tout compte d'administration non vérifié vers `/admin/mfa/` ; la preuve est gardée en session
(durée limitée, invalidée par une réinitialisation de l'appareil)."""
import re
import time

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme

from backoffice import mfa

SESSION_AT, SESSION_DEV = "admin_mfa_at", "admin_mfa_c"
MFA_PATH = "/admin/mfa/"


def session_ok(request) -> bool:
    if not mfa.required():
        return True
    user = request.user
    if not (user.is_authenticated and user.is_staff):
        return True
    dev = mfa.confirmed_device(user)
    at, ref = request.session.get(SESSION_AT), request.session.get(SESSION_DEV)
    return bool(dev and at and ref == int(dev.confirmed_at.timestamp()) and time.time() - at <= mfa.max_age())


def _mark(request, user) -> None:
    dev = mfa.confirmed_device(user)
    request.session[SESSION_AT] = int(time.time())
    request.session[SESSION_DEV] = int(dev.confirmed_at.timestamp()) if dev else 0
    request.session.cycle_key()


class AdminMFAMiddleware:
    """Placé APRÈS l'authentification : refuse l'administration Django aux comptes non vérifiés."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if mfa.required() and path.startswith("/admin/") and not path.startswith(MFA_PATH) and not re.match(r"^/admin/(login|logout)/", path):
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated and user.is_staff and not session_ok(request):
                return HttpResponseRedirect(f"{MFA_PATH}?next={path}")
        return self.get_response(request)


def admin_mfa_view(request):
    user = request.user
    if not (user.is_authenticated and user.is_staff):
        return HttpResponseRedirect("/admin/login/?next=/admin/")
    nxt = request.GET.get("next") or request.POST.get("next") or "/admin/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) or not nxt.startswith("/admin/"):
        nxt = "/admin/"
    ctx = {"next": nxt, "enroll": mfa.confirmed_device(user) is None, "error": None}
    if request.method == "POST":
        step = request.POST.get("step")
        try:
            if step == "setup":
                if not user.check_password(request.POST.get("password", "")):
                    raise mfa.MFAError("invalid_password", "Mot de passe incorrect.", 403)
                ctx.update(mfa.begin_enrollment(user))
            elif step == "confirm":
                data = mfa.confirm_enrollment(user, request.POST.get("code", ""))
                _mark(request, user)
                return render(request, "backoffice/admin_mfa.html", {**ctx, "backup_codes": data["backup_codes"], "enroll": True})
            elif step == "verify":
                code = request.POST.get("code", "").strip()
                mfa.verify(user, **({"code": code} if code.isdigit() and len(code) == 6 else {"backup_code": code}))
                _mark(request, user)
                return HttpResponseRedirect(nxt)
        except mfa.MFAError as e:
            ctx["error"] = e.message
            if step == "confirm":      # activation en cours : on ré-affiche le QR existant impossible (secret non relu) → recommencer
                ctx["enroll"] = True
        status = 429 if ctx.get("error") and "verrouill" in ctx["error"] else 200
        return render(request, "backoffice/admin_mfa.html", ctx, status=status)
    return render(request, "backoffice/admin_mfa.html", ctx)
