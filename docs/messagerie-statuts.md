# Messagerie temps réel, messagerie administrateur et statuts éphémères

Tout réutilise l'existant : modèles `Conversation` / `Message` de `handy`, Channels (ASGI + Redis), `handy.notifications` (centre de notifications + push FCM), stockage objet « default » (MinIO, URLs signées à durée limitée), Celery beat. Aucun doublon de modèle ni de service.

## 1. Messagerie (`handy/messaging.py`, `handy/api/messaging.py`)

| Besoin | Réalisation |
|---|---|
| Conversations privées uniques | `Conversation.kind` (`booking` / `direct` / `support`) + `pair_key` unique (`min:max` des identifiants, `support:<id>`). `POST /me/conversations/ {user}` renvoie TOUJOURS le même fil pour deux membres. |
| Qui peut écrire à qui | un membre en relation (voir « contact »), un prestataire publié, ou l'auteur d'un statut élargi qui accepte les réponses. Sinon `403 not_reachable`. Quota quotidien de nouvelles conversations (`MESSAGE_NEW_CONVERSATIONS_PER_DAY`). |
| Messages persistants | `Message` (+ `client_id`, `kind`, `attachment*`, `delivered_at`, `read_at`, `via_staff`, `context`). Rien n'est supprimé à la fermeture de l'application. |
| Texte et médias | image JPEG/PNG/WebP (réencodée, EXIF/GPS retiré, 1600 px max), vidéo MP4/MOV (durée mesurée dans le conteneur), PDF. Le type vient des OCTETS du fichier, jamais du nom ni du `Content-Type` (`handy/media/validate.py`). |
| États d'envoi | `sent` → `delivered` (accusé de l'appareil : `ack` WebSocket ou `POST /me/messages/delivered/`, ou rattrapage `sync`) → `read` (`POST /me/conversations/<id>/read/`). |
| Idempotence | `client_id` (UUID) : renvoyer après une coupure réseau ne crée jamais de doublon (contrainte unique `(conversation, sender, client_id)`). |
| Non-lus | `unread` par conversation, `unread_total` ; `GET /me/messages/unread/`. |
| Temps réel | `ws/inbox/?ticket=` : une connexion par membre, billet signé de 60 s (`POST /me/realtime/ticket/`), évènements `message`, `read`, `delivered`, `status`, `status_view`. Lecture seule hormis `ping` et `ack`. |
| Reconnexion / secours | clients : reconnexion progressive (1→30 s) + évènement `resync` ; `GET /me/messages/sync/?after=<id>` rejoue ce qui a été manqué ; sondage tant que la WebSocket est coupée. L'API REST reste la source de vérité. |
| Recherche, pagination | `GET /me/conversations/?q=&page=` (nom ou contenu), `GET /me/conversations/<id>/messages/?before=<id>&limit=&q=` (curseur), `GET /me/messages/search/?q=`. |
| Blocage, signalement | `UserBlock` (dans les deux sens : plus de message, de contact ni de statut visible) ; `POST /me/conversations/<id>/report/` crée un `Report` de modération existant. |
| Isolation | chaque lecture/écriture filtre sur la participation ; `/handy/conversations/` est en lecture seule, `/handy/messages/` n'accepte que lecture et envoi (ni modification ni suppression) et passe par `messaging.send`. |
| Notifications | `message_created` → `notify` (base persistante + push FCM si Firebase est configuré, préférences respectées). Un message de l'équipe s'affiche « Équipe Tratra ». |

### Relation « contact Tratra » (`handy/contacts.py`)
Aucun nouveau système de relations : deux membres sont en contact s'ils ont une réservation acceptée (confirmée, en cours, terminée), un contrat d'engagement, une candidature retenue, ou ont chacun écrit dans une même conversation. Les blocages l'annulent. Résultat mis en cache 2 min par membre, invalidé à chaque nouveau message ou blocage.

