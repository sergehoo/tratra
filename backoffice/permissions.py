"""Classes de permission DRF du Back-Office : `bo_permission = "module.action"` sur la vue (ou un dict {action|méthode: code})."""
from rest_framework.permissions import BasePermission

from backoffice import rbac


class HasBackOfficePermission(BasePermission):
    message = "Droits insuffisants pour cette opération du Back-Office."

    def _required(self, request, view):
        spec = getattr(view, "bo_permission", None)
        if isinstance(spec, dict):
            key = getattr(view, "action", None) or request.method
            return spec.get(key) or spec.get(request.method) or spec.get("*")
        return spec

    def has_permission(self, request, view):
        required = self._required(request, view)
        if not required:  # une vue du Back-Office sans droit déclaré est refusée (jamais ouverte par oubli)
            return False
        return rbac.has_permission(request.user, required)
