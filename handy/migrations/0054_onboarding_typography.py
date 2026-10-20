"""Questions de l'inscription accompagnée : apostrophes typographiques (« Moins d’un an », « L’après-midi »).

Ne touche qu'aux textes affichés (question, aide, libellés et phrases des réponses) ; les valeurs enregistrées ne changent pas."""
from django.db import migrations


def _t(text):
    return text.replace("'", "’") if isinstance(text, str) else text


def typography(apps, schema_editor):
    Question = apps.get_model("handy", "OnboardingQuestion")
    for q in Question.objects.all():
        options = [{**o, **{k: _t(o[k]) for k in ("label", "phrase") if k in o}} if isinstance(o, dict) else o for o in (q.options or [])]
        text, help_text = _t(q.text), _t(q.help_text)
        if (text, help_text, options) != (q.text, q.help_text, q.options):
            q.text, q.help_text, q.options = text, help_text, options
            q.save(update_fields=["text", "help_text", "options"])


class Migration(migrations.Migration):
    dependencies = [("handy", "0053_onboarding_questions_seed")]
    operations = [migrations.RunPython(typography, migrations.RunPython.noop)]
