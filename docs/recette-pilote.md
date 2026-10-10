# Recette du pilote — parcours complet

Objectif : prouver, sur le **staging** et sur de **vrais téléphones**, que le parcours **client → réservation → artisan → mission → paiement → avis** et le
**contrat de longue durée** fonctionnent de bout en bout, avec leurs notifications. Rien ici ne s'exécute en production.

Deux niveaux, dans l'ordre :

1. **Recette automatisée (5 min)** — le même scénario que le test `handy/test_recette_pilote.py`, joué par HTTP réel contre le staging.
   Si elle échoue, inutile de sortir les téléphones.
2. **Recette manuelle (≈ 2 h)** — ce que l'automate ne peut pas faire : SMS réel, KYC humain, push application fermée, Android réel, Back-Office avec MFA.

> Principe d'honnêteté vérifié par la recette : un paiement **en espèces** ou **entre les parties d'un contrat** est *déclaré* par une partie puis *confirmé*
> par l'autre — il n'est **jamais** présenté comme « vérifié par un prestataire de paiement » (seuls Orange Money / MTN / carte, une fois qualifiés, le sont).

## 0. Préparation (une fois)

| Besoin | Comment |
|---|---|
| Staging sain | `scripts/staging/verify.sh` → 0 anomalie ; `manage.py celery_check --db` ; `manage.py security_preflight --strict` |
| 2 comptes de recette | **Client** `recette_client`, **Artisan** `recette_artisan` — créés par l'inscription réelle (SMS OTP **réel**, jamais contourné). Numéros dédiés à la recette. |
| KYC de l'artisan | l'artisan dépose sa pièce d'identité ; un administrateur la **valide** dans le Back-Office (le KYC reste humain) ; profil complet + 1 service publié |
| 1 compte tiers | `recette_tiers` (client) — sert aux contrôles d'isolation (il ne doit rien voir) |
| 1 compte administrateur | rôle attribué, **MFA activée** (voir `docs/securite-admin.md`) |
| Téléphones | 1 Android réel (APK pilote : `tool/build_pilot_apk.sh`), idéalement 1 second appareil pour l'autre rôle ; notifications autorisées |
| Push | `manage.py push_check --token` vert ; appareil connecté au moins une fois avec chaque compte (enregistrement du jeton) |

## 1. Recette automatisée

```bash
export RECETTE_CLIENT='recette_client'    RECETTE_ARTISAN='recette_artisan'    # identifiant, e-mail ou +225…
read -rs RECETTE_PASSWORD && export RECETTE_PASSWORD                            # saisi sans écho, jamais dans l'historique
python3 scripts/pilot/recette_api.py --api https://api-staging.<domaine>/handy            # tout le parcours
python3 scripts/pilot/recette_api.py --api https://api-staging.<domaine>/handy --only contract
```
Attendu : `Recette terminée : 47/47 contrôles verts.` (code 0). Au premier écart : l'étape et la réponse du serveur, code 1.
Elle crée des données de test (une réservation terminée, un contrat) : comptes de recette uniquement.

## 2. Recette manuelle

Cocher chaque ligne ; noter toute anomalie (étape, appareil, capture) dans le journal en fin de document.

### A. Comptes
| # | Qui / où | Action | Attendu |
|---|---|---|---|
| A1 | Client, Android | Créer le compte (téléphone → code SMS) | SMS reçu < 1 min ; code accepté ; mauvais code refusé ; 6ᵉ essai bloqué |
| A2 | Artisan, web | Créer le compte, déposer la pièce d'identité, compléter le profil, publier un service | Statut KYC « en attente » ; service **non visible** du public tant que le KYC n'est pas approuvé |
| A3 | Admin, Back-Office | Valider le KYC | L'artisan est notifié (push) ; son service apparaît dans le catalogue |

