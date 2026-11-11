# Tratra Flash — phase 3 : fiabilité et concurrence

Novembre 2026. Suite de la recherche façon VTC (rayons progressifs, propositions, contre-offres, désistement).
Aucune refonte : les règles métier et les délais (`DispatchConfig`) sont inchangés. Ce document dit ce qui est garanti,
ce qui a été mesuré, et ce qui reste un risque.

## 1. Ce qui est garanti (et par quel test)

Tests : `flash/test_reliability.py` (19), `flash/test_flash.py`, `flash/test_progressive_search.py`,
`flash/test_dispatch_scale.py` — 87 réussis avec `loadtest`. Flutter : `test/flash_countdown_test.dart` (19),
`test/flash_search_test.dart`, `test/flash_test.dart` — suite complète 434 réussis.

| Sujet | Garantie | Mécanisme |
|---|---|---|
| Ordre des états | Chaque évènement visible d'une demande porte un numéro croissant (`MissionRequest.seq`, migration `flash 0004`). Un message en double ou en retard n'est jamais appliqué ; une demande annulée ou close n'est jamais rouverte. | `seq` incrémenté sous verrou dans `log()` ; un seul message temps réel par transaction, envoyé après validation ; côté application `FlashRequestLive._outdated`. |
| Acceptations simultanées | N acceptations de la même demande : une seule gagne, une seule réservation, chaque perdant reçoit « déjà attribuée ». Un professionnel n'est jamais engagé deux fois au même moment. | Verrou de ligne sur la demande puis sur le professionnel, toujours dans le même ordre (pas d'interblocage constaté sous acceptations + refus + expiration + annulation mêlés). |
| Expiration pendant une acceptation | Une seule issue : acceptée OU expirée, jamais les deux. | Même verrou ; l'échéance est relue sous verrou. |
| Propositions et contre-offres | Toutes les propositions simultanées sont conservées ; une seule est finalement retenue ; le prix final est celui de la dernière proposition acceptée ; une réponse tardive est refusée explicitement. | `choose_quote`, `counter_offer`, `answer_counter` sous verrou ; états `quoted / countered / lapsed`. |
| Désistement | La demande est rouverte une seule fois, même si le désistement est rejoué en parallèle ; seules les propositions encore valables reviennent ; le professionnel qui s'est désisté n'est jamais resollicité ; une annulation du client et l'accord « au-delà de 30 km » sont respectés. | `resign` idempotent sous verrou. |
| Tâches répétées ou perdues | Une vague n'est envoyée qu'une fois même si la tâche est relancée ou exécutée deux fois ; une tâche perdue ou un canal temps réel hors service ne bloque jamais une recherche (le passage périodique rattrape). | Paliers datés en base (`next_step_at`), `expire_due` idempotent. |
| Notification tardive | Un appui sur une notification périmée reçoit une réponse explicite (« délai écoulé », « déjà attribuée ») et ne change rien. | `offer_view_payload` + codes d'erreur dédiés. |
| Délais affichés | Le serveur envoie son heure (`server_now`), le début et la fin de chaque délai ; l'application ne décompte jamais avec sa propre horloge. | `request_payload`, `offer_view_payload` ; Flutter `FlashDeadline`. |

## 2. Barre de délai (application)

`lib/flash/flash_deadline.dart` — remplace l'ancien compteur des missions.

- Pleine au départ, vide à l'échéance, temps restant `01:30 → 00:00` ; vert, puis orange, puis rouge (fondu entre deux couleurs).
- L'échéance est celle du serveur (`expires_at`), située par rapport à SON heure (`server_now`, à défaut `seconds_left`).
  Sans l'un ni l'autre : aucune barre. Rien n'est décompté — chaque image relit l'horloge — donc fermeture puis réouverture,
  arrière-plan, reconnexion et évènement WebSocket reprennent exactement au bon endroit.
- Un seul `Ticker` pour toutes les barres (`FlashPulse`), arrêté quand aucune n'attend ; une seule minuterie par barre pour
  l'échéance ; la barre ne demande plus d'images quand son écran est recouvert.
- À 0 : accepter, proposer un prix, répondre à une contre-offre, choisir, contre-offrir sont désactivés immédiatement, puis
  l'état réel est relu depuis l'API (le serveur reste seul juge : il garde sa tolérance de quelques secondes).
