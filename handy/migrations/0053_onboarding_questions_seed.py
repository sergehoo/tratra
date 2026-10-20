"""Questions par défaut du parcours « Inscription accompagnée » (ajout seul ; modifiables ensuite dans l'administration).

Les tarifs proposés sont des SUGGESTIONS de départ (l'utilisateur peut toujours choisir « Je discute le prix avec le client »).
Une question existante (même `key`) n'est jamais écrasée."""
from django.db import migrations


def opt(value, label, emoji="", **extra):
    return {"value": value, "label": label, "emoji": emoji, **extra}


QUOTE = opt("quote", "Je discute le prix avec le client", "🤝", unit="quote", phrase="prix à discuter")

COMMON = [
    dict(key="experience", position=10, target="experience", kind="single",
         text="Depuis combien de temps faites-vous ce travail ?", help_text="Touchez la réponse qui vous correspond.",
         options=[opt("1", "Moins d'un an", "🌱", years=1), opt("2", "1 à 2 ans", "🙂", years=2), opt("4", "3 à 5 ans", "💪", years=4),
                  opt("8", "6 à 10 ans", "⭐", years=8), opt("12", "Plus de 10 ans", "🏆", years=12)]),
    dict(key="days", position=80, target="days", kind="multi",
         text="Quels jours pouvez-vous travailler ?", help_text="Touchez tous les jours qui vous conviennent.",
         options=[opt("monday", "Lundi"), opt("tuesday", "Mardi"), opt("wednesday", "Mercredi"), opt("thursday", "Jeudi"),
                  opt("friday", "Vendredi"), opt("saturday", "Samedi"), opt("sunday", "Dimanche")]),
    dict(key="slots", position=90, target="slots", kind="multi",
         text="À quel moment de la journée ?", help_text="Vous pouvez en choisir plusieurs.",
         options=[opt("morning", "Le matin", "🌅"), opt("afternoon", "L'après-midi", "☀️"), opt("evening", "Le soir", "🌙")]),
]

GENERIC_PRICE = dict(key="price_general", position=70, target="price", kind="single",
                     text="Comment voulez-vous fixer votre prix ?", help_text="Vous pourrez le changer plus tard.",
                     options=[opt("h2000", "2 000 FCFA de l'heure", "⏱️", amount=2000, unit="hour"),
                              opt("h5000", "5 000 FCFA de l'heure", "⏱️", amount=5000, unit="hour"),
                              opt("j10000", "10 000 FCFA par intervention", "🧾", amount=10000, unit="job"), QUOTE])

