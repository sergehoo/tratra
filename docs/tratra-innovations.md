# Tratra ID, Trust, Live et Business — exploitation

Quatre modules s'appuient sur les mêmes comptes, la même règle d'éligibilité (`handy/eligibility.py`) et les mêmes API pour
le web (Next.js) et le mobile (Flutter). Rien n'est simulé : chaque valeur affichée vient de la base.

## Tratra Trust (`trust/`)
- Badges **VERIFIE** (KYC approuvé + profil complet + compte actif), **EXPERT** (justificatifs approuvés par l'équipe + résultats),
  **SUR** (ponctualité, litiges, avis mesurés), cumulables ; attribués et retirés automatiquement (signaux = retrait immédiat,
  tâche périodique `trust.tasks.reevaluate_all_profiles`), historique `BadgeAward` et journal `AuditEvent`.
- Critères modifiables dans l'administration (`TrustConfig`). Score 0-100 publié seulement s'il repose sur au moins un résultat
  client mesuré ; les données manquantes ne pénalisent pas.
- API : `GET /handy/handymen/{id}/trust/` (public), `GET /handy/me/trust/` (artisan), filtre `?badge=` et tri `?sort=trust` sur `/services/`.

## Tratra ID (`trust/identity.py`)
- Identifiant `TR-XXXX-XXXX`, QR permanent (URL `PUBLIC_WEB_URL/verify/<code>`), badge PDF A4. Validité recalculée à chaque
  vérification (suspension/KYC invalide = révocation immédiate). QR de mission : 15 min, usage unique, lié à une réservation.
- API : `/me/tratra-id/`, `/me/tratra-id/badge.pdf`, `/verify/id/<code>/` (public, limité), `/bookings/{id}/identity-pass/`, `/verify/pass/`.
- **À configurer en production : `PUBLIC_WEB_URL`.**

## Tratra Live (`live/`)
- Suivi consenti : l'artisan n'est localisé qu'après « Je suis en route », jusqu'à son arrivée ; le client partage sa position
  seulement s'il le souhaite (retrait = effacement). Aucune position hors mission active.
- Temps réel : WebSocket `/ws/live/<id>/` (billet signé 60 s) + repli `GET /bookings/{id}/live/`. Serveur ASGI requis (daphne).
- ETA : `ROUTING_OSRM_URL` (OSRM auto-hébergé) sinon estimation à vol d'oiseau étiquetée `estimate`.
- `CHANNELS_USE_REDIS=1` pour Redis en développement (la production utilise Redis par défaut). Purge des positions : 24 h après la
  mission, 6 h si elle reste ouverte (`live.tasks.purge_positions`).
- Cartes : tuiles OpenStreetMap par défaut — **à remplacer en production** (`NEXT_PUBLIC_MAP_TILES`, `--dart-define=MAP_TILES=`).
- Limites : push mobile = nécessite la configuration FCM ; le suivi mobile fonctionne application ouverte (premier plan).

## Tratra Business (`business/`)
- Organisation, rôles (propriétaire, administrateur, responsable de site, validateur, demandeur, finance, lecteur), périmètre par site.
  Isolation stricte : sans adhésion active, l'organisation n'existe pas (404).
- Demandes d'intervention → validation hiérarchique configurable → affectation d'un artisan éligible (réservation réelle) → suivi,
  SLA (contrat ou défaut par priorité), budgets, préventif (`business.tasks.run_preventive_plans`), facturation consolidée, KPI, audit.
- Un plan d'abonnement payant ne s'active jamais sans paiement (`POST /subscriptions/` → 402).
- API : `/handy/business/orgs/...` (voir `business/urls.py`).
