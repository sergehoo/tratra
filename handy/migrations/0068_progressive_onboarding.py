"""Onboarding progressif : publication, commandes et badge « Vérifié » deviennent trois niveaux distincts (handy/eligibility.py).

Colonnes : `suspended` (décision de modération), `orders_enabled` et `verification` (copies calculées), `ServiceCategory.face_required`
(métier sensible). Reprise des profils existants, SANS attribution de badge :

- `is_approved` n'est pas modifié : les professionnels déjà validés gardent leurs commandes, les autres ne gagnent rien ;
- un profil que l'équipe avait suspendu (dernière décision du Back-Office = suspension ou révocation du Tratra ID) est marqué
  `suspended` : il ne redevient pas visible avec la nouvelle règle de publication ;
- le niveau affiché est recalculé par la règle : sans vérification faciale satisfaisante, un profil validé devient
  « Identité vérifiée », jamais « Vérifié ».

Le recalcul appelle le code courant de la règle : il est fait dans un point de sauvegarde et, en cas d'échec sur une base rejouée
plus tard, laissé au démarrage (`manage.py eligibility_sync`) et à la réconciliation périodique — comme en 0060.

Ici : les colonnes seulement. La reprise des données est en 0069, dans sa propre transaction — PostgreSQL refuse de créer les index
d'une table dont des lignes viennent d'être modifiées dans la même transaction (« pending trigger events »)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('handy', '0067_user_gender'),
        ('trust', '0003_xp_penalties_score_history'),
        ('biometrics', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='handymanprofile',
            name='suspended',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='handymanprofile',
            name='orders_enabled',
            field=models.BooleanField(db_index=True, default=False, editable=False),
        ),
        migrations.AddField(
            model_name='handymanprofile',
            name='verification',
            field=models.CharField(choices=[('NON_VERIFIE', 'Non vérifié'), ('IDENTITE_VERIFIEE', 'Identité vérifiée'), ('VERIFIE', 'Vérifié')], db_index=True, default='NON_VERIFIE', editable=False, max_length=20),
        ),
        migrations.AddField(
            model_name='servicecategory',
            name='face_required',
            field=models.BooleanField(default=False, help_text="Métier sensible : la vérification faciale (selfie comparé à la pièce d'identité) est exigée AVANT toute commande. S'applique aussi à ses prestations. Sans cette case, la pièce d'identité approuvée suffit."),
        ),
    ]
