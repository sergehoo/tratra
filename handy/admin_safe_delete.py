"""Suppression sécurisée dans l'administration Django (comptes et réservations) : aperçu exact, confirmation, audit, superutilisateur seul.

Remplace l'action « Supprimer la sélection » de Django (qui échoue dès qu'un objet PROTÉGÉ est lié) par le service `handy.safe_delete` :
l'argent réel n'est jamais effacé, les comptes réels sont anonymisés, les données fictives sont supprimées avec leurs dépendances."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse

from handy import safe_delete as sd


class SafeDeleteAdminMixin:
    safe_delete_kind = "users"          # "users" | "bookings"

    # ---- droits : superutilisateur uniquement (le bouton « Supprimer » et l'action disparaissent pour les autres)
    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)                      # remplacée : elle ne peut pas traverser les protections
        if self.has_delete_permission(request):
            actions["safe_delete_selected"] = (type(self).safe_delete_selected, "safe_delete_selected", "Supprimer en sécurité (aperçu et confirmation)…")
        return actions

    def safe_delete_selected(self, request, queryset):
        return self._safe_delete_response(request, queryset)

    def delete_view(self, request, object_id, extra_context=None):
        if not self.has_delete_permission(request):
            raise PermissionDenied
        queryset = self.get_queryset(request).filter(pk=object_id)
        if not queryset.exists():
            raise Http404
        return self._safe_delete_response(request, queryset, single=True)

    # ---- aperçu, confirmation, exécution
    def _safe_delete_response(self, request, queryset, single=False):
        if not self.has_delete_permission(request):
            raise PermissionDenied
        objs = list(queryset.select_related("client", "handyman") if self.safe_delete_kind == "bookings" else queryset)
        changelist = reverse(f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist")
        if len(objs) > sd.MAX_BATCH:
            self.message_user(request, f"{sd.MAX_BATCH} éléments au plus par opération (sélection : {len(objs)}). Pour un grand nettoyage : "
                                       "commande `cleanup_demo_data`.", messages.ERROR)
            return HttpResponseRedirect(changelist)
        confirm_fictive = bool(request.POST.get("confirm_fictive"))
        plan = sd.plan_users if self.safe_delete_kind == "users" else sd.plan_bookings
        outcomes = plan(objs, confirm_fictive=confirm_fictive, actor=request.user)

        if request.method == "POST" and request.POST.get("safe_delete_apply"):
            if request.POST.get("confirm_word", "").strip() == sd.CONFIRM_WORD:
                report = sd.execute(outcomes, apply=True, actor=request.user)
                self.message_user(request, f"Terminé : {len(report.deleted)} supprimé(s), {len(report.anonymized)} anonymisé(s), "
                                           f"{len(report.refused)} conservé(s) ({sum(report.counts.values())} objet(s) supprimé(s) au total).", messages.SUCCESS)
                return HttpResponseRedirect(changelist)
            messages.error(request, f"Pour confirmer, tapez exactement « {sd.CONFIRM_WORD} ».")

        report = sd.execute(outcomes, apply=False, actor=request.user)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.opts, "title": "Suppression sécurisée", "outcomes": outcomes, "report": report,
            "counts": sorted(report.counts.items()), "confirm_word": sd.CONFIRM_WORD, "confirm_fictive": confirm_fictive, "single": single,
            "ids": [o.obj_id for o in outcomes], "changelist_url": changelist, "kind": self.safe_delete_kind,
            "can_apply": any(o.action in ("delete", "anonymize") for o in outcomes),
        }
        return TemplateResponse(request, "admin/handy/safe_delete.html", context)
