"""Aides communes des classes d'administration."""


class CascadeOnlyDeleteMixin:
    """Historique en lecture seule : jamais supprimé ISOLÉMENT depuis sa propre liste, mais emporté avec son propriétaire (suppression d'un compte,
    d'un profil) par un superutilisateur. Sans cela, supprimer un compte erroné échoue toujours (« votre compte n'est pas autorisé à supprimer
    les types d'objet suivants ») dès qu'une ligne d'historique lui est liée, même pour un superutilisateur."""

    def has_delete_permission(self, request, obj=None):
        name = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
        direct = name.startswith(f"{self.opts.app_label}_{self.opts.model_name}_")       # liste, fiche ou suppression de CE modèle
        return bool(request.user.is_superuser) and not direct