### B. Réservation
| # | Qui / où | Action | Attendu |
|---|---|---|---|
| B1 | Client, Android | Trouver l'artisan (catalogue / recherche), réserver (date, adresse, description) | Réservation « En attente » ; aucune donnée fictive |
| B2 | Artisan, téléphone **application fermée** | — | **Push** « Nouvelle demande de réservation » dans les secondes ; toucher la notification ouvre la **mission** |
| B3 | Artisan | Accepter | Client : push « Réservation confirmée », ouvre **sa réservation** |
| B4 | Client / Artisan | Échanger 2 messages | Push « Message reçu » chez le destinataire seulement ; lien vers la conversation |
| B5 | Tiers | Ouvrir l'URL de la réservation | 404 (isolation) |

### C. Mission
| # | Qui / où | Action | Attendu |
|---|---|---|---|
| C1 | Artisan | « En route » puis partage de position (facultatif) | Client : suivi en direct, push « en route » / « arrivé » ; arrêt du partage à la fin |
| C2 | Client | Vérifier l'identité de l'artisan (QR de mission) | Vérification confirmée ; aucune donnée sensible affichée |
| C3 | Artisan | Démarrer l'intervention | Client : push « Intervention démarrée » |

### D. Paiement en espèces (déclaré → confirmé)
| # | Qui / où | Action | Attendu |
|---|---|---|---|
| D1 | Artisan | Carte « Paiement en espèces » → **Déclarer** (montant proposé = solde, photo du reçu facultative) | État « À confirmer » ; **aucun** bouton de confirmation côté artisan (« un paiement ne se confirme jamais soi-même ») |
| D2 | Client | Push « Paiement en espèces à confirmer » → ouvrir | Voir la déclaration, le justificatif (ouvre l'image ; un PDF s'ouvre **dans l'application**) |
| D3 | Client | **Contester** (motif obligatoire) | État « Contesté », motif visible des deux ; artisan notifié |
| D4 | Artisan | Déclarer à nouveau le montant exact | Nouvelle ligne ; l'historique garde la contestation |
| D5 | Client | **Confirmer** | État « Réglé en espèces » ; mention « Les espèces … ne passent pas par Tratra … pas un encaissement vérifié par un prestataire » ; **aucune** mention « vérifié » |
| D6 | Artisan | Page Gains | Aucun gain retirable créé par ces espèces |
| D7 | Admin | Back-Office → Finances → paiement / réservation | Bloc « Espèces entre les parties » en **lecture seule** ; aucun bouton de confirmation ; aucun justificatif |
| D8 | Tiers | Ouvrir l'URL du justificatif | 404 |

### E. Fin de mission et avis
| # | Qui / où | Action | Attendu |
|---|---|---|---|
| E1 | Artisan | Terminer la mission | Client : push « Intervention terminée — laissez un avis » |
| E2 | Client | Noter (5 étoiles + commentaire) | Avis publié ; artisan : push « Avis reçu » ; moyenne publiée seulement à partir de 3 avis |
| E3 | Artisan | Répondre (une seule fois) | Réponse visible ; second essai refusé |

### F. Contrat de longue durée
| # | Qui / où | Action | Attendu |
|---|---|---|---|
| F1 | Client (donneur d'ordre) | Publier un besoin longue durée (catégorie, planning, montant mensuel) | Brouillon invisible du prestataire ; publié : visible, **sans coordonnées** |
| F2 | Artisan | Candidater | Donneur d'ordre notifié ; 2ᵉ candidature refusée |
| F3 | Client | Retenir la candidature, créer le contrat, le **proposer** | Artisan : push « Contrat proposé » → ouvre le **contrat** |
| F4 | Artisan | Lire les conditions, **accepter** | Acceptation liée à l'empreinte exacte ; modification des conditions entre-temps → refus `terms_changed` |
| F5 | Les deux | Onglet Rémunération | Échéances générées ; « Tratra ne verse ni n'encaisse rien » |
| F6 | Client | Déclarer un **acompte** (photo ou **PDF** de reçu facultatif) | « À confirmer » ; plafond d'avance respecté |
| F7 | Artisan | Ouvrir le PDF (Android) | Lecture **dans l'application** ; copie temporaire supprimée à la fermeture |
| F8 | Artisan | **Confirmer** le paiement | « Confirmé » avec la mention « Tratra ne vérifie pas ce paiement … » — jamais « vérifié » |
| F9 | Les deux | Planning : demander un congé, valider ; déclarer une présence | Aucune position GPS ; confirmations par la contrepartie |
| F10 | Attendre le prochain tick horaire (ou `tasks.run()`) | — | Pushs « échéance à venir » une fois par partie ; rejeu sans doublon |

### G. Notifications et liens profonds — application **fermée**, **en arrière-plan**, **ouverte**
| Événement | Destinataire | Ouvre |
|---|---|---|
| Nouvelle demande de réservation | Artisan | Mission |
| Réservation confirmée / démarrée / terminée | Client | Réservation |
| Message | Autre partie | Conversation |
| Espèces déclarées / confirmées / contestées | Contrepartie / auteur | Réservation (client) ou mission (artisan) |
| Annonce (Back-Office) | Public ciblé | Annonce |
| Contrat proposé / accepté / actif ; échéance à venir ou en retard ; paiement à confirmer | Parties | Contrat |

Pour chaque ligne : (1) application fermée → notification affichée, un seul exemplaire ; (2) toucher → bon écran ; (3) préférences : couper la catégorie « Contrats »
→ plus de push mais l'historique in-app reste.

### H. Résilience Android
| # | Action | Attendu |
|---|---|---|
| H1 | Mode avion pendant une action (déclaration d'espèces) | Message clair, rien n'est affiché comme réussi ; rejeu sans doublon au retour du réseau |
| H2 | Tuer l'application, relancer | Session conservée ; carte « Activité en cours » ; reprise de la mission/du contrat |
| H3 | Relancer **sans réseau** | Dernière activité connue, marquée « hors ligne, non vérifié » ; resynchronisation automatique au retour |
| H4 | Déconnexion volontaire puis connexion avec l'autre compte | Aucune donnée du compte précédent ; jeton push réenregistré pour le bon compte |
| H5 | Ouvrir un PDF puis tuer l'application | Au lancement suivant, plus aucune copie temporaire (`adb shell run-as … ls cache` sur un APK debug) |

### I. Back-Office et sécurité
| # | Action | Attendu |
|---|---|---|
| I1 | Connexion administrateur | Écran de double authentification ; code faux refusé ; code de secours à usage unique |
| I2 | Rôles | Chaque administrateur n'a que les modules de son rôle ; `manage.py security_preflight --strict` → 0 problème |
| I3 | Finances / Engagements | Aucun bouton « confirmer un paiement » ; remboursement par le séquestre existant uniquement |
| I4 | Journal d'audit | Les opérations sensibles apparaissent avec auteur et motif |

## 3. Critères de sortie (go / no-go du pilote)

- Recette automatisée **verte** sur le staging ; toutes les lignes A–I cochées, ou anomalie classée **non bloquante** par le responsable produit.
- **Bloquants** : un paiement présenté comme « vérifié » alors qu'il ne l'est pas ; une donnée visible d'un tiers ; une notification dupliquée ou perdue (application fermée) ;
  un justificatif accessible sans authentification ; un compte administrateur sans MFA.
- Sauvegarde **testée** (`scripts/staging/backup.sh` puis restauration sur une base jetable) et `rollback.sh` répété une fois.

## 4. Après la recette

Désactiver (sans supprimer) les comptes `recette_*` ; garder leurs données pour l'analyse des anomalies ; consigner le résultat :

| Date | Testeur | Appareil / version | Lignes en échec | Décision |
|---|---|---|---|---|
| | | | | |