## 2. Messagerie administrateur (`backoffice/staff_messaging.py`, `backoffice/api_messaging.py`)
- Droits : `messages.send` (support, ops, super admin : un ou jusqu'à 20 membres choisis, réponses) ; `messages.bulk` (ops, super admin : critères ou plus de 20 destinataires).
- Chaque destinataire reçoit SON message dans SON fil `support` (« Équipe Tratra ») : jamais de groupe, jamais de liste de destinataires exposée ; l'identité de l'agent n'est jamais montrée au membre.
- Critères autorisés : type de membre, ville déclarée, état KYC, offre de services, compte vérifié, activité récente, recherche par nom. Toute autre clé est refusée.
- Aperçu obligatoire côté interface (`POST /backoffice/messages/preview/`) : nombre réel de destinataires, ignorés (sans consentement marketing pour une promotion, compte inactif), exemples.
- Envoi : `POST /backoffice/messages/send/` → lot `StaffMessageBatch` + une `StaffMessageDelivery` par membre ; tâche Celery `backoffice.tasks.deliver_batch` (réessayable, idempotente : `client_id` dérivé du lot et du membre). Le résultat par destinataire (envoyé / distribué / lu / ignoré / échec) est consultable.
- Audit : `backoffice.message.batch_created` (nombre, nature, mode de sélection — jamais le texte), `backoffice.message.reply`.
- Boîte de réception : les réponses des membres arrivent dans `GET /backoffice/messages/threads/` (non lues, recherche) ; réponse au nom de l'équipe.

## 3. Statuts éphémères (app `statuses`)
- Types : texte (couleur de fond), photo, vidéo, média + texte. Plusieurs publications par membre (`STATUS_MAX_ACTIVE_PER_USER`).
- Réglages initiaux (variables d'environnement) : 24 h (`STATUS_TTL_HOURS`), 700 caractères, 30 s de vidéo, 10 Mo d'image, 30 Mo de vidéo, vues répétées désactivées.
- Validation serveur réelle : signature des octets, décodage de l'image, analyse du conteneur vidéo (`ftyp`, `moov`, `mvhd`, piste vidéo, rotation) ; durée et taille refusées au-delà. Les images sont compressées/réencodées côté serveur et côté client.
- Expiration : vérifiée à CHAQUE lecture (`expires_at > now`) ; la tâche `statuses.tasks.purge` (toutes les 15 min, réessayable) ne fait que libérer le stockage : média supprimé `STATUS_MEDIA_RETENTION_HOURS` (24 h) après expiration, lignes supprimées après `STATUS_ROW_RETENTION_DAYS` (30 j), fichiers orphelins de plus de 2 jours supprimés. Une suppression par l'auteur ou la modération retire immédiatement texte et média.
- Visibilité : contacts Tratra par défaut ; l'auteur peut élargir à tous les membres (page « Découvrir les statuts ») ; exclusions individuelles (sans prévenir le membre) ; blocages dans les deux sens.
- Vues : `POST /statuses/<id>/view/` n'est appelé QUE lorsque le statut est réellement affiché (jamais par le fil ni la découverte). Un lecteur = une vue ; son propre statut ne compte pas ; consultations répétées comptées seulement si `STATUS_REPEAT_VIEWS_ENABLED`, hors fenêtre anti-double-comptage. La liste nominative (`/statuses/<id>/viewers/`) n'est lisible QUE par l'auteur (404 pour tout autre).
- Réponse par message (si autorisée) : message privé avec le statut en contexte. Signalement : `StatusReport` ; modération Back-Office (`reviews.moderate`) : liste, retrait avec motif (auteur prévenu), classement sans suite.
- Fil d'accueil mis en cache 30 s, invalidé à la publication, la suppression, une vue, une exclusion ou un changement de relation.

## 4. Clients
- Web : en-tête (statuts, messages, notifications avec compteurs temps réel), barre des statuts sous l'en-tête de l'accueil, visionneuse plein écran (progression, pause, précédent/suivant, réponse, signalement, vues et lecteurs pour l'auteur), publication avec aperçu et progression d'envoi, page Statuts (Découvrir / Mes statuts / Confidentialité), messagerie temps réel, page Back-Office « Messagerie ».
- Flutter : mêmes écrans (`lib/messaging`, `lib/statuses`), WebSocket avec reprise et rattrapage, envoi idempotent avec « Renvoyer ».

## 5. Vérifications Docker (14 oct. 2026)
Pile jetable et isolée (projet Compose `tratra-wsverify` : PostGIS, Redis, API Daphne, worker Celery sur l'image construite par le `Dockerfile` du dépôt), supprimée ensuite. Constats :
- les migrations (`handy` 0046-0048, `statuses`, `backoffice` 0004) s'appliquent sur une base vierge ; la pile WebSocket est bien attachée à ASGI ; `ws/inbox/` refuse sans billet (403) et accepte avec un billet signé (101 puis `ready` avec le compteur de non-lus) ;
- diffusion temps réel entre PROCESSUS : un message envoyé depuis un shell Django séparé, puis depuis le worker Celery (envoi d'équipe à deux membres, deux fils distincts), arrive sur la WebSocket ouverte dans Daphne via Redis ;
- redémarrage de Redis : la connexion est fermée proprement, le client reconnecte, `ready` donne le bon compteur ; redémarrage de Daphne : fermeture détectée, reconnexion, rattrapage `sync` sans doublon, renvoi avec le même `client_id` sans second message ;
- l'abonnement au groupe Redis expire (24 h) ou se perd : la connexion le renouvelle toute seule (toutes les 2 minutes et à chaque `ping`), couverte par des tests.
Contrôle de routage en environnement réel : `scripts/staging/ws_check.py --api <url> [--inbox]` (billet de messagerie avec `TRATRA_TOKEN`).

## 6. Limites connues
- Pas de transcodage vidéo côté serveur (pas de ffmpeg dans l'image) : seules les vidéos MP4/MOV de moins de `STATUS_VIDEO_MAX_SECONDS` sont acceptées.
- Les notifications push de messages ne sont opérationnelles qu'avec Firebase configuré ; non testées en réel ici.
- Le sens « lu » d'un message d'équipe n'est visible que de l'équipe.
