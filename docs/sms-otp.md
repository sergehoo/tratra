# SMS et codes OTP

Le code de vérification du téléphone (`POST /handy/auth/otp/request/`) est envoyé par SMS via un
fournisseur choisi par `SMS_BACKEND` (code : `handy/sms.py`).

| `SMS_BACKEND` | Usage | Variables |
|---|---|---|
| `twilio` | production | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, et `TWILIO_MESSAGING_SERVICE_SID` **ou** `TWILIO_FROM` (alias `TWILIO_PHONE_NUMBER`) |
| `africastalking` | production | `AT_USERNAME`, `AT_API_KEY`, `AT_SENDER_ID` (facultatif), `AT_SANDBOX=true` pour le bac à sable |
| `console` | développement uniquement | aucune — le code est journalisé et renvoyé par l'API (`DEBUG` seulement) |
| `locmem` | tests uniquement | aucune — `handy.sms.outbox` |

Autres réglages : `SMS_DEFAULT_COUNTRY_CODE` (défaut `225`, appliqué aux numéros nationaux de 10
chiffres), `SMS_TIMEOUT` (secondes, défaut `10`).

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

- **`503` « L'envoi de SMS n'est pas disponible »** : fournisseur absent ou identifiants refusés par le
  fournisseur (Twilio : HTTP 401, code 20003 = jeton d'authentification invalide ou révoqué). Corriger
  `TWILIO_AUTH_TOKEN` / `TWILIO_ACCOUNT_SID` dans `.env` ; le journal serveur indique la cause exacte, sans
  jamais afficher le jeton, le texte du SMS ni le numéro complet.
- **`502` « Le SMS n'a pas pu être envoyé »** : le fournisseur a refusé ce message (numéro invalide ou non
  autorisé — avec un compte Twilio d'essai, seuls les numéros vérifiés reçoivent des SMS) ou est injoignable.
