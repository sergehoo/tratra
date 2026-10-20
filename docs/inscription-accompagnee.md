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
- **KYC simplifié** (application ET site, mêmes API `/me/kyc/`) : CNI ou passeport, photos guidées avec contrôle qualité
  (à reprendre / acceptée / nette), informations **préremplies** par la lecture du recto puis confirmées, envoi, suivi de la
  revue humaine (« en cours de revue », nouvelle pièce demandée avec le motif). Vérification faciale jamais imposée.
- **Progression commune** : « Étape x sur 9 » = les 9 étapes de Django (`JOURNEY`), même table écran → étape dans l'application
  et sur le site (vérifiée par les tests, le site relit `handy/onboarding.py`).
- **Code SMS** : « Plus tard » possible (l'annonce est créée, le tableau de bord proposera de confirmer le numéro).

## Voix

Synthèse vocale **de l'appareil** en français (application : `flutter_tts` ; site : `speechSynthesis` du navigateur). Aucun
fournisseur en ligne, aucune IA, rien n'est envoyé. Bouton « Réécouter », lecture automatique désactivable (préférence gardée).
Sans voix française installée, les boutons de voix n'apparaissent pas et les écrans restent utilisables.

## Expérience : déclaration exacte, minimum par métier

- La réponse choisie est enregistrée **telle quelle** : `HandymanProfile.experience_label` (« Moins d’un an », « 3 à 5 ans ») et
  `experience_years` = **borne basse** de la tranche (0, 1, 3, 6, 10) — jamais arrondie vers le haut. L'annonce dit
  « Expérience : moins d’un an. ». Le formulaire classique n'efface la tranche que si l'artisan **change** le nombre d'années.
- Expérience **déclarée** (profil complet) ≠ **éligibilité** : chaque métier a un minimum réglable dans l'administration
  (`ServiceCategory.min_experience_years`, 0 = débutants acceptés ; s'applique aussi à ses prestations). Il compte pour les
  spécialités et les offres actives, dans la règle unique `handy/eligibility.py` (Python et SQL, vérifiés concordants).
- Sous le minimum : rien n'est publié, la déclaration n'est jamais modifiée ; le minimum est annoncé **avant** de répondre,
  l'aperçu et le tableau de bord le disent (blocage `experience_minimum`, prochaine action `blocked`, pas « en attente »).
- Migration 0056 : les réponses semées passent aux bornes basses et les profils déjà remplis avec l'ancienne règle
  (« Moins d’un an » enregistré comme 1 an) retrouvent leur déclaration exacte.

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
- **Après**, il est sur le serveur (`GET/PUT /handy/me/onboarding/`), envoyé **un enregistrement à la fois, dans l'ordre**
  (réseau lent : une ancienne réponse n'écrase jamais une récente) ; double appui = un seul envoi.
- **Réseau coupé ou session expirée** : les réponses restent sur l'appareil **rattachées au compte** (application :
  préférences locales avec propriétaire ; site : coffre local cloisonné par compte), un bandeau le dit, elles repartent au
  retour du réseau ou à la réouverture (elles sont alors plus récentes que le serveur).
- **Changement de compte** pendant le parcours : plus aucun envoi ; les réponses sont gardées pour le compte d'origine, jamais
  montrées ni envoyées à un autre. Tout est effacé à la déconnexion volontaire.
- `POST /handy/me/onboarding/apply/` crée/complète le profil et l'offre sans jamais écraser ce que l'utilisateur a saisi
  ailleurs. **Rien n'est publié** avant l'éligibilité habituelle (identité vérifiée + validation de l'équipe).
- Compte unique : aucun nouveau rôle ; les profils et offres existants sont préservés.

## Limites connues

- La voix dépend de la voix française installée sur l'appareil ou le navigateur.
- SMS réels : fournisseur à configurer (voir `docs/sms-otp.md`) ; notifications push : identifiants Firebase/APNs requis.

## Tests

- Backend : `handy/test_onboarding.py`.
- Application : `test/onboarding_test.dart` (parcours avec et sans compte, reprise, code SMS, bascule classique, voix,
  aperçu identique au serveur, non-fuite entre comptes, KYC prérempli, petits écrans).
- Site : `src/lib/onboarding.test.ts` et `src/lib/kycFlow.test.ts` (`npm run test:bo`).
- Éligibilité : `handy/test_eligibility.py` (expérience déclarée et minimum par métier : SQL = Python).
