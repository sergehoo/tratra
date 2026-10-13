# TODO Tratra — état réel au 11 oct. 2026

Aucun push, aucun déploiement. Tout est en commits locaux sur `feat/compte-unique-kyc`.

## Terminé et vérifié
- Refonte du Back-Office : navigation en 7 rubriques, tableaux triables, filtres dans l'URL, actions par ligne et groupées, fiches à onglets, coordonnées complètes pour le Super Admin avec trace d'audit (voir `docs/backoffice.md`).
- Correctif des compteurs de statut : ils se rafraîchissent au rechargement seulement, plus à chaque filtre (commit 529875f). Cela évite les rafales de requêtes qui provoquaient des 429.
- Vérifications : `tsc` OK ; `npm run test:bo` 11/11 ; backend `backoffice` 93 tests OK (avant le correctif des compteurs, qui ne touche que le front) ; balayage visuel à 1440 et 390 px, sans anomalie sur les 36 pages contrôlées.
- SMS Orange avec bascule automatique depuis Twilio (`SMS_BACKEND=twilio,orange`), commit e9f5ed0.

## Étape 1 (Back-Office) — vérifiée le 11 oct. 2026
- Balayage visuel : 36 pages à 1440/390 px et 18 pages à 1280/768 px, sans débordement, troncature ni erreur console. Largeur 1920 : page Utilisateurs seulement.
- `interact.mjs` : tous les scénarios OK (recherche, tri, filtres dans l'URL, fiche à 6 onglets, palette Ctrl+K, export CSV, menu de ligne, sous-menu Retraits). Un KO sur la recherche lors du premier chargement à froid du serveur de dev ; rejoué isolément, il passe (25 → 1 ligne, `?q=awa`).
- `roles.mjs` : 6 rôles sur 6 conformes (menu = modules autorisés, module interdit refusé, 0 erreur JS).
- Actions : suspension puis réactivation d'un compte depuis la console, vérifiées en base ; audit `backoffice.user.suspended` / `reactivated` avec auteur et motif.
- Backend `backoffice` : 93 tests OK. `tsc` OK. Build de production OK.

## Étapes de la reprise (11 oct. 2026) — état réel
- **Étape 2 — Compte unique : fait.** « Proposer un service » / « Mes services » / « Gérer mes prestations » remplacent « Devenir artisan » (web et Flutter) ; plus d'identifiant technique affiché ; libellé « Membre » ; liste Utilisateurs unique du Back-Office (services proposés, missions réalisées, KYC, badges Trust, réputation, litiges ouverts, filtres « propose / ne propose pas de services » et KYC). Règles KYC inchangées. Reste : photo modifiable, nom/prénom, préférences et confidentialité regroupés dans un seul écran Flutter (raccourcis web faits).
- **Étape 3 — Adresses : fait** (backend, web, Flutter). Principale/secondaires/favorites, autocomplétion et géocodage configurables (cache, limite, panne => saisie manuelle), sélection sur carte, position actuelle avec consentement (lecture unique), adresse différente par réservation (web). Non fait : sélecteur d'adresses enregistrées dans le parcours de réservation Flutter (la position et la saisie manuelle fonctionnent).
- **Étape 4 — Transport : fait** (backend, Back-Office, web, Flutter). Voir `docs/adresses-transport.md`. Désactivé par défaut ; tout est configurable ; sans OSRM (`ROUTING_OSRM_URL`) la distance est « indisponible » et le forfait de secours s'applique.
- **Étape 5 — Évaluations : fait** (backend, Back-Office, web, Flutter). Évaluation mutuelle par mission, notes masquées jusqu'à réciprocité ou 7 jours (`EVALUATION_REVEAL_DAYS`), scores sans moyenne sous 3 notes, contestation, surveillance proposée + décisions humaines avec recours, évaluation mensuelle des contrats (défaut 30 jours, invitations à chaque échéance et à la clôture). Limite : l'évaluation client → prestataire passe encore par l'écran « À rédiger » existant (photos) ; l'évaluation du demandeur par le prestataire est dans « Évaluations réciproques ».

- **Étape 6 — IA : fait pour le contrôle KYC/fraude et les recommandations ; Trust partiel** (backend, Back-Office, web, Flutter pour les recommandations). Routeur DeepSeek (principal) → Anthropic (repli) facultatif ; les documents KYC ne partent jamais sans `AI_KYC_EXTERNAL_ENABLED=true` + `AI_KYC_LEGAL_BASIS` ; OCR local Tesseract (paquets ajoutés au Dockerfile) ; analyse explicable (expiration, nom, date de naissance, complétude, fichier/numéro identique) ; dossiers de risque proposés (doublons par identifiants forts, KYC expirés, identité incomplète, activité anormale, réservations artificielles) et décisions humaines ; recommandations déterministes explicables. Voir `docs/ia-controle.md`. **Non testé en réel** : appels DeepSeek et Anthropic (aucune clé en recette ; testés par simulation), OCR sur de vrais documents ivoiriens (formats de CNI à valider), image Docker reconstruite avec Tesseract.

## Reste à faire du brief
- Lot 4 (Trust) : l'IA ne propose pas encore de badges ni n'analyse la pertinence d'un justificatif de compétence par catégorie ; le moteur de badges existant est inchangé (aucun badge attribué par l'IA).
- Lot 8 (Back-Office) : tout y est réparti dans les modules existants (Utilisateurs, KYC > Risques, Avis > Surveillance, Réglages > Transport) ; pas de page « Doublons » dédiée ni de statistiques de réputation agrégées.
- Flutter : profil unifié et adresses enregistrées dans la réservation faits (13 oct. 2026). Reste : Firebase (push) à renseigner, bundle Play Store (.aab) avec clé d'upload, test sur appareil des parcours d'écriture (adresse, évaluation, déplacement) une fois MinIO joignable depuis le conteneur.
- Validation sur appareil Android non refaite pour cette série (aucun APK reconstruit).

