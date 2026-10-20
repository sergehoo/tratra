# « Vérifier mon identité » — parcours guidé et éligibilité

Un seul parcours en 7 étapes, enregistré côté Django (`KycDossier`) : l'artisan reprend là où il s'était arrêté, même après avoir fermé
l'application. **Ce n'est pas un second système de vérification** : les photos transmises deviennent des pièces `HandymanDocument`
(« id_card ») revues dans la file KYC du Back-Office, la vérification faciale reste celle du module `biometrics`, la validation finale
reste `approve_profile` (Back-Office).

| # | Étape | Ce qui se passe |
|---|---|---|
| 1 | Informations personnelles | nom et prénoms **tels qu'ils figurent sur la pièce**, date de naissance (≥ `KYC_MIN_AGE`, 18 par défaut). Le nom public du compte n'est pas modifié. |
| 2 | Choix de la pièce | carte nationale d'identité (recto + verso) ou passeport (page photo). Changer de pièce efface les photos non transmises. |
| 3 | Photo | caméra de l'application ; JPEG/PNG, ≤ `KYC_MAX_UPLOAD_BYTES`. |
| 4 | Contrôle qualité et lecture | qualité mesurée (`intelligence.documents.image_quality_problems`) : image illisible ou résolution insuffisante = **bloquant** ; floue, sombre, reflet = conseil de reprendre. Lecture Tesseract locale (`KYC_FLOW_OCR`) : **indications seulement** (type de pièce, date d'expiration, nom) ; le texte lu n'est jamais conservé. « Envoyer » crée les pièces « en attente » et programme l'analyse assistée pour l'examinateur. |
| 5 | Vérification faciale | **seulement si `BIOMETRIC_ENABLED`**, avec consentement explicite (écran du module biométrique) ; l'alternative « vérification par l'équipe » reste toujours proposée. Aucune validation faciale automatique. Désactivée : étape « non requise ». |
| 6 | Revue humaine | l'équipe approuve ou refuse chaque face. Refus → « Nouvelle pièce demandée » avec le motif ; de nouvelles photos rouvrent le dossier (les pièces refusées restent dans l'historique, rien n'est supprimé). |
| 7 | Activation | règle unique `handy.eligibility` : affiche les blocages réels et l'action corrective. |

API (compte connecté, son propre dossier uniquement) : `GET|PATCH /handy/me/kyc/`, `POST /handy/me/kyc/capture/` (side, file),
`POST /handy/me/kyc/send/`, `POST /handy/me/kyc/restart/`. Limite : `THROTTLE_KYC_FLOW` (30/min). Les pièces déposées avant le parcours
(ancien écran « Mes documents ») sont prises en compte : pièce approuvée = identité vérifiée, pièce en attente = en revue.

## Éligibilité : quatre notions distinctes

`eligibility_summary(profile)` (dans `handy/eligibility.py`, servi par `/me/dashboard/` → `provider.eligibility` et `/me/services/`) :

- **Profil complet** : présentation, spécialités, expérience, zone, photo (5 éléments que l'artisan renseigne) ;
- **Identité** : `draft | pending | rejected | approved` (pièce d'identité uniquement — un justificatif professionnel en attente n'affiche
  plus « vérification en cours » à un artisan déjà vérifié) ;
- **Autorisation de publication** = `is_publishable` (profil complet + identité + validation finale de l'équipe + compte actif), avec la liste
  des blocages (`profile_incomplete`, `kyc_draft|pending|rejected`, `approval_pending`, `account_inactive`) et leur action
  (`edit_profile`, `verify_identity`, `contact_support`, ou aucune quand il suffit d'attendre l'équipe) ;
- **Offres** : créées, actives, publiées (= actives si la publication est autorisée) ; chaque offre de `/me/services/` porte son état
  (`published`, `waiting` = en attente d'autorisation, `inactive`).

Le Back-Office (fiche KYC) affiche l'identité déclarée à côté des pièces, à comparer — jamais une preuve.
