# Tratra AI — assistant du Back-Office et messagerie assistée

Tratra AI aide le personnel à **comprendre** la plateforme et à **préparer** ses décisions. Il ne décide ni n'exécute rien :
lecture seule, aucune suspension, suppression, validation KYC, remboursement ni envoi automatique.

## Activation

DeepSeek est le fournisseur principal, Anthropic le repli (mêmes clés que le contrôle intelligent) :

```
AI_PROVIDERS=deepseek,anthropic
AI_DEEPSEEK_API_KEY=…        # exclusivement côté serveur, jamais renvoyé ni journalisé
AI_ANTHROPIC_API_KEY=…
```

**Sans aucune clé** : le panneau affiche « IA non configurée », le bouton « Rédiger avec l'IA » est désactivé, et les **synthèses de gestion**
(règles, sans IA) restent disponibles. Interrupteur général : `AI_ASSISTANT_ENABLED=false`.

| Variable | Défaut | Rôle |
|---|---|---|
| `AI_ASSISTANT_PER_HOUR` / `AI_ASSISTANT_PER_DAY` | 30 / 150 | Questions par administrateur (comptées en base) |
| `AI_ASSISTANT_DAILY_TOKENS` | 150000 | Budget de jetons par 24 h et par administrateur |
| `AI_ASSISTANT_MAX_TOKENS` | 1024 | Longueur maximale d'une réponse du modèle |
| `AI_ASSISTANT_DEADLINE` | 90 | Échéance globale d'un tour, en secondes (outils compris) |
| `AI_ASSISTANT_RETENTION_DAYS` | 90 | Conservation de l'historique après la dernière activité |
| `AI_DRAFT_PER_HOUR` | 30 | Rédactions assistées de messages par heure et par administrateur |
| `AI_TIMEOUT` | 30 | Délai de lecture réseau vers un fournisseur |

## Fonctionnement

1. L'administrateur pose une question (`POST /handy/backoffice/assistant/chat/`, flux SSE : `meta`, `status`, `delta`, `done` | `error`).
2. Le serveur transmet au modèle la question, les 12 derniers échanges **réussis** et la liste des **outils autorisés pour ce compte**.
3. Le modèle peut demander des outils (4 tours et 6 appels au plus). Le serveur les exécute **en lecture seule**, puis renvoie les résultats
   comme **données non fiables**.
4. La réponse est diffusée au fil de l'eau, enregistrée dans l'historique **privé** de l'administrateur, avec les **sources** consultées.
5. Repli : si DeepSeek échoue **avant** d'avoir produit quoi que ce soit, Anthropic prend le relais. Après un début de réponse, une coupure
   n'est jamais « complétée » par un autre fournisseur : la réponse partielle est conservée et marquée en erreur.

Streaming : sous Daphne (ASGI) l'agent tourne dans un fil de travail et pousse ses événements dans une file lue par la boucle d'événements ;
sous WSGI, un générateur synchrone suffit. L'en-tête `X-Accel-Buffering: no` désactive la mise en tampon d'un éventuel proxy.

## Outils (lecture seule, droit du module exigé **à la liste et à l'exécution**)

| Outil | Droit | Contenu |
|---|---|---|
| `platform_overview` | `dashboard.view` | Membres, artisans, réservations, KYC, litiges (sections selon les droits) |
| `search_users`, `get_user_summary` | `users.view` | Recherche et fiche résumée (coordonnées masquées) ; filtre KYC : `kyc.review` |
| `kyc_overview`, `risk_cases` | `kyc.review` | File KYC, dossiers de risque (jamais de pièce ni de biométrie) |
| `bookings_overview`, `booking_anomalies` | `bookings.view` | Indicateurs, réservations bloquées, litiges anciens, annulations et paires répétées |
| `account_alerts` | `users.view` | Pic d'inscriptions, KYC en attente/expirés, dossiers prioritaires, signalements |
| `security_events` | `security.manage` | Axes (échecs, blocages, sources réduites), MFA, consultations sensibles, changements de rôles |
| `communications_overview` | `messages.send` | Réponses non lues, envois récents, notifications (si `notifications.view`) |

Droit d'accès à l'assistant : `assistant.use` (tous les rôles du Back-Office). Un rôle ne reçoit que les outils qu'il a le droit d'utiliser ;
un outil inventé ou non autorisé est refusé, jamais exécuté.

## Garanties de sécurité

- **Pas de SQL libre** : des fonctions fixes, des arguments validés (types, bornes, énumérations).
- **Lecture seule jusque dans la base** : les outils s'exécutent dans une transaction PostgreSQL `READ ONLY` à durée limitée.
- **Données minimisées** : coordonnées masquées pour tous les rôles (y compris Super Admin), adresses IP réduites (/24), aucune donnée
  biométrique ni document d'identité, clés sensibles retirées, textes libres bornés et masqués.
- **Secrets** : un secret collé dans une question (clé, jeton, mot de passe) est masqué **avant** envoi et avant enregistrement.
- **Injection de consignes** : résultats d'outils et textes d'utilisateurs présentés comme données ; aucun outil d'écriture n'existe ; liens
  de réponse limités au Back-Office ; rendu sans HTML.
- **Isolation** : une conversation n'est lisible que par son propriétaire (404 pour tout autre compte, super-administrateur compris).
- **Audit** (`backoffice.assistant.*`) : qui, quand, quels outils, quel fournisseur, combien de jetons — **jamais le texte**.
- **Limites** : questions par heure/jour, budget de jetons, une réponse à la fois par administrateur, échéance globale.
- **Rétention** : historique purgé après `AI_ASSISTANT_RETENTION_DAYS` (tâche quotidienne ; `manage.py purge_assistant_history [--apply]`).

## Synthèses de gestion (sans IA)

`GET /handy/backoffice/assistant/insights/?scope=accounts|security|bookings` : alertes **explicables** (règle et seuil indiqués, exemples,
actions **proposées** avec lien — jamais exécutées). Un signal est un indice à vérifier, pas une preuve. Seules les sections autorisées
par les droits sont calculées.

## Messagerie

`/backoffice/messages` : fils « Équipe Tratra » (un par membre, jamais de doublon), non-lus, recherche dans les noms **et** les messages,
pièces jointes (photo, vidéo, PDF) contrôlées comme dans l'application, actualisation automatique.
« Rédiger avec l'IA » (`POST /handy/backoffice/messages/ai-draft/`) : rédiger, reformuler, corriger, ton professionnel, raccourcir.
C'est une **proposition** : rien n'est envoyé tant que l'administrateur n'a pas relu puis confirmé l'envoi. Pour une réponse, les trois derniers
messages du fil sont joints au contexte, coordonnées masquées.
