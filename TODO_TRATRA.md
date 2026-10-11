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

## Reste à faire du brief (lots 3, 4, 6, 8)
Ordre prévu : 1 compte unique/profil → 2 adresses → 7 transport → 5 évaluations mutuelles → 3-4 IA fraude/KYC/Trust → 6 recommandations → 8 Back-Office → tests.
- Lot 1 : la distinction client/artisan existe déjà côté compte unique ; reste à chercher les libellés « Devenir artisan » / « compte professionnel » dans `frontend/src` et `flutter_tratra/lib` (la recherche n'a pas abouti), à retirer l'affichage du username, et à ajouter dans le Back-Office les filtres « propose des services », nombres de services et de missions, et badges Trust.
- Lots 2 à 8 : tout est à faire.
- Principes à respecter : migrations additives, droits vérifiés côté Django, consentement explicite pour la localisation, aucun badge ni sanction décidés par l'IA seule, aucun tarif codé en dur, tarif transport recalculé côté serveur, aucune dépendance obligatoire à une IA externe.

## Côté utilisateur (hors code)
- Serveur : `.env` des hôtes, `docker compose build tratrafrontend && up -d`, diagnostic Traefik/ACME de `minioapi.tratra.net`.
- Après un push explicite : `SMS_BACKEND=twilio,orange` et identifiants Orange sur le serveur.
- Firebase pour l'APK de notifications ; `.aab` Play Store seulement avec les infos de clé d'upload.
