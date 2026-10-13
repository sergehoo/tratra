# Vérification faciale biométrique du KYC

**Biométrie ≠ IA générative.** Les visages ne sont envoyés ni à DeepSeek ni à Anthropic : seul un fournisseur **spécialisé** de liveness et de comparaison visage/document, choisi par l'exploitant, les reçoit. DeepSeek (principal) et Anthropic (repli) ne servent qu'à l'analyse des **documents** et à la rédaction d'un rapport à partir des résultats de contrôles (jamais de nom, de numéro ni d'image).

## Principes de sécurité
- **OFF par défaut** (`BIOMETRIC_ENABLED=false`). Sans fournisseur réel (`BIOMETRIC_PROVIDER=none`), la session s'arrête à **EN ATTENTE de revue humaine** : aucune validation fondée sur une simulation. Aucun fournisseur « mock » n'est sélectionnable (refusé en production).
- Le client (Flutter) ne fait que **guider** : cadrage, rotation, sourire (ML Kit). Des mouvements ne prouvent pas une présence réelle ; la décision vient du **fournisseur** (liveness) puis des **seuils serveur** (`BIOMETRIC_LIVENESS_THRESHOLD`, `BIOMETRIC_MATCH_THRESHOLD`). Aucun secret n'est dans l'application.
- Résultat « satisfaisant » uniquement si le fournisseur renvoie liveness réussi ET correspondance ≥ seuil, sans indice de contournement (écran, masque, injection), avec une pièce **comparable** (image). Sinon : échec, non concluant ou revue humaine.
- Une validation biométrique ne valide **jamais** à elle seule le KYC ni un badge : l'approbation documentaire reste humaine ; le badge « Vérifié » exige en plus, si `KYC_BIOMETRIC_REQUIRED=true`, une vérification faciale satisfaisante **ou** une procédure alternative approuvée par un humain.

## Flux (API `/handy/kyc/biometric/…`)
1. `GET /` état : consentement (texte + version), pièce d'identité présente, session en cours, tentatives, résultat (jamais de score).
2. `POST consent/` consentement explicite, versionné (empreinte du texte, IP hachée) ; `DELETE consent/` le retire **et supprime toutes les captures**.
3. `POST sessions/` crée ou **reprend** une session (jeton court `X-Biometric-Token`, renvoyé une fois, nouveau jeton à chaque reprise ; ordre des défis aléatoire : face, 4 inclinaisons mélangées, sourire).
4. `POST sessions/<id>/captures/` (multipart `index`, `kind`, `file` JPEG) : qualité contrôlée (taille, éclairage, netteté), rang unique (rejeu refusé), image identique refusée, chiffrement Fernet, stockage privé.
5. `POST sessions/<id>/submit/` : décision serveur ; `POST human-review/` : alternative accessible (vérification par l'équipe, sans capture).
Limites : 3 sessions/jour et 6/semaine (configurables), 60 appels par jeton, session de 10 min.

## Fournisseur HTTP générique (`BIOMETRIC_PROVIDER=http`)
`POST {BIOMETRIC_API_URL}/verify` — `Authorization: Bearer <BIOMETRIC_API_KEY>`, multipart : `frames` (JPEG, une par défi), `document` (JPEG de la pièce), `session`, `challenges` (JSON). Réponse : `{"liveness": {"passed": bool, "score": 0..1}, "match": {"score": 0..1}, "flags": ["screen_replay", …]}`. À adapter par un adaptateur dédié (`biometrics/providers.py`) selon le fournisseur retenu (AWS Rekognition Face Liveness, Smile ID, Onfido, Sumsub…) ; l'interface `BiometricProvider` est volontairement minimale.

## Données et conservation
Captures chiffrées (`BIOMETRIC_ENCRYPTION_KEY`, Fernet) dans le bucket privé ; supprimées `BIOMETRIC_RETENTION_DAYS` (30) après la fin de la session, 2 jours après l'abandon, ou immédiatement au retrait du consentement. Tâche horaire `biometrics.tasks.tick`. Aucune URL publique ; accès Back-Office temporaire, déchiffré en mémoire, journalisé. Aucune base de reconnaissance faciale : aucune comparaison entre comptes.

## Back-Office (KYC > fiche > Vérification faciale)
- `kyc.review` : statut, anomalies, historique des tentatives, contrôles requis, rapport documentaire ; demander une nouvelle capture, des pièces complémentaires, ouvrir une revue manuelle.
- `kyc.biometric` (**Super Admin** par défaut) : scores, captures, approuver (après contrôles : pièce d'identité approuvée, aucun dossier de risque biométrique actif), refuser, approuver la procédure alternative. Tout est audité.
- Alertes explicables (Risques et fraudes) : tentatives répétées, images rejouées, enchaînement trop rapide, indices techniques du fournisseur.

## Variables
Voir `.env.staging.example` (`BIOMETRIC_*`, `KYC_BIOMETRIC_REQUIRED`, `THROTTLE_BIOMETRIC`). Générer la clé : `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` (la perdre rend les captures illisibles).