BY_TRADE = [
    ("nounou, nousnou, nourrice, garde d'enfant, garde-enfant, baby, bebe, enfant", [
        dict(key="nanny_skills", position=30, target="strengths", kind="multi",
             text="Que savez-vous faire avec les enfants ?", help_text="Touchez tout ce que vous savez faire.",
             options=[opt("babies", "M'occuper des bébés", "👶", phrase="soins des bébés"),
                      opt("meals", "Préparer leurs repas", "🍲", phrase="préparation des repas des enfants"),
                      opt("school", "Les accompagner à l'école", "🎒", phrase="accompagnement à l'école"),
                      opt("homework", "Aider aux devoirs", "📚", phrase="aide aux devoirs"),
                      opt("bath", "Donner le bain", "🛁", phrase="toilette et bain"),
                      opt("housework", "Petit ménage", "🧹", phrase="petit ménage")]),
        dict(key="nanny_live_in", position=40, target="info", kind="single",
             text="Pouvez-vous dormir chez la famille ?", help_text="",
             options=[opt("yes", "Oui, je peux loger sur place", "🏠", phrase="logement sur place possible"),
                      opt("no", "Non, je rentre chez moi le soir", "🚶", phrase="sans hébergement")]),
        dict(key="nanny_price", position=70, target="price", kind="single",
             text="Quel salaire souhaitez-vous ?", help_text="C'est une base de discussion avec la famille.",
             options=[opt("m40000", "40 000 FCFA par mois", "💵", amount=40000, unit="month"),
                      opt("m60000", "60 000 FCFA par mois", "💵", amount=60000, unit="month"),
                      opt("m80000", "80 000 FCFA par mois", "💵", amount=80000, unit="month"), QUOTE]),
    ]),
    ("menage, menagere, nettoyage, repassage, lessive, femme de menage", [
        dict(key="cleaning_skills", position=30, target="strengths", kind="multi",
             text="Quelles tâches faites-vous ?", help_text="Touchez tout ce que vous savez faire.",
             options=[opt("floors", "Balayer et laver le sol", "🧹", phrase="sols"),
                      opt("laundry", "La lessive", "👕", phrase="lessive"),
                      opt("ironing", "Le repassage", "🧺", phrase="repassage"),
                      opt("dishes", "La vaisselle", "🍽️", phrase="vaisselle"),
                      opt("windows", "Les vitres", "🪟", phrase="vitres"),
                      opt("tidy", "Ranger la maison", "🛏️", phrase="rangement")]),
        dict(key="cleaning_price", position=70, target="price", kind="single",
             text="Quel prix souhaitez-vous ?", help_text="Vous pourrez le changer plus tard.",
             options=[opt("d5000", "5 000 FCFA par jour", "💵", amount=5000, unit="day"),
                      opt("m40000", "40 000 FCFA par mois", "💵", amount=40000, unit="month"),
                      opt("m60000", "60 000 FCFA par mois", "💵", amount=60000, unit="month"), QUOTE]),
    ]),
    ("cuisine, cuisinier, cuisiniere, traiteur, repas", [
        dict(key="cooking_skills", position=30, target="strengths", kind="multi",
             text="Quels plats savez-vous préparer ?", help_text="Touchez tout ce que vous savez faire.",
             options=[opt("local", "Plats ivoiriens et africains", "🍛", phrase="plats ivoiriens et africains"),
                      opt("european", "Plats européens", "🥘", phrase="plats européens"),
                      opt("daily", "Repas de tous les jours", "🥗", phrase="repas du quotidien"),
                      opt("party", "Repas de fête", "🎉", phrase="repas de fête"),
                      opt("pastry", "Pâtisserie", "🧁", phrase="pâtisserie")]),
        dict(key="cooking_price", position=70, target="price", kind="single",
             text="Quel prix souhaitez-vous ?", help_text="Vous pourrez le changer plus tard.",
             options=[opt("m50000", "50 000 FCFA par mois", "💵", amount=50000, unit="month"),
                      opt("m75000", "75 000 FCFA par mois", "💵", amount=75000, unit="month"),
                      opt("j10000", "10 000 FCFA par repas de fête", "🧾", amount=10000, unit="job"), QUOTE]),
    ]),
    ("jardin, jardinage, jardinier, espaces verts, gazon, pelouse", [
        dict(key="garden_skills", position=30, target="strengths", kind="multi",
             text="Quels travaux faites-vous au jardin ?", help_text="Touchez tout ce que vous savez faire.",
             options=[opt("lawn", "Tondre le gazon", "🌿", phrase="tonte du gazon"),
                      opt("hedges", "Tailler les haies", "✂️", phrase="taille des haies"),
                      opt("flowers", "Entretenir les fleurs", "🌸", phrase="entretien des fleurs"),
                      opt("planting", "Planter", "🌱", phrase="plantations"),
                      opt("cleanup", "Nettoyer le jardin", "🍂", phrase="nettoyage du jardin")]),
        dict(key="garden_price", position=70, target="price", kind="single",
             text="Quel prix souhaitez-vous ?", help_text="Vous pourrez le changer plus tard.",
             options=[opt("j5000", "5 000 FCFA par passage", "🧾", amount=5000, unit="job"),
                      opt("m40000", "40 000 FCFA par mois", "💵", amount=40000, unit="month"), QUOTE]),
    ]),
]


def seed(apps, schema_editor):
    Question = apps.get_model("handy", "OnboardingQuestion")
    rows = [(q, "") for q in COMMON] + [(GENERIC_PRICE, "__generic__")]
    for keywords, questions in BY_TRADE:
        rows += [(q, keywords) for q in questions]
    for q, keywords in rows:
        if Question.objects.filter(key=q["key"]).exists():
            continue
        Question.objects.create(**q, trade_keywords="" if keywords == "__generic__" else keywords)


class Migration(migrations.Migration):
    dependencies = [("handy", "0052_pro_onboarding")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
