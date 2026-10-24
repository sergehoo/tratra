"""Tient `HandymanProfile.published` (copie calculée de la règle d'éligibilité) à jour DANS LA MÊME TRANSACTION que chaque changement
qui peut la modifier : un professionnel suspendu, une pièce d'identité rejetée ou un métier durci disparaissent de la recherche au
moment même où le changement est validé.

Déclencheurs : profil (validation, présentation, commune, photo, expérience), compte (activation), pièce KYC (statut, suppression),
spécialités (ajout, retrait), offres (activation, métier), métier (expérience minimale, rattachement).
Les écritures en masse (`queryset.update()`) n'émettent aucun signal : elles appellent `eligibility.refresh_published` elles-mêmes
(action d'administration, parcours KYC). Filet de sécurité : réconciliation périodique (`handy.tasks.reconcile_published`) et
au démarrage (`manage.py eligibility_sync`), qui signale tout écart.
La disponibilité (« Disponible », absences, horaires) ne fait pas partie de la règle : elle reste vérifiée en direct, jamais copiée."""
from django.db.models import Q
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete

from handy import eligibility
from handy.models import HandymanDocument, HandymanProfile, Service, ServiceCategory, User

PROFILE_FIELDS = {"is_approved", "bio", "commune", "photo", "experience_years", "experience_label", "user", "user_id"}
SERVICE_FIELDS = {"is_active", "category", "category_id", "handyman", "handyman_id"}
CATEGORY_FIELDS = {"min_experience_years", "parent", "parent_id"}


def _relevant(update_fields, fields) -> bool:
    return update_fields is None or bool(set(update_fields) & fields)


def _refresh_user(user_id) -> None:
    eligibility.refresh_published(HandymanProfile.objects.filter(user_id=user_id))


def profile_saved(sender, instance, raw=False, update_fields=None, **kwargs):
    if not raw and _relevant(update_fields, PROFILE_FIELDS):
        eligibility.refresh_published([instance.pk])


def user_saved(sender, instance, raw=False, update_fields=None, created=False, **kwargs):
    # La dernière connexion (`last_login`) et la plupart des mises à jour ne touchent pas l'activation : rien à recalculer.
    if not raw and not created and _relevant(update_fields, {"is_active"}):
        _refresh_user(instance.pk)


def document_changed(sender, instance, raw=False, **kwargs):
    if not raw and instance.handyman_id:
        eligibility.refresh_published([instance.handyman_id])


def service_saved(sender, instance, raw=False, update_fields=None, **kwargs):
    if not raw and _relevant(update_fields, SERVICE_FIELDS):
        _refresh_user(instance.handyman_id)


def service_deleted(sender, instance, **kwargs):
    _refresh_user(instance.handyman_id)


def _subtree(category_id) -> list:
    ids = {category_id}
    level = {category_id}
    for _ in range(2):   # la règle remonte au plus au grand-parent : deux niveaux de descendants suffisent
        level = set(ServiceCategory.objects.filter(parent_id__in=level).values_list("pk", flat=True)) - ids
        ids |= level
    return sorted(ids)


def _profiles_of_categories(category_ids):
    return HandymanProfile.objects.filter(Q(skills__in=category_ids)
                                          | Q(user__services__category_id__in=category_ids, user__services__is_active=True))


def category_saved(sender, instance, raw=False, update_fields=None, created=False, **kwargs):
    if not raw and not created and _relevant(update_fields, CATEGORY_FIELDS):
        eligibility.refresh_published(_profiles_of_categories(_subtree(instance.pk)))


def category_deleting(sender, instance, **kwargs):
    # Après la suppression, les liens (spécialités, offres) auront disparu : on retient les profils concernés avant.
    instance._eligibility_profiles = list(_profiles_of_categories(_subtree(instance.pk)).values_list("pk", flat=True).distinct())


def category_deleted(sender, instance, **kwargs):
    eligibility.refresh_published(getattr(instance, "_eligibility_profiles", []))


def skills_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if action == "pre_clear" and reverse:
        instance._eligibility_profiles = list(instance.handymen.values_list("pk", flat=True))
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    if not reverse:
        eligibility.refresh_published([instance.pk])
    elif action == "post_clear":
        eligibility.refresh_published(getattr(instance, "_eligibility_profiles", []))
    else:
        eligibility.refresh_published(list(pk_set or []))


def skill_link_deleted(sender, instance, **kwargs):
    # Liens spécialité supprimés en cascade (métier ou profil supprimé) : aucun m2m_changed n'est émis dans ce cas.
    eligibility.refresh_published([instance.handymanprofile_id])


def connect() -> None:
    uid = "eligibility_sync"
    post_save.connect(profile_saved, sender=HandymanProfile, dispatch_uid=f"{uid}.profile")
    post_save.connect(user_saved, sender=User, dispatch_uid=f"{uid}.user")
    post_save.connect(document_changed, sender=HandymanDocument, dispatch_uid=f"{uid}.document_saved")
    post_delete.connect(document_changed, sender=HandymanDocument, dispatch_uid=f"{uid}.document_deleted")
    post_save.connect(service_saved, sender=Service, dispatch_uid=f"{uid}.service_saved")
    post_delete.connect(service_deleted, sender=Service, dispatch_uid=f"{uid}.service_deleted")
    post_save.connect(category_saved, sender=ServiceCategory, dispatch_uid=f"{uid}.category_saved")
    pre_delete.connect(category_deleting, sender=ServiceCategory, dispatch_uid=f"{uid}.category_deleting")
    post_delete.connect(category_deleted, sender=ServiceCategory, dispatch_uid=f"{uid}.category_deleted")
    m2m_changed.connect(skills_changed, sender=HandymanProfile.skills.through, dispatch_uid=f"{uid}.skills")
    post_delete.connect(skill_link_deleted, sender=HandymanProfile.skills.through, dispatch_uid=f"{uid}.skill_link")
