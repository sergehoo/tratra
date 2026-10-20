"""Expérience déclarée telle quelle : une tranche (« Moins d’un an », « 3 à 5 ans ») n'est plus transformée en un nombre d'années flatteur.

1. Réponses semées de la question « experience » : `years` = borne BASSE de la tranche (0, 1, 3, 6, 10) au lieu de 1, 2, 4, 8, 12.
   Une réponse modifiée dans l'administration (autres années) n'est pas touchée.
2. Profils remplis par l'inscription accompagnée avec l'ancienne règle (ex. « Moins d’un an » enregistré comme 1 an) : la déclaration
   exacte est rétablie (`experience_label` + borne basse), seulement si le profil porte encore la valeur posée automatiquement.
"""
from django.db import migrations

# valeur de la réponse → (anciennes années semées, borne basse)
SEEDED = {"1": (1, 0), "2": (2, 1), "4": (4, 3), "8": (8, 6), "12": (12, 10)}


def exact(apps, schema_editor):
    Question = apps.get_model("handy", "OnboardingQuestion")
    Onboarding = apps.get_model("handy", "ProOnboarding")
    Profile = apps.get_model("handy", "HandymanProfile")
    labels = {}
    for q in Question.objects.filter(key="experience"):
        options, changed = [], False
        for o in q.options or []:
            old = SEEDED.get(str(o.get("value"))) if isinstance(o, dict) else None
            if old and o.get("years") == old[0]:
                o, changed = {**o, "years": old[1]}, True
            options.append(o)
            if isinstance(o, dict):
                labels[str(o.get("value"))] = str(o.get("label") or "")
        if changed:
            q.options = options
            q.save(update_fields=["options"])
    for ob in Onboarding.objects.filter(applied_at__isnull=False).exclude(answers={}):
        value = str((ob.answers or {}).get("experience") or "")
        if value not in SEEDED or not labels.get(value):
            continue
        Profile.objects.filter(user_id=ob.user_id, experience_years=SEEDED[value][0], experience_label="").update(
            experience_years=SEEDED[value][1], experience_label=labels[value])


class Migration(migrations.Migration):
    dependencies = [("handy", "0055_experience_declared_and_trade_minimum")]
    operations = [migrations.RunPython(exact, migrations.RunPython.noop)]
