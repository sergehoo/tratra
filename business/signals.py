from django.db.models.signals import post_save
from django.dispatch import receiver

from business import services
from business.models import Membership, Organization, Role
from handy.models import Booking, CompanyProfile


@receiver(post_save, sender=Booking, dispatch_uid="business_booking_saved")
def booking_changed(sender, instance, created, **kwargs):
    if kwargs.get("raw") or created:
        return
    services.sync_from_booking(instance)


@receiver(post_save, sender=CompanyProfile, dispatch_uid="business_company_profile_saved")
def company_profile_saved(sender, instance, created, **kwargs):
    """Un compte « entreprise » reçoit son organisation (propriétaire = le compte) : aucun doublon, aucune perte."""
    if kwargs.get("raw") or Organization.objects.filter(company_profile=instance).exists():
        return
    org = Organization.objects.create(
        name=instance.company_name or f"Entreprise #{instance.user_id}", registration_number=instance.registration_number or "",
        industry=instance.industry or "", address=instance.address or "", city=instance.city or "", phone=instance.phone or "",
        owner=instance.user, company_profile=instance)
    Membership.objects.get_or_create(organization=org, user=instance.user, defaults={"role": Role.OWNER})
