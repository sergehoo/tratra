# SMS et codes OTP

Le code de vérification du téléphone (`POST /handy/auth/otp/request/`) est envoyé par SMS via un
fournisseur choisi par `SMS_BACKEND` (code : `handy/sms.py`).

| `SMS_BACKEND` | Usage | Variables |
|---|---|---|
| `twilio` | production | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, et `TWILIO_MESSAGING_SERVICE_SID` **ou** `TWILIO_FROM` (alias `TWILIO_PHONE_NUMBER`) |
| `orange` | production | `ORANGE_SMS_CLIENT_ID` + `ORANGE_SMS_CLIENT_SECRET` **ou** `ORANGE_SMS_AUTHORIZATION_HEADER` (portail Orange) ; `ORANGE_SMS_SENDER` (numéro d'expéditeur du pays, défaut `2250000` = Côte d'Ivoire) ; facultatifs : `ORANGE_SMS_SENDER_NAME` (nom validé par Orange, 11 caractères max), `ORANGE_SMS_RESOURCE_TYPE` (`SMS_OCB2` = offre « Orange seulement ») |
| `africastalking` | production | `AT_USERNAME`, `AT_API_KEY`, `AT_SENDER_ID` (facultatif), `AT_SANDBOX=true` pour le bac à sable |
| `twilio,orange` | production, **relève automatique** | les variables de chaque fournisseur listé (voir ci-dessous) |
| `console` | développement uniquement | aucune — le code est journalisé et renvoyé par l'API (`DEBUG` seulement) |
| `locmem` | tests uniquement | aucune — `handy.sms.outbox` |

Autres réglages : `SMS_DEFAULT_COUNTRY_CODE` (défaut `225`, appliqué aux numéros nationaux de 10
chiffres), `SMS_TIMEOUT` (secondes **par fournisseur**, défaut `10`), `SMS_FAILOVER_COOLDOWN` (voir ci-dessous).

## Relève automatique entre fournisseurs

`SMS_BACKEND` accepte une **liste ordonnée** : `SMS_BACKEND=twilio,orange`. Le premier fournisseur est essayé d'abord ;
s'il échoue, le suivant envoie le **même** SMS, sans que l'utilisateur ne voie rien.

| Échec du premier fournisseur | Relève ? | Mis de côté ? |
|---|---|---|
| injoignable, délai dépassé, erreur serveur (5xx), quota (429) | oui | oui |
| identifiants, contrat ou solde refusés (401/403) | oui | oui |
| message ou numéro refusé (400…) | oui | non (le fournisseur n'est pas en panne) |

- **Mise à l'écart** : un fournisseur en panne est essayé **en dernier** pendant `SMS_FAILOVER_COOLDOWN` secondes (60 par défaut,
  `0` = jamais) : les codes suivants partent directement par l'autre fournisseur au lieu d'attendre le délai d'attente du premier.
  Si tous sont écartés, l'ordre configuré est rétabli : jamais d'impasse. La mise à l'écart est propre à chaque processus de
  l'application (cache local) et disparaît au redémarrage.
