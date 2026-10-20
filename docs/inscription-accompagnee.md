# Inscription accompagnée (double parcours d'inscription professionnelle)

Pour qu'une nounou, une ménagère ou un jardinier peu à l'aise avec un smartphone puisse proposer ses services sans se perdre,
« Proposer mes services » offre deux chemins qui créent **le même compte** et aboutissent aux **mêmes règles** :

| | Inscription accompagnée (nouvelle) | Inscription classique (inchangée) |
|---|---|---|
| Pour qui | débutants, recommandée | habitués |
| Forme | une question par écran, gros boutons illustrés, voix | formulaire complet |
| Annonce | rédigée automatiquement (sans IA) à partir des réponses | saisie par l'utilisateur |

On peut passer de l'une à l'autre à tout moment : les réponses sont gardées et reprises dans le profil.

## Parcours

Métier → prestations → commune/quartier → questions du métier → **aperçu de l'annonce** → compte (prénom, nom, téléphone,
mot de passe — application seulement, le site exige déjà un compte) → code SMS → photo → pièce d'identité → fin.

- **Valeur d'abord** : l'utilisateur voit son annonce avant de créer son compte.
- **Reprise** : progression enregistrée à chaque réponse ; « Continuer mon inscription » rouvre l'écran atteint (application,
  site, autre appareil).
- **Tableau de bord débutant** : carte « Mon inscription professionnelle » (étapes faites/restantes, prochaine action
  calculée par le serveur, un seul bouton « Continuer »). Rien ne s'affiche pour un compte qui n'a pas commencé ce parcours.
- **Fin honnête** : tant que la photo ou la pièce manque, l'écran final dit « Il vous reste à… » (jamais « c'est fini »).
- **KYC simplifié** (application) : la pièce d'abord, puis les informations **préremplies** par la lecture du recto, à
  confirmer. Même revue humaine ; vérification faciale toujours facultative.
- **Code SMS** : « Plus tard » possible (l'annonce est créée, le tableau de bord proposera de confirmer le numéro).

## Voix

Synthèse vocale **de l'appareil** en français (application : `flutter_tts` ; site : `speechSynthesis` du navigateur). Aucun
fournisseur en ligne, aucune IA, rien n'est envoyé. Bouton « Réécouter », lecture automatique désactivable (préférence gardée).
Sans voix française installée, les boutons de voix n'apparaissent pas et les écrans restent utilisables.

## Configuration (administration Django)

- **Questions** : *Questions de l'inscription accompagnée* (`OnboardingQuestion`) — texte, aide, choix unique/multiple, cible
  (`experience`, `days`, `slots`, `strengths`, `price`, `info`), métiers concernés (liste ou mots-clés), ordre, activation.
  Chaque réponse : `value`, `label`, `emoji` et, pour rédiger l'annonce, `phrase`, `years`, `amount` + `unit`
  (`hour`, `day`, `month`, `job`, `quote`). Une question de métier remplace la question commune de même cible.
- **Tarifs** : de simples **suggestions** ; « Je discute le prix avec le client » est toujours proposé. Un tarif mensuel ou
  journalier n'est jamais publié comme faux forfait : l'offre reste « sur devis » et le montant va dans le profil.
- Configuration publique : `GET /handy/onboarding/config/?trade=<id>` (liste blanche des champs).

## Données et sécurité

- **Avant le compte**, le brouillon reste **sur le téléphone** (aucun appel privé ; jamais de mot de passe dans le brouillon).
- **Après**, il est sur le serveur (`GET/PUT /handy/me/onboarding/`). Hors ligne, il reste sur le téléphone **rattaché au
  compte** : il n'est jamais envoyé à un autre compte et il est effacé à la déconnexion volontaire.
- `POST /handy/me/onboarding/apply/` crée/complète le profil et l'offre sans jamais écraser ce que l'utilisateur a saisi
  ailleurs. **Rien n'est publié** avant l'éligibilité habituelle (identité vérifiée + validation de l'équipe).
- Compte unique : aucun nouveau rôle ; les profils et offres existants sont préservés.

## Limites connues

- « Moins d'un an » compte comme 1 an d'expérience (l'éligibilité exige une expérience > 0).
- La voix dépend de la voix française installée sur l'appareil ou le navigateur.
- SMS réels : fournisseur à configurer (voir `docs/sms-otp.md`) ; notifications push : identifiants Firebase/APNs requis.

## Tests

- Backend : `handy/test_onboarding.py`.
- Application : `test/onboarding_test.dart` (parcours avec et sans compte, reprise, code SMS, bascule classique, voix,
  aperçu identique au serveur, non-fuite entre comptes, KYC prérempli, petits écrans).
- Site : `src/lib/onboarding.test.ts` (`npm run test:bo`).
