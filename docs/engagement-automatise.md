# Engagement automatisé

Messages déclenchés par des **événements réels** (inscription vérifiée, profil, identité, offres, commandes, activité) pour amener
chaque compte à l'étape suivante : profil complet, pièce d'identité transmise, première offre, première commande, avis, retour
après une inactivité. Canaux : **message dans l'application** (module Annonces) et **push FCM si autorisé**. **Jamais de SMS.**

Code : app `campaigns/` (modèles, déclencheurs, moteur, bibliothèque), Back-Office `backoffice/api_campaigns.py`, page web
`/backoffice/campaigns` (« Communication › Engagement automatisé », droit `announcements.manage` : rôle marketing, Super Admin).

## Fonctionnement

Tâche Celery `campaigns.tasks.tick` (file `bulk`, beat toutes les 10 minutes) :

1. **Programmer** : pour chaque campagne active et dans sa période, les comptes dont l'événement déclencheur tombe dans la fenêtre
   `[maintenant − délai − fenêtre ; maintenant − délai]` reçoivent un envoi « programmé ». Contrainte d'unicité
   `(campagne, compte, référence)` : rejouer la tâche ne duplique rien. La référence distingue les objets (`booking:12`,
   `doc:7`, `login:20261025`) ; vide = une fois par compte.
2. **Envoyer** (verrou `skip_locked` : deux workers ne traitent jamais le même envoi), dans cet ordre :
   campagne toujours active → compte actif → **objectif déjà atteint : arrêt** → désinscription → consentement marketing →
   heures autorisées (report) → priorité opérationnelle (report de 2 h) → écart minimal (report) → push seulement sous la limite
   hebdomadaire, sinon message dans l'application seul (motif `push_quota`). Au-delà de 12 reports, l'envoi est abandonné.
3. **Mesurer** : un envoi dont l'objectif est atteint ensuite est marqué « converti » (taux affiché dans le Back-Office).

Chaque campagne a une **annonce support** (`Announcement.source = "campaign"`, invisible dans la liste des annonces manuelles) :
elle porte le message du flux de l'application et le lien du push. Désactiver la campagne annule ses envois programmés et retire
le message des flux ; un push encore en file ne part plus.

## Déclencheurs et objectifs

| Déclencheur | Audiences | Événement | Arrêt (objectif) |
|---|---|---|---|
| `welcome` | toutes | inscription (téléphone vérifié) | message reçu |
| `profile_incomplete` | clients, artisans | inscription, profil incomplet | profil complet |
| `kyc_pending` | artisans | inscription, pièce non transmise | pièce transmise |
| `kyc_rejected` | artisans | pièce refusée (une fois par pièce) | nouvelle pièce transmise |
| `first_service` | artisans | inscription, aucune offre | première offre |
| `first_order` | clients, entreprises | inscription, aucune demande | réservation, demande Flash ou demande Business |
| `review` | clients | prestation terminée sans avis (une fois par réservation) | avis laissé |
| `artisan_reviews` | artisans | dernière prestation terminée, aucun avis | premier avis reçu |
| `inactive` | toutes | aucune connexion depuis N jours (un message par épisode) | nouvelle connexion |
| `news` | toutes | activation ou date de début (une fois par compte) | — |

Ciblage : audience (rôle du compte unique), communes **déclarées** (jamais le GPS), étape de progression
(`verified`, `profile_complete`, `kyc_approved`, `publishable`, `active`). Seuls les comptes actifs, non staff, au téléphone vérifié.

## Règles anti-spam

- **2 push d'engagement par semaine et par compte au plus** (`CAMPAIGN_PUSH_WEEKLY_LIMIT`), annonces promotionnelles manuelles comprises.
- **Consentement** : une campagne « marketing » n'est envoyée qu'aux comptes ayant donné leur consentement marketing ; retiré, le
  message disparaît du flux et aucun push ne part.
- **Désinscription** : catégorie de notification « Conseils, rappels et nouveautés » (`tips`) dans les préférences de l'application
  et du site. Désactivée = plus aucun message d'engagement.
- **Heures** : envoi seulement entre `CAMPAIGN_SEND_HOURS` (défaut 9-20) dans le fuseau `TIME_ZONE` (Africa/Abidjan) ; sinon report
  au prochain début de plage.
- **Priorité absolue** à Tratra Flash, aux réservations et à la sécurité : aucun message pendant une demande Flash ouverte, une
  réservation en cours ou dans les 24 h, ni dans les 2 h suivant une notification Flash, réservation, compte, suivi ou paiement.