- **Tous les fournisseurs listés doivent être configurés** : `prod.py` refuse de démarrer sinon (une relève « fantôme » n'existe pas) ;
  `scripts/check_env.py` signale l'écart, et avertit quand un seul fournisseur est configuré.
- **Si tous échouent** : `502` (« Le SMS n'a pas pu être envoyé ») ; `503` si tous ont refusé leur configuration. Le code créé est
  invalidé, comme avec un seul fournisseur.
- **Doublon possible** : si un fournisseur a envoyé le SMS mais n'a pas répondu à temps, le suivant l'envoie aussi — le même code arrive
  deux fois (sans conséquence pour la sécurité : un seul code est valide). Avec 2 fournisseurs, la durée maximale d'une demande
  est ≈ 2 × `SMS_TIMEOUT` ; `SMS_TIMEOUT=6` la ramène à ≈ 12 s.
- **Erreur inattendue d'un fournisseur** (réponse de forme imprévue, caractère non encodable dans un identifiant…) : traitée comme une
  panne de ce fournisseur — la relève continue, et sans relève l'API répond `502` (jamais un `500` qui laisserait le code valide). Seul le
  *type* de l'erreur est journalisé, jamais son texte (il peut contenir une URL ou un identifiant).
- `console` et `locmem` ne se combinent avec aucun autre fournisseur.
- Le Back-Office (Intégrations) affiche la chaîne (`twilio,orange`) et si elle est prête.

### Orange : obtenir les identifiants

Portail developer.orange.com → votre application → API « SMS » du pays → **identifiant client** et **secret** (ou l'en-tête
« Authorization header » fourni tel quel : `ORANGE_SMS_AUTHORIZATION_HEADER`). Il faut un **contrat SMS actif avec un solde
positif** (sinon Orange refuse, ce que l'application traite comme un fournisseur indisponible et relève). Débit limité à 5 SMS/s
par Orange. `ORANGE_SMS_SENDER` accepte `2250000`, `+225 0000`, `tel:+2250000` ou la forme encodée de la documentation Orange ; vide = `2250000` ; un numéro
illisible est refusé au démarrage (il rendrait toute la chaîne inutilisable, Twilio compris). Un nom d'expéditeur personnalisé (`ORANGE_SMS_SENDER_NAME`) ne doit être renseigné qu'**après** validation par Orange
(délai jusqu'à 5 jours ouvrés), sinon chaque envoi est refusé (400). Le jeton d'accès (valable 1 h) est mis en cache et renouvelé
automatiquement.

## Garanties

- **Production** : `tratra/settings/prod.py` refuse de démarrer sans `SMS_BACKEND` réel et sans ses
  identifiants. `console` et `locmem` sont de plus refusés à l'exécution hors `DEBUG`/tests.
- **Aucun faux succès** : sans numéro (`400`), sans fournisseur (`503`)
  ou si le fournisseur refuse (`502`), l'API renvoie une erreur et le code créé est invalidé.
- **Aucun code fictif** : il n'existe aucun code de secours ; un seul code est valide à la fois ; le
  code n'est jamais renvoyé par l'API (sauf `console` en `DEBUG`) ni écrit dans les journaux de production.
- **Limites** : 60 s entre deux codes, 5 codes par heure et par compte (comptés en base) ;
  5 essais invalides invalident le code (`429`).
- Les journaux ne contiennent ni le texte du SMS ni le numéro complet.

## Activer Twilio en local

Les identifiants Twilio du `.env` ne sont utilisés que si `SMS_BACKEND=twilio` y est aussi défini (par défaut en développement : `console`, aucun SMS réel). Un compte Twilio d'essai n'envoie qu'aux numéros vérifiés.

## Dépannage

- **Vérifier la relève sans attendre une panne** : `SMS_BACKEND=twilio,orange`, puis couper volontairement Twilio (mauvais
  `TWILIO_AUTH_TOKEN`) : le code arrive par Orange et le journal serveur indique « SMS : twilio a échoué … relève par le
  fournisseur suivant » puis « SMS livré via orange après l'échec de : twilio ».

- **`503` « L'envoi de SMS n'est pas disponible »** : fournisseur absent ou identifiants refusés par le
  fournisseur (Twilio : HTTP 401, code 20003 = jeton d'authentification invalide ou révoqué). Corriger
  `TWILIO_AUTH_TOKEN` / `TWILIO_ACCOUNT_SID` dans `.env` ; le journal serveur indique la cause exacte, sans
  jamais afficher le jeton, le texte du SMS ni le numéro complet.
- **`502` « Le SMS n'a pas pu être envoyé »** : le fournisseur a refusé ce message (numéro invalide ou non
  autorisé — avec un compte Twilio d'essai, seuls les numéros vérifiés reçoivent des SMS) ou est injoignable.
