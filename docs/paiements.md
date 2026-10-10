# Paiements — Orange Money, MTN MoMo, carte, espèces

> Rien n'est branché « en vrai » tant que les identifiants d'un prestataire autorisé ne sont pas renseignés. **Aucun identifiant n'est versionné.**
> Sans eux, la méthode répond `503 payment_provider_unavailable` : l'application ne simule jamais un paiement.

## Principe : déclaré, confirmé, vérifié

| Niveau | Qui l'établit | Où |
|---|---|---|
| **Déclaré** | une partie affirme avoir payé / reçu | engagements (`InstallmentPayment.status = declared`) |
| **Confirmé** | l'**autre** partie confirme (jamais l'auteur) | engagements (`confirmed`) — affiché « Tratra ne vérifie pas ce paiement » |
| **Vérifié** | **le prestataire de paiement**, interrogé par le serveur Tratra | réservations (`Payment.provider_verified_at`) |

* « Vérifié » n'existe que pour un encaissement passé par un prestataire configuré. Les paiements entre les parties d'un engagement
  (virement, espèces, Mobile Money direct) ne transitent pas par Tratra : ils restent **déclarés puis confirmés**, jamais « vérifiés ».
* **Espèces** : mode manuel conservé tel quel — le paiement reste `pending` tant qu'une confirmation humaine réelle n'existe pas.

## Règles de sécurité (testées : `handy/test_payments_providers.py`)

1. Un webhook ou le retour du client ne sont que des **déclencheurs**. La décision vient de `Provider.verify` (appel serveur-à-serveur) :
   statut, **montant**, **devise** et **référence** doivent concorder avec le paiement Tratra, sinon `provider_status = "mismatch"`
   et rien n'est reconnu (journalisé dans `PaymentLog`).
2. `Payment.mark_held` refuse un paiement par prestataire sans `provider_verified_at` — aucun chemin (vue, tâche, admin, script) ne peut
   donc placer des fonds sous séquestre sans vérification. Un test balaie le code pour s'en assurer.
3. Prestataire non configuré ou injoignable → **aucun changement d'état** (webhook : 503, il sera rejoué ; réconciliation : repasse).
4. Webhooks : HMAC-SHA256 du corps brut (`X-Webhook-Signature`, secret **par prestataire** : `PAYMENT_<OM|MTN|CARD>_WEBHOOK_SECRET`)
   ou `Stripe-Signature` (secret `STRIPE_WEBHOOK_SECRET`, tolérance 5 min). Sans secret : tout est refusé.
5. Les données de session (`pay_token`, `notif_token`, secrets, jetons OAuth) ne sont jamais renvoyées par l'API ni journalisées.
6. Filet : la tâche Celery `handy.tasks.reconcile_provider_payments` (toutes les 2 min) interroge le prestataire pour les paiements
   en attente de 1 min à 72 h — indispensable pour Orange et MTN, dont les rappels ne portent pas notre HMAC.
7. Une tentative **échouée** (refus, expiration, annulation) peut être relancée : la même ligne de paiement repart avec une nouvelle transaction.

## Variables (voir `.env.staging.example`)

| Prestataire | Variables | Disponible quand |
|---|---|---|
| Orange Money (Web Payment) | `OM_CLIENT_ID`, `OM_CLIENT_SECRET`, `OM_MERCHANT_KEY`, `PAYMENT_RETURN_URL`, `PAYMENT_CANCEL_URL`, `PAYMENT_NOTIFY_BASE_URL` (+ `OM_API_BASE`, `OM_COUNTRY`, `OM_CURRENCY`) | toutes les six sont renseignées |
| MTN MoMo (Collection) | `MTN_MOMO_SUBSCRIPTION_KEY`, `MTN_MOMO_API_USER`, `MTN_MOMO_API_KEY` (+ `MTN_MOMO_BASE_URL`, `MTN_MOMO_TARGET_ENV`, `MTN_MOMO_CURRENCY`) | les trois sont renseignées |
| Carte (Stripe) | `STRIPE_SECRET_KEY` (+ `STRIPE_WEBHOOK_SECRET`, `STRIPE_CURRENCY`) | la clé est renseignée |

Contrôle sans rien afficher de secret : `python manage.py payments_check [--ping]` (`--ping` obtient un jeton / interroge l'API du prestataire).
`manage.py check --deploy` avertit (`tratra.W003`) si un prestataire de production est réglé sur une devise de bac à sable.

## Procédure de qualification (bac à sable, puis production) — **à faire avec les comptes du prestataire**

Ce qui ne peut pas être prouvé hors ligne : les formats exacts de réponse de chaque prestataire. Les adaptateurs suivent les
documentations publiques ; les tests simulent le réseau. Avant d'activer en production :

1. Ouvrir le compte marchand (Orange Money Côte d'Ivoire, MTN MoMo Developer, Stripe), obtenir les identifiants **de bac à sable**.
2. Staging : renseigner les variables (devise de bac à sable : `OM_CURRENCY=OUV`, `MTN_MOMO_CURRENCY=EUR`, clé `sk_test_…`).
   Déclarer l'URL de notification `…/handy/payments/webhook/<om|mtn|card>/` chez le prestataire (Stripe : événements
   `payment_intent.succeeded`, `payment_intent.payment_failed`, `payment_intent.canceled`, `charge.refunded`).
3. `payments_check --ping` → « jeton obtenu » / « clé acceptée ».
4. Pour **chaque** prestataire, rejouer :
   - paiement réussi → `held`, `provider_verified_at` renseigné, `provider_status` = statut du prestataire ;
   - refus / expiration → `failed`, puis nouvelle tentative possible ;
   - **montant erroné** (Orange : appeler le statut avec un autre montant ne doit pas rendre `SUCCESS` ; MTN/Stripe : montant renvoyé ≠ montant Tratra
     → `mismatch`) ;
   - webhook perdu → la réconciliation règle le paiement en ≤ 2 min ;
   - webhook forgé (mauvaise signature) → 401 sans appel au prestataire ; rejeu → sans effet double.
5. Production : identifiants de production, devise XOF, secrets de webhook distincts de ceux du staging ; `check --deploy` sans `tratra.W003`.
6. Côté clients (web/Flutter), n'exposer la méthode qu'une fois qualifiée : `NEXT_PUBLIC_PAYMENT_METHODS` (web) ; l'API refuse de toute façon une méthode non configurée.

## Limites connues

* Aucun appel réel n'a été exécuté (pas d'identifiants) : formats à confirmer à l'étape 4.
* Remboursement initié côté Tratra auprès du prestataire : non implémenté (`Provider.refund` « non supporté ») — un remboursement n'est
  reconnu que si le prestataire l'indique (Stripe) ou par l'action du Back-Office sur le séquestre.
* Reversement aux artisans (Payout) : inchangé (hors périmètre).
* Les écrans de paiement par prestataire ne sont pas exposés tant que la méthode n'est pas qualifiée.