- **Fréquence** : écart minimal (`min_gap_hours`) avec le précédent message d'engagement reçu.

## Nouveautés et versions de l'application

Le serveur et le site sont livrés ensemble : une fonction récente est en ligne côté serveur et web dès que la version qui la contient
est déployée. L'application, elle, n'est à jour que lorsque chaque utilisateur l'a mise à jour. Le registre `handy/features.py`
liste les fonctions qu'une campagne peut **annoncer** (`feature`) ou **ouvrir** (`flash_order` → `flash`, `panne` → `panne`,
`favorites` → `favorites`, `badge` → `tratra_id`, `engagements` → `engagements`) ; codes : `flash`, `panne`, `favorites`,
`tratra_id`, `engagements`, `service_modes`, `catalogue_families`.

- L'application annonce au serveur les fonctions dont elle a l'écran (capacités de l'appareil, `POST /devices/`, à chaque
  démarrage) — à partir du build 13.
- Une campagne qui annonce ou ouvre une fonction ne programme que les comptes qui peuvent l'ouvrir : un téléphone dont l'application
  la connaît, ou aucun téléphone (compte qui n'utilise que le site). Les autres **attendent** : ils sont visés au premier passage qui
  suit leur mise à jour (rien n'est enregistré pour eux d'ici là).
- Le push d'une annonce ou d'une campagne qui conduit à une fonction ne part que vers les téléphones à jour (statut
  `outdated_app` sinon) : jamais un bouton qui n'ouvre rien sur une ancienne version.
- Le Back-Office affiche, par campagne, les téléphones à jour (« Appli à jour : n / N téléphones ») et, dans l'estimation, les
  comptes qui attendent la mise à jour. Une fonction inconnue du registre empêche l'activation.

## Bibliothèque

30 modèles (`campaigns/library.py`), **tous désactivés**, installés par la migration `campaigns.0002` (idempotente : un modèle
existant n'est jamais réécrit). L'équipe relit, ajuste et active depuis le Back-Office. Règles de rédaction : aucune promesse
invérifiable, aucun chiffre inventé, chaque bouton ouvre un écran du registre central (`handy/destinations.py`) accessible à
l'audience.

## Applications (liens et push)

- Le push d'une campagne part comme une **annonce** (`t = "announcement"`, `id` = annonce support, catégorie `tips`, canal Android
  `tratra_announcements`) : les versions déjà installées l'affichent (grande notification « rich1 ») et l'ouvrent sans mise à jour.
- Le bouton ouvre l'écran du registre (`tratra://<clé>` dans l'application, équivalent web) ; l'application et le site revérifient
  les droits du compte (`openDeepLink`).
- Nouvelle clé de lien : `panne` (« J'ai une panne »). Les applications qui ne la connaissent pas encore ouvrent les notifications.

## Back-Office

Liste (filtres statut, audience, déclencheur ; envoyés, objectifs atteints), éditeur (message, bouton, marketing, push, déclencheur
et audience modifiables seulement campagne désactivée, communes, progression, délais, fenêtre, écart, priorité, début, fin), aperçu
(notification et carte dans l'application), statistiques (programmés, envoyés, push, ouverts, objectif atteint avant / après envoi,
motifs de non-envoi), historique (prénom et initiale seulement), « Exécuter un passage » (mêmes règles que la tâche). Toute
modification est versionnée (409 en cas de conflit) et journalisée.

## Déploiement

1. Migrations : `handy 0065`, `announcements 0003`, `campaigns 0001` et `0002` (installe les 30 modèles désactivés).
2. Beat Celery : `campaigns-tick` (toutes les 10 minutes, file `bulk`) — le worker `bulk` doit tourner.
3. Variables : `CAMPAIGN_PUSH_WEEKLY_LIMIT`, `CAMPAIGN_SEND_HOURS` (l'ancienne `DEPLOYED_FEATURES` n'est plus lue).
   Migration `handy 0066` (statut de push « application à mettre à jour »).
4. Rien n'est envoyé tant qu'aucune campagne n'est activée dans le Back-Office.

## Tests

`campaigns/test_campaigns.py` : déclencheurs, ciblage, idempotence, consentement et désinscription, limite de push, heures,
priorité opérationnelle, écart minimal, arrêt après objectif, désactivation, nouveautés réservées aux applications à jour, bibliothèque, compatibilité
FCM (serveur simulé) et Back-Office.