## Vérification faciale KYC (13 oct. 2026) — état réel
- **Fait** (backend `biometrics/`, Back-Office web, Flutter) : consentement explicite et versionné ; sessions courtes à jeton limité (ordre des défis aléatoire, anti-rejeu, 3 essais/jour) ; captures chiffrées dans MinIO privé ; adaptateur fournisseur agnostique (`none` par défaut → revue humaine ; `http` générique) ; décision côté serveur sur les seuils ; jamais de validation par simulation ; alerte de fraude expliquée sans comparaison de visages entre comptes ; BO : droits séparés (`kyc.review` = statut/anomalies, `kyc.biometric` = scores, captures, décisions) ; badge VÉRIFIÉ conditionné par `KYC_BIOMETRIC_REQUIRED=true`. Voir `docs/kyc-biometrique.md`.
- **Vérifié sur appareil** (Galaxy S10+, build debug `.bio`, serveur de recette) : consentement, caméra avant, 6 étapes guidées, envoi, résultat « en attente de l'équipe » (fournisseur `none`), captures stockées chiffrées. Tests : Flutter 192 OK, `biometrics`/`backoffice`/`intelligence`/`trust`/`transport` 261 OK.
- **Non fait / à valider** : aucun fournisseur de liveness réel branché (contrat HTTP générique seulement : il faut un adaptateur et une clé du fournisseur choisi) ; seuils `BIOMETRIC_LIVENESS_THRESHOLD`/`BIOMETRIC_MATCH_THRESHOLD` à calibrer sur données réelles ; sens gauche/droite (`kLeftYawSign`) accepté sur un seul appareil ; parcours membre web absent (Flutter + BO seulement) ; iOS non testé ; DeepSeek/Anthropic testés par simulation uniquement.
- Image Docker : reconstruire (Tesseract, `cryptography`) et appliquer les migrations `biometrics` ; générer `BIOMETRIC_ENCRYPTION_KEY` hors Git avant d'activer `BIOMETRIC_ENABLED`.

## Messagerie temps réel + statuts éphémères (13 oct. 2026) — état réel
- **Fait** (backend, Back-Office, web, Flutter) : conversations privées uniques, messages persistants avec médias validés par leur contenu, états envoyé/distribué/lu, non-lus, WebSocket `ws/inbox/` avec billet signé, reprise et rattrapage par l'API, recherche et pagination, blocage et signalement ; messagerie administrateur (envoi individuel à un ou plusieurs membres, critères, aperçu, consentement, suivi par destinataire, audit, boîte de réponses) ; statuts texte/photo/vidéo/média+texte (24 h, 700 caractères, 30 s, configurables), visibilité contacts / élargie / exclusions / blocages, vues côté serveur et liste des lecteurs réservée à l'auteur, purge Celery, modération API. Voir `docs/messagerie-statuts.md`.
- **Vérifié** : backend (`handy/test_messaging.py`, `statuses/`, `backoffice/test_messaging.py`), Flutter 216 tests, `tsc` et build web OK ; parcours web testé dans le navigateur avec des données de recette (barre de statuts, visionneuse, message reçu en temps réel, message envoyé, découverte, mobile 375 px).
- **Non fait / à valider** : push FCM des messages (Firebase non configuré : non déclaré opérationnel) ; transcodage vidéo serveur (pas de ffmpeg : MP4/MOV ≤ 30 s seulement) ; page Back-Office de modération des statuts (API faite, pas d'écran) ; envoi de PDF depuis Flutter (réception et affichage faits) ; parcours iOS non testé ; mise en prod : appliquer les migrations `handy` 0046-0048, `statuses`, `backoffice` 0004 et vérifier que Redis/daphne servent `ws/inbox/`.

## Côté utilisateur (hors code)
- Serveur : `.env` des hôtes, `docker compose build tratrafrontend && up -d`, diagnostic Traefik/ACME de `minioapi.tratra.net`.
- Après un push explicite : `SMS_BACKEND=twilio,orange` et identifiants Orange sur le serveur.
- Firebase pour l'APK de notifications ; `.aab` Play Store seulement avec les infos de clé d'upload.
