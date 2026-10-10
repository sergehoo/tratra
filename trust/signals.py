"""Réévaluation automatique des badges quand une donnée qui les fonde change.

Les réévaluations s'exécutent DANS la transaction de l'action métier : un retrait (suspension, KYC rejeté,
compte désactivé) est donc immédiat et cohérent — il n'attend ni une tâche planifiée ni un cache. La
réévaluation périodique (trust.tasks) rattrape ce qui dépend du temps (fenêtre d'observation, expiration des
justificatifs) et sert de filet de sécurité.
"""
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from handy.models import Booking, Dispute, HandymanDocument, HandymanProfile, Review, User
from trust.engine import evaluate_user

# Champs de profil qui conditionnent l'éligibilité (donc VERIFIE) ou le niveau d'expérience (EXPERT).
PROFILE_FIELDS = ("is_approved", "bio", "commune", "photo", "experience_years")


def _trigger(user_id, why):
    if user_id:
        evaluate_user(user_id, trigger=why)


@receiver(pre_save, sender=HandymanProfile, dispatch_uid="trust_profile_snapshot")
def remember_profile(sender, instance, **kwargs):
    if kwargs.get("raw") or not instance.pk:
        instance._trust_changed = False
        return
    old = HandymanProfile.objects.filter(pk=instance.pk).values(*PROFILE_FIELDS).first()
    current = {f: getattr(instance, f) for f in PROFILE_FIELDS}
    # `photo` est un FieldFile : on compare les noms de fichier.
    if old is not None:
        old["photo"] = old["photo"] or ""
        current["photo"] = getattr(current["photo"], "name", current["photo"]) or ""
    instance._trust_changed = old is None or old != current


@receiver(post_save, sender=HandymanProfile, dispatch_uid="trust_profile_saved")
def profile_saved(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
    if created or getattr(instance, "_trust_changed", False):
        _trigger(instance.user_id, "profile")


@receiver(m2m_changed, sender=HandymanProfile.skills.through, dispatch_uid="trust_skills_changed")
def skills_changed(sender, instance, action, reverse, **kwargs):
    if action in ("post_add", "post_remove", "post_clear") and not reverse:
        _trigger(instance.user_id, "skills")


@receiver(pre_save, sender=User, dispatch_uid="trust_user_snapshot")
def remember_user(sender, instance, **kwargs):
    if kwargs.get("raw") or not instance.pk:
        instance._trust_was_active = None
        return
    instance._trust_was_active = User.objects.filter(pk=instance.pk).values_list("is_active", flat=True).first()


@receiver(post_save, sender=User, dispatch_uid="trust_user_saved")
def user_saved(sender, instance, created, **kwargs):
    if kwargs.get("raw") or created:
        return
    was = getattr(instance, "_trust_was_active", None)
    if was is not None and was != instance.is_active:  # suspension / réactivation du compte
        _trigger(instance.pk, "account")


@receiver(post_save, sender=HandymanDocument, dispatch_uid="trust_document_saved")
@receiver(post_delete, sender=HandymanDocument, dispatch_uid="trust_document_deleted")
def document_changed(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    _trigger(getattr(instance.handyman, "user_id", None) if instance.handyman_id else None, "document")


@receiver(post_save, sender=Review, dispatch_uid="trust_review_saved")
@receiver(post_delete, sender=Review, dispatch_uid="trust_review_deleted")
def review_changed(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    handyman_id = Booking.objects.filter(pk=instance.booking_id).values_list("handyman_id", flat=True).first()
    _trigger(handyman_id, "review")


@receiver(post_save, sender=Booking, dispatch_uid="trust_booking_saved")
def booking_saved(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    if instance.status in ("completed", "cancelled"):  # missions comptabilisées / litiges / ponctualité
        _trigger(instance.handyman_id, "mission")


@receiver(post_save, sender=Dispute, dispatch_uid="trust_dispute_saved")
def dispute_saved(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    handyman_id = Booking.objects.filter(pk=instance.booking_id).values_list("handyman_id", flat=True).first()
    _trigger(handyman_id, "dispute")