- Écrans : alerte de mission, « Mes propositions » (professionnel), propositions reçues (client : validité de la proposition
  et attente de réponse à une contre-offre).

## 3. Professionnels sollicités sur la carte

Pendant la recherche, le client voit apparaître les professionnels sollicités à mesure des vagues : pictogramme
travailleur / travailleuse, estompé après un refus ou une absence de réponse, marqué quand une proposition est reçue.

- Position **approchée** (arrondie côté serveur), jamais exacte ; aucune identité tant que le professionnel n'a rien proposé.
- Le genre est **déclaratif et facultatif** (`User.gender`, migration `handy 0067`) ; non indiqué → pictogramme neutre.
  Il est effacé avec le compte. Le formulaire de profil du site web ne le propose pas encore.

## 4. Recette sur téléphone (Galaxy S10+, copie `.recette`, base jetable, aucun SMS ni push réel)

Professionnel : barre cohérente avec le serveur à l'ouverture ; arrière-plan puis retour ; vert → orange → rouge ; à 0
« Le délai de réponse est écoulé. » et seul « Fermer » reste ; fermeture en direct quand un autre professionnel accepte ;
fermeture après coupure réseau puis reconnexion ; contre-offre reçue en direct avec sa barre ; après son échéance, « votre
proposition reste valable » ; rendu en paysage.

Client : carte de reprise de la recherche ; propositions avec leur validité ; à 0 « Proposition échue 00:00 » et boutons
désactivés aussitôt ; contre-offre et réponse reflétées en 2 s ; proposition close par le serveur → tuile estompée sans bouton.

Deux défauts constatés et corrigés :

1. Rechargement de « Mes propositions » à l'échéance : `setState` recevait une fonction asynchrone (assertion). Corrigé.
2. Une proposition close par le serveur (ou une contre-offre refusée) n'était relue qu'à la lecture périodique (30 s) :
   l'évènement ne changeait aucun compteur. Désormais, dès qu'une proposition est affichée, tout évènement la fait relire.

## 5. Performance mesurée (banc local, jamais la production)

`scripts/loadtest/run_local.sh flash 100,500,1000` — base dédiée, Redis dédié, aucun fournisseur SMS/push.
Machine : 8 cœurs, 8 Go, PostgreSQL 16.3 sur le même poste ; 20 000 professionnels dont 6 895 disponibles ; charge 6 processus × 8 fils.
**Ces chiffres décrivent ce poste, pas la production** : ils servent à comparer et à trouver les goulots, pas à annoncer une capacité.

Passage du 11 novembre 2026 (code tel que validé, `loadtest-results/flash-20261111-093334.json`) :

| Demandes simultanées | Création + 1re vague | Paliers suivants | Requêtes SQL / création |
|---|---|---|---|
| 100 | 14,7/s — p50 2,6 s, p95 5,1 s | 17/s — p50 2,2–2,3 s, p95 3,7–4,0 s | 54 |
| 500 | 6,6/s — p50 4,3 s, p95 17,7 s | 5,5–7,0/s — p50 4,0–5,8 s, p95 15–20 s | 54 |
| 1 000 | 7,3/s — p50 4,4 s, p95 13,8 s | 5,9–6,7/s — p50 4,7–6,2 s, p95 13–25 s | 54 |

- Toutes les opérations ont abouti (100 / 500 / 1 000 créations, autant à chaque palier) : aucune erreur.
- Le nombre de requêtes par opération est constant (54 à la création, 40 à 47 par palier) : pas de dérive avec le volume.
- **Les débits varient beaucoup d'un passage à l'autre sur ce poste** (8 Go, partagé avec d'autres travaux) : un passage
  précédent donnait 19,9/s à 100, 21,5/s à 500 et 3,2/s à 1 000. Seuls l'ordre de grandeur (quelques demandes à une
  vingtaine par seconde, délais de plusieurs secondes dès 500) et les invariants ci-dessous sont à retenir.

### Acceptations simultanées (la moitié des demandes, tous les professionnels alertés répondent en même temps)

