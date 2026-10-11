# TODO Tratra — état réel au 11 oct. 2026

Aucun push, aucun déploiement. Tout est en commits locaux sur `feat/compte-unique-kyc`.

## Terminé et vérifié
- Refonte du Back-Office : navigation en 7 rubriques, tableaux triables, filtres dans l'URL, actions par ligne et groupées, fiches à onglets, coordonnées complètes pour le Super Admin avec trace d'audit (voir `docs/backoffice.md`).
- Correctif des compteurs de statut : ils se rafraîchissent au rechargement seulement, plus à chaque filtre (commit 529875f). Cela évite les rafales de requêtes qui provoquaient des 429.
- Vérifications : `tsc` OK ; `npm run test:bo` 11/11 ; backend `backoffice` 93 tests OK (avant le correctif des compteurs, qui ne touche que le front) ; balayage visuel à 1440 et 390 px, sans anomalie sur les 36 pages contrôlées.
- SMS Orange avec bascule automatique depuis Twilio (`SMS_BACKEND=twilio,orange`), commit e9f5ed0.

## Non vérifié, à refaire avant de livrer le Back-Office
- Balayage visuel : pages `engagements` (onglets postings, installments, disputes, evaluations) et `finance` → `security` non revues après le correctif des compteurs ; largeurs 1920, 1280 et 768 px non rejouées.
- `interact.mjs` (attente de la navigation « Retraits ») et `roles.mjs` (rôles non Super Admin) non exécutés.
- Tests fonctionnels d'actions avec contrôle en base et audit (suspension, masquage en lot, rejet de retrait, exports) non faits.
- Build de production non lancé : `NEXT_DIST_DIR=.next-build npm run build`, puis `git checkout frontend/tsconfig.json` s'il est réécrit.

## Nouveau brief (lots 1 à 9) — RIEN n'est commencé
Ordre prévu : 1 compte unique/profil → 2 adresses → 7 transport → 5 évaluations mutuelles → 3-4 IA fraude/KYC/Trust → 6 recommandations → 8 Back-Office → tests.
- Lot 1 : la distinction client/artisan existe déjà côté compte unique ; reste à chercher les libellés « Devenir artisan » / « compte professionnel » dans `frontend/src` et `flutter_tratra/lib` (la recherche n'a pas abouti), à retirer l'affichage du username, et à ajouter dans le Back-Office les filtres « propose des services », nombres de services et de missions, et badges Trust.
- Lots 2 à 8 : tout est à faire.
- Principes à respecter : migrations additives, droits vérifiés côté Django, consentement explicite pour la localisation, aucun badge ni sanction décidés par l'IA seule, aucun tarif codé en dur, tarif transport recalculé côté serveur, aucune dépendance obligatoire à une IA externe.

## Côté utilisateur (hors code)
- Serveur : `.env` des hôtes, `docker compose build tratrafrontend && up -d`, diagnostic Traefik/ACME de `minioapi.tratra.net`.
- Après un push explicite : `SMS_BACKEND=twilio,orange` et identifiants Orange sur le serveur.
- Firebase pour l'APK de notifications ; `.aab` Play Store seulement avec les infos de clé d'upload.
