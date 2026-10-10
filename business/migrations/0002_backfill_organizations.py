"""Les comptes « entreprise » existants reçoivent leur organisation (propriétaire = le compte), sans rien supprimer ni modifier."""
from django.db import migrations


def backfill(apps, schema_editor):
    CompanyProfile = apps.get_model("handy", "CompanyProfile")
    Organization = apps.get_model("business", "Organization")
    Membership = apps.get_model("business", "Membership")
    for cp in CompanyProfile.objects.all():
        if Organization.objects.filter(company_profile=cp).exists():
            continue
        org = Organization.objects.create(
            name=cp.company_name or f"Entreprise #{cp.user_id}", registration_number=cp.registration_number or "",
            industry=cp.industry or "", address=cp.address or "", city=cp.city or "", phone=cp.phone or "",
            owner_id=cp.user_id, company_profile=cp)
        Membership.objects.get_or_create(organization=org, user_id=cp.user_id, defaults={"role": "owner"})


class Migration(migrations.Migration):
    dependencies = [("business", "0001_initial")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
