"""Double authentification du personnel : état, activation (secret + QR, confirmation par un code), vérification, codes de secours.

Ces routes sont accessibles à tout compte d'administration AVANT sa vérification (sinon l'activation serait impossible) mais
jamais à un compte ordinaire. Elles sont limitées (`mfa`), journalisées, et ne renvoient le secret qu'à l'activation."""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from backoffice import mfa
from trust.models import audit


class IsStaffAccount(permissions.BasePermission):
    message = "Réservé aux comptes d'administration."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_staff)


class MFAView(APIView):
    permission_classes = [IsStaffAccount]
    throttle_scope = "mfa"

    def fail(self, e: mfa.MFAError):
        return Response({"code": e.code, "detail": e.message}, status=e.status)


class MFAStatus(MFAView):
    def get(self, request):
        return Response(mfa.status(request.user))


class MFASetup(MFAView):
    """Démarre l'activation : renvoie le secret et le QR (une seule fois utile). Exige le mot de passe actuel."""

    def post(self, request):
        if not request.user.check_password(str(request.data.get("password") or "")):
            audit("backoffice.mfa.setup_refused", actor=request.user, target=request.user)
            return Response({"code": "invalid_password", "detail": "Mot de passe incorrect."}, status=status.HTTP_403_FORBIDDEN)
        try:
            data = mfa.begin_enrollment(request.user)
        except mfa.MFAError as e:
            return self.fail(e)
        audit("backoffice.mfa.setup_started", actor=request.user, target=request.user)
        return Response(data, status=status.HTTP_201_CREATED)


class MFAConfirm(MFAView):
    """Confirme l'activation avec un premier code valide : renvoie les codes de secours (affichés UNE fois) et des jetons vérifiés."""

    def post(self, request):
        try:
            data = mfa.confirm_enrollment(request.user, str(request.data.get("code") or ""))
        except mfa.MFAError as e:
            return self.fail(e)
        return Response(data)


class MFAVerify(MFAView):
    """Code TOTP (ou code de secours) → nouveaux jetons portant la preuve de vérification."""

    def post(self, request):
        try:
            data = mfa.verify(request.user, code=str(request.data.get("code") or ""), backup_code=str(request.data.get("backup_code") or ""))
        except mfa.MFAError as e:
            return self.fail(e)
        return Response(data)