| Demandes | Acceptations | Gagnantes | « Déjà attribuée » | « Déjà engagé ailleurs » | Délai (p50 / p95) | Verrous en attente (max) |
|---|---|---|---|---|---|---|
| 50 | 376 | 50 | 326 | 0 | 19 ms / 0,8 s | 13 |
| 250 | 1 767 | 250 | 1 515 | 2 | 99 ms / 2,3 s | 13 |
| 500 | 3 500 | 500 | 2 950 | 50 | 143 ms / 1,9 s | 6 |

Invariants vérifiés en base après chaque série : **0 demande avec deux acceptations, 0 professionnel avec deux réservations
au même moment, 0 proposition restée en attente** ; une réservation par demande (50 / 250 / 500). Chaque perdant a reçu une
réponse explicite ; aucun interblocage, aucune erreur. 4 requêtes SQL par acceptation perdante (47 pour la gagnante).

Annulations (demandes encore ouvertes de la moitié restante) : 50 / 250 / 488, toutes abouties, 10 requêtes SQL chacune, p95 ≤ 2 s.

### Goulot identifié

La recherche des candidats (`flash/services.py::candidates`) : 64 à 85 % du temps SQL. Elle charge tous les profils du métier
dans le rayon courant avec leur compte (≈ 0,1 s pour 900 profils à 5 km, ≈ 0,4 s pour 3 800 à 30 km), puis les classe en Python.
Essai fait : remplacer les jointures + `DISTINCT` par une sous-requête d'identifiants donne les mêmes profils dans le même
ordre mais ne gagne que 5 à 25 % — non retenu (gain trop faible pour toucher au cœur du classement).
Le vrai gain demanderait de borner le nombre de profils lus par palier (tri par distance en base, colonnes réduites) :
c'est un changement de la règle de classement, donc une décision produit, pas une correction.

Second point : le passage périodique global (`expire_due`) traite les demandes une à une, et chaque relance refait la
recherche des candidats (mesuré : 18 demandes en 4,3 s et 1 749 requêtes SQL à 100 ; 84 demandes en 25 s et 10 913 requêtes à 500 ; 168 demandes en 101 s et 24 046 requêtes à 1 000 — soit 0,2 à 0,6 s et 100 à 145 requêtes par demande). Les demandes restent correctes (chaque palier est daté, rien n'est envoyé deux
fois), mais quand des centaines de demandes arrivent à échéance ensemble, les vagues suivantes partent en retard.

## 6. Limites et risques résiduels

- **Nouvelle mission = push uniquement.** L'alerte d'une nouvelle mission arrive au professionnel par notification ; la
  WebSocket ne porte que les changements d'une alerte déjà connue (fermeture, contre-offre). Sans push (Firebase coupé), la
  liste doit être rouverte. Une notification en retard est sans danger (réponse explicite, rien ne change).
- **Notification système Android** : elle garde le compte à rebours natif du système (chronomètre de la notification),
  calé sur l'échéance du serveur ; la barre n'existe que dans l'application.
- **Carte de reprise** (accueil du client) : elle n'est cherchée qu'à la construction de l'accueil ; tirer pour actualiser
  ne la fait pas apparaître.
- **Rafale d'évènements** : trois évènements dans la même seconde déclenchent trois lectures de l'API ; seule la dernière est
  appliquée. Sans effet visible, léger surcoût.
- **Couleur** : autour de la moitié du délai, le fondu vert → orange passe par une teinte olive pendant quelques secondes.
- **Capacité** : sur un poste de ce type, la création plafonne entre 7 et 20 demandes par seconde selon le passage, et les
  délais de création dépassent plusieurs secondes dès 500 demandes simultanées. Aucune capacité de production n'est déduite de ce banc : à mesurer sur l'infrastructure réelle avant
  toute montée en charge (voir `docs/scalabilite-phase2.md`).
- **Verrous** : sous acceptations massives, jusqu'à 13 transactions ont attendu un verrou en même temps ; aucune n'a échoué,
  aucun interblocage. Lors d'un passage précédent, une erreur de connexion à la base (1 expiration sur 166) était apparue à
  1 000, poste saturé (100 connexions PostgreSQL au plus) ; elle ne s'est pas reproduite au passage suivant.

## 7. Déploiement

Migrations à appliquer : `flash 0003_progressive_search`, `flash 0004_request_seq`, `handy 0067_user_gender`.
Application : nouvelle dépendance Dart `clock`. Rien n'est poussé ni déployé : commits locaux uniquement.
