# agent4

## FINDINGS
# Recherche externe : KYC + OTP SMS pour Tratra (CI + international)

Note : la plupart des faits viennent de la doc officielle consultée le 2026-10-08. La couverture CNI CI de Smile ID a été **vérifiée en direct** sur l'endpoint public `GET /v3/services/supported_documents?country_code=CI` (sandbox et prod).

---
## 1. Comparatif des prestataires KYC (CNI ivoirienne recto/verso, selfie liveness, face match)

| Prestataire | CNI CI | Doc + liveness + face match | Intégration | Signature webhook (algorithme exact) | Sandbox | Statuts |
|---|---|---|---|---|---|---|
| **Smile ID** | **OUI, vérifié en direct** : `IDENTITY_CARD` « Cartes d'identité nationales », `has_back: true`. Aussi `PASSPORT` (pas de verso), `RESIDENT_ID`, `DRIVERS_LICENSE`, etc. Recherche par numéro : `NATIONAL_ID_NO_PHOTO` (11 chiffres, Basic/Enhanced KYC uniquement, **pas de Biometric KYC en CI**). Enhanced Document Verification : **CI non supportée** (uniquement KE/NG/ZA) | Authenticité du document (éléments de sécurité, MRZ, codes-barres), liveness **passive** par défaut, liveness **active** en option (`enableEnhancedLiveness` sur mobile, `use_strict_mode: true` sur le web), comparaison selfie ↔ photo du document | API REST v3 multipart, SDK Flutter `usesmileid`, SDK web hébergé v12 (CDN) | En-tête `Response-Signature` = base64(HMAC-SHA256(**api_key**, `Response-Timestamp` + `partner_id` + `"sid_request"`)). **Le corps n'est PAS signé** | Résultats simulés et déterministes selon des identités de test (nom + prénom + email) | `clear` / `attention` / `block` / `error`, plus `reason` |
| Sumsub | 14 000+ types de pièces annoncés. CNI CI non confirmée explicitement dans les sources | Oui (liveness + face match) | WebSDK, MobileSDK Flutter `flutter_idensic_mobile_sdk_plugin` 1.40.2. API : `X-App-Token`, `X-App-Access-Ts` (secondes epoch, tolérance ±1 min), `X-App-Access-Sig` = hex(HMAC-SHA256(secret, ts+METHOD+path?query+body)) | `X-Payload-Digest` = hex HMAC du **corps brut** ; algorithme indiqué par `X-Payload-Digest-Alg` (`HMAC_SHA256_HEX` par défaut, `HMAC_SHA1_HEX` obsolète) ; secret défini à la création du webhook | Même hôte `api.sumsub.com` (c'est le token qui détermine le mode), aucun algorithme d'approbation en sandbox, 500 candidats / 24 h | `applicantReviewed` → `reviewResult.reviewAnswer` GREEN/RED, `reviewRejectType` RETRY/FINAL, `rejectLabels`, `moderationComment` |
| Onfido (désormais Entrust) | **Non** pour la CNI : Document Report Instant ne liste que le **passeport** pour la CI | Oui | SDK + API | `X-SHA2-Signature` = hex HMAC-SHA256(token du webhook, corps brut), comparaison en temps constant | Oui | — |
| Veriff | CNI CI non confirmée (renvoi au support) | Oui | `veriff_flutter` 5.x, API `X-AUTH-CLIENT` + `X-HMAC-SIGNATURE` | `x-hmac-signature` = hex HMAC-SHA256(secret partagé, corps brut) | Oui | `approved`, `declined`, `resubmission_requested`, `review`, `expired`, `abandoned` ; codes 9001/9102/9103/9104/9121 ; webhook `resubmission_requested` retardé de 5 min |
| Regula | Couverture CI non confirmée | SDK Document Reader + Face SDK **sur l'appareil, hors ligne** | `flutter_document_reader_api` 7.x | Pas de décision hébergée ni de webhook : le moteur de décision serait à construire | Licence | — |
| Youverify | Doc « document capture supported countries » : carte d'identité et permis de conduire ivoiriens (extrait de recherche) | Oui | Centré sur le Nigeria | Non obtenue | — | — |
| Dojah | Couverture CI non documentée publiquement | Oui (EasyOnboard) | Widget + API | Non obtenue | — | — |

### RECOMMANDATION : Smile ID
Raisons :
- Seul prestataire dont la CNI CI recto/verso est **prouvée** (`IDENTITY_CARD has_back=true`).
- Spécialisé Afrique : il annonce 99,8 % de précision sur les visages africains, plus 8 types de pièces ivoiriennes.
- Liveness passive et active, comparaison faciale avec la photo de la CNI.
- Objet de **consentement natif** (obligatoire dans la v3, renvoyé au format ISO 27560 → audit).
- REST v3 simple à appeler depuis Django avec `requests` (déjà présent), sans SDK serveur.
- Sandbox déterministe pour les tests.
- Webhook + polling disponibles.
- Paiement à l'usage par portefeuille prépayé, avec un programme startup « Smile for Success » (jusqu'à 6 000 $ de crédits). Les prix unitaires ne sont pas publiés.

Second choix : Sumsub. Il apporte une couverture mondiale et une sémantique RETRY/FINAL mature, mais la CNI CI n'est pas confirmée.

Sources :
- https://docs.usesmileid.com/id-coverage/verify-with-document.md
- https://docs.usesmileid.com/id-coverage/verify-with-id-number/cote-divoire.md
- https://smile.id/countries/cote-divoire
- https://docs.sumsub.com/reference/authentication
- https://docs.sumsub.com/docs/webhook-manager
- https://docs.sumsub.com/docs/user-verification-webhooks
- https://docs.sumsub.com/docs/flutter-plugin
- https://documentation.identity.entrust.com/api/manual-webhook-signature-verification/
- https://documentation.identity.entrust.com/guide/supported-documents-instant/
- https://devdocs.veriff.com/docs/decision-webhook.md
- https://devdocs.veriff.com/docs/hmac-authentication-and-endpoint-security
- https://pub.dev/documentation/flutter_document_reader_api/5.8.0/index.html

---
## 2. Smile ID : spécification du flux serveur (API v3, actuelle)

**URLs de base** : sandbox `https://testapi.smileidentity.com`, production `https://api.smileidentity.com`. Les identifiants sont distincts par environnement et les tokens ne passent pas d'un environnement à l'autre.

### 2.1 Authentification
Appel : `POST {base}/v3/token`
- En-têtes : `SmileID-Partner-ID: <partner_id>`, `SmileID-API-Key: <api_key>`, `Accept: application/json`
- Corps en multipart : `partner_id=<partner_id>`
- Réponse : `200 {"token":"<jwt>"}`. Le JWT **expire au bout de 15 min**.
- Il se passe ensuite dans l'en-tête `SmileID-Token` à chaque appel.
- La doc impose de garder la clé API côté serveur et de ne jamais générer de token depuis le navigateur.

Sources : https://docs.usesmileid.com/api-reference/authentication.md et https://docs.usesmileid.com/api-reference/api-keys.md

### 2.2 Soumission « vérification de document + selfie/liveness »
Appel : `POST {base}/v3/document_verification` (multipart/form-data, en-tête `SmileID-Token`)

| Champ | Obligatoire | Contenu |
|---|---|---|
| `selfie_image` | oui | JPEG |
| `liveness_images` | oui | **6 à 8 JPEG** (images de la séquence de liveness) |
| `document` | oui | Recto de la CNI, JPEG/PNG |
| `document_back` | optionnel dans l'API, mais `has_back=true` pour la CNI CI → **à envoyer** | Verso, JPEG/PNG |
| `consent` | oui | JSON `{"granted":true,"granted_at":"ISO8601","notice_language":"FR","notice_privacy_policy_url":"https://..."}` |
| `country` | oui | `CI` (ISO alpha-2, majuscules) |
| `id_type` | non | `IDENTITY_CARD` ; auto-classifié si omis |
| `user_details` | oui | JSON `{"given_names":..,"last_name":..,"phone_number":"+225..."}` (email OU téléphone E.164) |
| `user_id` | non | Identifiant opaque côté Tratra, pas de donnée personnelle |
| `callback_url` | non | HTTPS |
| `partner_params` | non | Paires clé/valeur, par ex. `{"kyc_submission_id":"..."}` |
| `metadata` | non | Liste de `{name,value}` |

- Réponse **202** : `{"status":"accepted","message":"Verification submitted for processing","job_id":"job_...","user_id":"...","created_at":"..."}`. Le `job_id` est généré par le serveur Smile, au format TypeID `^job_[0-9a-hjkmnp-tv-z]{26}$`.
- Catalogue des pièces (sans authentification) : `GET /v3/services/supported_documents?country_code=CI&locale=fr-FR` → `valid_documents[].id_types[]{code,name,has_back}`.
- Les champs « job_type 6 / image_type_id / info.json zip / prep_upload » appartiennent à l'**API historique v1**. Elle utilise le même HMAC (`timestamp+partner_id+"sid_request"`) dans les champs `signature`/`timestamp` du corps, ainsi que le SDK Python `smile-id-core` 2.1.x. Correspondance `image_type_id` : 0 = selfie, 1 = recto, 5 = verso, 4/6 = liveness. **À ne pas utiliser pour une nouvelle intégration.**

Sources : https://docs.usesmileid.com/api-reference/products/document-verification/perform-a-document-verification.md et https://docs.usesmileid.com/api-reference/core-resources/services/supported-documents.md

Docs historiques : https://legacy-docs.usesmileid.com/integration-options/server-to-server/python/generate-signature et https://docs.usesmileid.com/further-reading/faqs/what-are-the-image-types-i-can-upload-to-smile-id

### 2.3 Réception du résultat
**Webhook** `POST callback_url` :
- En-têtes : `Response-Signature`, `Response-Timestamp` (ISO 8601), `Job-ID`, `User-ID`, `Api-Version`, `Content-Type: application/json`.
- 2xx attendu sous **35 s**. Jusqu'à 3 nouvelles tentatives (4 au total).
- Vérification de la signature (exemple Django officiel) :
```python
message = f"{timestamp}{settings.SMILE_ID_PARTNER_ID}sid_request".encode()
expected = base64.b64encode(hmac.new(settings.SMILE_ID_API_KEY.encode(), message, hashlib.sha256).digest()).decode()
if not hmac.compare_digest(expected, signature): return HttpResponse(status=401)
```
- La signature ne couvre que l'horodatage et le partner_id, **pas le corps**. Durcissement indispensable :
  - fenêtre de fraîcheur maison sur `Response-Timestamp` (±5 min ; la doc n'impose aucune tolérance) ;
  - idempotence par `job_id` ;
  - concordance `Job-ID` ↔ `partner_params.job_id` ↔ `job_id` stocké à la soumission ;
  - relecture faisant foi via `GET /v3/status/{job_id}` avant toute transition terminale.

**Contenu du webhook** (Document Verification) : `status`, `message`, `reason`, `product`="document_verification", `created_at`, `completed_at`, `partner_params{job_id,user_id,...}`, `kyc_receipt`, **`image_links`** (sensible), `id_fields{country,id_type,first_name,last_name,full_name,id_number,date_of_birth,gender,issuance_date,expiration_date,address...}`, `user_provided_info`, `antifraud{fraud_risk{risk_level low|medium|high,risk_score 0-100},smile_secure,summary{fraud_detected}}`, `device_signals`, `consent{schema_version:"ISO27560-v1",...}`.

**Codes `reason` par statut** :
- `clear` : `reason` vaut null.
- `attention` : `document_expired`, `age_requirement_not_met`, `document_copy_detected`, `medium_risk`.
- `block` : `high_risk`, `account_locked_fraud`, `face_verification_failed`, `spoof_detected`, `document_check_failed`, `unsupported_document`, `age_requirement_not_met`.
- `error` : `image_unavailable_or_invalid`, `internal_error`, `document_unclassifiable`, `content_policy_violated`.

**Correspondance proposée avec les états Tratra** :
- `clear` → APPROVED automatique, **seulement si** le profil est complet et le compte actif ; sinon REVIEW.
- `attention` → REVIEW (validation humaine).
- `block` → REJECTED avec motif et resoumission possible. Pour `account_locked_fraud`/`high_risk` : REVIEW, ou rejet sans resoumission automatique.
- `error` → reste PENDING. Resoumission demandée pour `image_unavailable_or_invalid`/`document_unclassifiable`, nouvelle tentative pour `internal_error`.

**Polling de secours** : `GET /v3/status/{jobId}` (en-tête `SmileID-Token`). Réponse 200 si terminal (`clear|block|attention|error`), 202 si `processing`, 404 si inconnu. Champs : `status`, `job_id`, `user_id`, `message`, `created_at`.

**Sandbox** : identités de test, par ex. `Clearwater`/`Amina Fatou` → clear, `Dangerfield`/`Rashid Omar` → block, `Glitchford`/`Chidinma Obi` → error. Correspondance sur `last_name` + `given_names` + `email`. La validation des champs est identique à la prod.

Sources :
- https://docs.usesmileid.com/developer-resources/essentials/verification-webhooks/receive-webhooks.md
- https://docs.usesmileid.com/developer-resources/essentials/verification-webhooks/webhook-types/document-verification.md
- https://docs.usesmileid.com/products/onboarding-with-biometrics/document-verification.md
- https://docs.usesmileid.com/api-reference/core-resources/verification-status/retrieve-a-verification-result.md
- https://docs.usesmileid.com/developer-resources/essentials/testing-in-sandbox.md
- https://docs.usesmileid.com/products/biometric-authentication/smartselfie-tm-registration.md

### 2.4 SDK officiels
**Flutter** :
- `usesmileid` **12.2.0** (2026-09-30, MIT, éditeur vérifié smileidentity.com). Requiert **Flutter 3.44+ / Dart 3.12+**, AGP 9.1, Gradle 9, Android API 24+, iOS 15+. Point d'entrée `UseSmileIDBuilder` (configuration `network()/config()/ml()/screens()/theme()`), auth par **token v3** généré par le backend, qui peut porter les données utilisateur et le consentement.
- L'ancien `smile_id` **11.2.14** (Flutter 3.0+, Dart 3.0.5, iOS 13, `smile_config.json`) s'appuie sur une clé API ou un token **longue durée embarqué dans l'app** : à proscrire.
- Environnement local : **Flutter 3.38.5**, `pubspec.yaml` avec `sdk: ^3.6.1`, `image_picker ^1.1.2`, `http ^1.5.0`. Seule la 11.x est compatible sans montée de version. Il faut donc soit monter Flutter en 3.44, soit capturer les images dans l'app et faire soumettre le multipart v3 par le backend.

**Web** :
- SDK hébergé v12 **non publié sur npm** : `<script src="https://cdn.usesmileid.com/inline/v12/js/script.min.js">` puis `window.SmileIdentity({token, product:'document_verification', callback_url, environment:'sandbox'|'production', partner_details{partner_id,name,logo_url,policy_url,theme_color}, onResult, onSuccess, onClose, onError})`.
- Prérequis : HTTPS, `cdn.usesmileid.com` à ajouter à la CSP, `allow="camera"` si le flux est dans une iframe.
- Le résultat fait foi **uniquement via le webhook**.
- Package npm historique de capture seule : `@smileid/web-components` (`<smart-camera-web capture-id="back">`, événement `imagesComputed`). Le v11 n'est pas compatible avec le v12.

Sources :
- https://pub.dev/packages/usesmileid
- https://docs.usesmileid.com/developer-resources/sdks/mobile/release-notes/flutter.md
- https://pub.dev/packages/smile_id
- https://docs.usesmileid.com/developer-resources/sdks/web/web-sdk/setup.md
- https://docs.usesmileid.com/developer-resources/sdks/web/web-sdk.md
- https://www.npmjs.org/package/@smile_identity/smart-camera-web

### 2.5 Cadre légal CI (à valider par un juriste)
Loi n°2013-450 du 19/06/2013 : le traitement de **données biométriques est soumis à autorisation préalable de l'ARTCI**. Le transfert vers un sous-traitant hors CEDEAO est à vérifier. Source : https://www.digitalbusiness.africa/ce-quil-faut-savoir-du-cadre-reglementaire-de-la-biometrie-en-cote-divoire/

---
## 3. OTP SMS

### Fournisseurs
| Fournisseur | API | Coût indicatif vers la CI | Remarques |
|---|---|---|---|
| **Orange SMS API Côte d'Ivoire** | OAuth `POST https://api.orange.com/oauth/v3/token` (`Authorization: Basic`, `grant_type=client_credentials`, token d'1 h), puis `POST https://api.orange.com/smsmessaging/v1/outbound/tel%3A%2B{sender}/requests` avec `{"outboundSMSMessageRequest":{"address":"tel:+225...","senderAddress":"tel:+{sender}","senderName":"Tratra","outboundSMSTextMessage":{"message":"..."}}}` | Forfaits 20 SMS/145 XOF, 100/725, 1 000/7 260, **10 000/72 600 XOF (≈7,26 XOF par SMS)**, payables en crédit ou Orange Money | Envoi vers **tous les opérateurs CI**, mais uniquement à l'intérieur du pays. **5 SMS/s**. `senderName` de 11 caractères maximum, soumis à approbation. Accusés de réception sur HTTPS:443 avec IP en liste blanche |
| MTN SMS v3 | `https://api.mtn.com/v3/sms/`, OAuth2 client credentials | Tarifs locaux de 10 à 50 XOF | CI listée parmi les pays migrés en v3 |
| **Twilio Verify** | `POST https://verify.twilio.com/v2/Services/{sid}/Verifications` (To, Channel=sms), puis `.../VerificationCheck` (To, Code) | **0,05 $ par vérification réussie** + SMS ≈ **0,44 à 0,49 $** vers la CI | OTP généré, stocké et vérifié par Twilio. Expiration 10 min, 5 vérifications (erreur 60202), 5 envois par cycle (60203). **Fraud Guard actif par défaut** (niveaux Basic/Standard/Max ; 60410 = préfixe bloqué 12 h) |
| Infobip | API 2FA avec PIN géré (`pinAttempts`, `pinTimeToLive`, `verifyPinLimit`, `sendPinPerPhoneNumberLimit` ex. "5/1d", gabarit `{{pin}}`) | ≈ 0,24 $ par SMS | Bon compromis pour l'international |
| Africa's Talking | — | Couverture et prix CI non confirmés | Déconseillé faute de preuve |

**Spécificités CI** :
- Sender ID alphanumérique : **pré-enregistrement obligatoire, environ 3 semaines**, pas d'expéditeur dynamique, pas de SMS bidirectionnel.
- Éviter les expéditeurs génériques (« INFO », « Verify »…).
- Numérotation à **10 chiffres depuis le 31/01/2021** : préfixes mobiles 07 Orange, 05 MTN, 01 Moov ; fixes 27/25/21.

**Twilio Verify ou SMS brut** :
- Verify : rien à stocker et anti-pumping intégré, mais ≈ 0,5 $ par OTP en CI, dépendance au fournisseur, audit moins fin.
- SMS brut + OTP local : environ 40 fois moins cher via Orange CI, mais toute la logique OTP est à maîtriser.

**Recommandation** :
- OTP **généré localement** (réutiliser `OTPCode`).
- Abstraction `SmsBackend` avec un routage par indicatif : `console` (dev), `orange_ci` (+225), `twilio`/`infobip` (international).

**Anti SMS pumping** (Twilio) :
- Liste blanche de pays.
- Limites par numéro, IP, appareil et préfixe.
- Délai exponentiel entre deux renvois.
- CAPTCHA ou détection de bots.
- Envoi uniquement vers des numéros mobiles (Lookup ou `phonenumbers.number_type`).
- Suivi du taux de conversion envoyés/vérifiés par pays, avec alertes.
- Blocage IP VPN/TOR/cloud.
- Plafond de dépense et alertes d'usage.

Sources :
- https://developer.orange.com/apis/sms/getting-started
- https://developer.orange.com/apis/sms-ci/pricing
- https://developers.mtn.com/categories/messaging
- https://www.twilio.com/docs/verify/api/verification
- https://www.twilio.com/docs/api/errors/60410
- https://www.twilio.com/docs/api/errors/60203
- https://www.twilio.com/docs/api/errors/60202
- https://www.twilio.com/docs/verify/preventing-toll-fraud
- https://www.twilio.com/en-us/sms/pricing/ci
- https://www.twilio.com/en-us/guidelines/ci/sms
- https://infobip.com/docs/2fa-service/using-2fa-api
- https://sent.dm/en/resources/sms-pricing/ivory-coast-sms-pricing
- https://cio-mag.com/cote-divoire-telephonie-face-a-lexplosion-de-la-demande-lartci-passe-dune-numerotation-de-8-a-10-chiffres/

---
## 4. Bonnes pratiques OWASP / NIST pour l'OTP et la récupération → paramètres proposés

**Référentiel** :
- NIST SP 800-63B-4 : secret d'au moins 6 chiffres issu d'un générateur aléatoire approuvé, validité de **10 min maximum**, usage unique, limitation des essais obligatoire (au plus 100 échecs consécutifs avant désactivation). Le SMS est un authentificateur « restreint ».
- Le changement de téléphone équivaut à lier un nouvel authentificateur : il exige une authentification préalable.

**Paramètres proposés** :
- **6 chiffres** (OWASP MFA suggère 8 si l'ergonomie le permet), via `secrets` (comme le fait déjà `OTPCode.issue`).
- **TTL 5 min**.
- **5 essais maximum par code**, puis invalidation.
- Usage unique, consommation **atomique** (UPDATE conditionnel ou `select_for_update`).
- Renvoi : **cooldown de 60 s** puis exponentiel. Maximum 5 envois par numéro et par heure, 10 par jour, 10 par IP et par heure, plus un budget global par pays.
- Tout renvoi **invalide les codes précédents**.
- Stockage **haché** : `HMAC-SHA256(OTP_PEPPER, f"{purpose}:{phone_e164}:{code}")` + `hmac.compare_digest`. Un simple SHA-256 de 10^6 valeurs se casse hors ligne.
- Code lié à un `purpose` (signup/login/reset/phone_change) et à un `challenge_id` opaque renvoyé au client.

**Anti-énumération** :
- Mêmes statut HTTP, message et délai pour un numéro connu ou inconnu, par ex. « Si ce numéro est éligible, un code vous a été envoyé ».
- Envoi asynchrone via Celery pour lisser les temps de réponse.
- À l'inscription sur un numéro déjà existant : envoyer un SMS d'information (« utilisez Mot de passe oublié ») plutôt qu'une erreur.
- Login : message générique « Identifiants invalides ». Django `ModelBackend` hache déjà un mot de passe factice pour un utilisateur inexistant ; à reproduire dans un backend téléphone personnalisé.

**Verrouillage** :
- Compteur par compte (pas seulement par IP), backoff exponentiel.
- Aucun changement d'état du compte tant qu'aucun token valide n'est présenté.

**Après une réinitialisation** :
- Invalider toutes les sessions et refresh tokens (blacklist simplejwt).
- Notifier l'utilisateur par SMS.
- Pas de connexion automatique.

**Mots de passe** : 8 caractères minimum si MFA, 15 sinon ; accepter au moins 64 caractères.

Sources :
- https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html
- https://pages.nist.gov/800-63-4/sp800-63b.html

---
## 5. Normalisation des numéros de téléphone (E.164)
- **Python** : `phonenumbers` **9.0.41** (2026-10-08, Apache-2.0). Usage : `parse(raw, "CI")`, `is_valid_number`, `number_type` (MOBILE), `format_number(x, PhoneNumberFormat.E164)`. Variante allégée `phonenumberslite`.
  - Point projet : `django-phonenumber-field 8.1.0` est installé mais **`phonenumbers` est absent du venv** (`ModuleNotFoundError`). Il faut ajouter `django-phonenumber-field[phonenumbers]` et définir `PHONENUMBER_DEFAULT_REGION="CI"` et `PHONENUMBER_DB_FORMAT="E164"`.
  - Source : https://pypi.org/project/phonenumbers/
- **JS** : `libphonenumber-js` **1.13.15** (MIT). Utiliser `parsePhoneNumberWithError(raw,'CI')`, `.isValid()`, `.number` (E.164), et les métadonnées `libphonenumber-js/max` pour `getType()` et une validation stricte (`min` ne contrôle que la longueur). Composant UI : `react-phone-number-input` **3.4.18** (MIT, dépend de libphonenumber-js ^1.13.11). Aucun des deux n'est présent dans `frontend/package.json`.
  - Sources : https://registry.npmjs.org/libphonenumber-js/latest et https://registry.npmjs.org/react-phone-number-input/latest
- **Flutter** :
  - `phone_numbers_parser` **9.0.28** (MIT) : `PhoneNumber.parse(raw, callerCountry: IsoCode.CI)`, `.isValid(type: PhoneNumberType.mobile)`, `.international` (E.164).
  - Widget recommandé : `phone_form_field` **12.0.1** (MIT, construit sur phone_numbers_parser ^9.0.28).
  - `intl_phone_field` **3.2.0** : dernière publication il y a environ 3 ans, validation essentiellement par longueur min/max par pays (d'après ma connaissance du package) → déconseillé.
  - Sources : https://pub.dev/packages/phone_numbers_parser, https://pub.dev/packages/phone_form_field, https://pub.dev/packages/intl_phone_field

---
## 6. Rapprochement avec l'existant (lecture seule)
- `handy/models.py:37` : `phone = models.CharField(max_length=20, blank=True, null=True, unique=True, db_index=True)`. Un E.164 CI tient en 14 caractères.
- `handy/models.py:995-1017` `OTPCode` :
  - le code est stocké **en clair** : `code = models.CharField(max_length=6, db_index=True)` ;
  - aucun compteur d'essais, rattaché à `user` (pas au téléphone) ;
  - `issue()` utilise `secrets.randbelow(1000000)` avec un TTL de 10 min.
- `handy/api/views.py:1085-1110` (fichier **en cours de modification** par d'autres agents) :
  - `otp_request` réservé aux utilisateurs authentifiés, renvoie `payload["code"]` si `settings.DEBUG` ;
  - `otp_verify` cherche par `filter(user=request.user, code=code, used=False)` : aucune limite d'essais hormis le throttle utilisateur à 1000/h.
- `handy/tasks.py:32-36` : `_send_sms` est un **stub** qui se contente de journaliser (« TODO(prod): brancher un provider (Orange/Twilio) »).
- `tratra/settings/base.py` :
  - 205-215 : throttles DRF `anon` 60/min, `user` 1000/h, `login` 10/min, `webhook` 120/min ;
  - 230-236 : `SIMPLE_JWT` avec access 30 min, refresh 7 j, `ROTATE_REFRESH_TOKENS` et `BLACKLIST_AFTER_ROTATION` à True ;
  - 440-446 : axes avec `AXES_FAILURE_LIMIT=5`, cooloff 1 h ;
  - 293-315 : stockage `private_kyc` avec `KYC_MAX_UPLOAD_BYTES`, `KYC_ALLOWED_CONTENT_TYPES` et `KYC_SIGNED_URL_TTL_SECONDS=300` ;
  - **aucun `CACHES`** défini, donc LocMemCache propre à chaque processus.
- `handy/storage.py:40` `KycPrivateStorage` (alias `private_kyc`).
- `handy/api/views.py:976` : endpoint de revue KYC `{action: approve|reject, reason}`.
- `handy/api/views.py:1266` : `throttle_scope = "webhook"`.

## DATA
n/a

## RISKS
- Webhook Smile ID : la signature (base64 HMAC-SHA256(api_key, Response-Timestamp + partner_id + 'sid_request')) ne couvre PAS le corps. Un en-tête valide rejoué permettrait de forger un payload. Il faut une fenêtre de fraîcheur maison (±5 min, absente de la doc), l'idempotence par job_id, la concordance Job-ID / partner_params.job_id / job_id stocké, et une relecture via GET /v3/status/{job_id} avant toute transition APPROVED/REJECTED.
- Le payload du webhook Smile contient image_links (liens vers selfie/CNI), id_fields (numéro de pièce, date de naissance, adresse) et kyc_receipt. Ces données ne doivent jamais être journalisées en clair (Sentry SDK présent → scrubbing), ni renvoyées par une API publique, ni stockées hors du stockage private_kyc.
- Pas de faux KYC : le sandbox Smile renvoie des résultats SIMULÉS selon des noms de test (Clearwater/Amina Fatou → clear). Garde-fou obligatoire : en prod, refuser les identifiants ou l'URL sandbox. Sans prestataire configuré, toute soumission doit aller en REVIEW humaine, jamais en APPROVED automatique.
- Couverture Smile ID en CI : la vérification de document couvre IDENTITY_CARD (has_back=true, vérifié en direct), mais Biometric KYC (comparaison avec la base ONECI) est indisponible : NATIONAL_ID_NO_PHOTO, sans photo, n'est supporté qu'en Basic/Enhanced KYC. Enhanced Document Verification ne couvre pas la CI. La comparaison faciale se fait donc uniquement contre la photo imprimée sur la CNI.
- Flutter : usesmileid 12.2.0 exige Flutter 3.44+/Dart 3.12+, AGP 9.1 et Gradle 9, alors que l'environnement local est en Flutter 3.38.5 (pubspec sdk ^3.6.1). L'ancien smile_id 11.2.14 est compatible mais embarque une clé longue durée dans l'app (smile_config.json), à proscrire. Il faut choisir : montée de version Flutter, ou capture dans l'app + soumission multipart v3 par le backend.
- Web : le SDK Smile v12 est un script hébergé (cdn.usesmileid.com), pas un package npm. Il faut adapter la CSP de Next (next.config.mjs, en cours de modification par d'autres agents), servir en HTTPS et ajouter allow=camera si iframe. Le résultat fait foi uniquement côté webhook.
- Aucun CACHES n'est défini dans tratra/settings, donc LocMemCache propre à chaque processus. Les throttles DRF (login 10/min, futurs otp_send/otp_verify) et tout compteur OTP en cache sont inefficaces avec plusieurs workers gunicorn. Configurer un cache Redis (Redis déjà utilisé par Celery et Channels).
- OTPCode actuel (handy/models.py:995) : code stocké en clair et indexé, aucun compteur d'essais, lié à user et non au téléphone. otp_verify (views.py ~1103) ne limite pas les essais par code. otp_request renvoie le code si DEBUG (views.py ~1092). À migrer vers un code haché (HMAC avec pepper), un compteur d'essais, un challenge_id, et une invalidation au renvoi.
- Le paquet phonenumbers n'est pas installé dans le venv alors que django-phonenumber-field 8.1.0 l'est : tout PhoneNumberField ou validateur plantera à l'exécution. L'ajouter dans requirements.txt (django-phonenumber-field[phonenumbers]).
- Migration des numéros existants : User.phone est un CharField(20) unique et nullable, pouvant contenir des formats hétérogènes ou d'anciens numéros CI à 8 chiffres (avant le 31/01/2021), invalides pour phonenumbers. La normalisation E.164 doit conserver la valeur brute (colonne legacy), marquer comme non vérifiés les numéros invalides ou en doublon après normalisation, et ne jamais supprimer de comptes.
- Coûts et pumping SMS : Twilio coûte environ 0,44-0,49 $ par SMS vers la CI (+0,05 $ par vérification Verify), contre environ 7,26 XOF chez Orange CI. Une attaque de pumping peut multiplier la facture. Prévoir liste blanche de pays, plafonds par numéro, IP et préfixe, plafond quotidien global, CAPTCHA après N envois et alertes sur le taux de conversion.
- Orange SMS API CI : envoi uniquement à l'intérieur de la CI (impossible vers l'international), 5 SMS/s, senderName de 11 caractères maximum soumis à approbation. Le pré-enregistrement du sender ID alphanumérique prend environ 3 semaines (guidelines Twilio CI). Un second fournisseur est nécessaire pour l'international, et les délais administratifs sont à anticiper avant la mise en prod.
- Légal CI : la loi 2013-450 soumet le traitement de données biométriques (selfie, comparaison faciale) à une autorisation préalable de l'ARTCI. Le transfert vers un sous-traitant étranger (Smile ID) est à valider juridiquement. Le consentement doit être horodaté et archivé (champ consent v3 obligatoire, enregistrement ISO 27560 en retour).
- Anti-énumération contre ergonomie : avec un téléphone unique, l'inscription ne doit pas répondre « numéro déjà utilisé ». Utiliser une réponse identique et un SMS d'information au titulaire. Un backend d'authentification par téléphone personnalisé doit reproduire le hachage factice de ModelBackend pour éviter l'énumération par le temps de réponse.
- Fichiers backend handy/api/views.py, serializers.py et urls.py modifiés en ce moment par d'autres agents (git status M) : les numéros de ligne cités (views.py ~976, ~1085-1110, ~1266) peuvent avoir bougé.

## REUSE
- handy/storage.py:40 KycPrivateStorage (alias 'private_kyc', S3 privé en prod, FileSystem non public en dev) : stocker CNI recto/verso, selfie et preuves du prestataire.
- tratra/settings/base.py:293-315 KYC_MAX_UPLOAD_BYTES, KYC_ALLOWED_CONTENT_TYPES, KYC_SIGNED_URL_TTL_SECONDS=300 et STORAGES['private_kyc'] : contrôles d'upload et URL signées courtes pour le dashboard admin.
- handy/management/commands/migrate_kyc_documents_to_private_storage.py : modèle de commande de reprise en dry-run par défaut, réutilisable pour la migration sans perte (KYC et téléphones).
- handy/models.py:995 OTPCode (OTPCode.issue avec secrets.randbelow, TTL) : à étendre (phone_e164, code_hash, attempts, challenge_id, purpose reset/phone_change) plutôt qu'à recréer.
- handy/tasks.py:32 _send_sms (stub) : point d'injection unique à remplacer par une abstraction SmsBackend (console / orange_ci / twilio ou infobip) appelée via Celery (déjà en place).
- tratra/settings/base.py:205-215 DRF ScopedRateThrottle (scopes login/webhook existants) : ajouter les scopes otp_send, otp_verify, password_reset et kyc_webhook (avec un cache Redis partagé).
- tratra/settings/base.py:230-236 SIMPLE_JWT avec ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION et l'app token_blacklist (base.py:113) : révoquer tous les refresh tokens après reset ou changement de téléphone.
- django-axes 8.0.0 (base.py:101, 150, 180, 440-446 ; AXES_FAILURE_LIMIT=5, cooloff 1 h) : verrouillage par compte pour le login téléphone + mot de passe.
- django-phonenumber-field 8.1.0 (déjà installé) + paquet phonenumbers à ajouter : normalisation E.164 et validation côté serveur.
- requests 2.32.4 (déjà présent) : suffit pour l'API Smile ID v3 (POST /v3/token, POST /v3/document_verification multipart, GET /v3/status/{job_id}, GET /v3/services/supported_documents), sans SDK serveur.
- handy/api/views.py:~976 endpoint de revue KYC admin ({action: approve|reject, reason}) et :~932-949 téléchargement authentifié de pièce KYC : base pour le dashboard de validation humaine (REVIEW).
- handy/api/views.py:~1266 pattern de webhook avec throttle_scope='webhook' : à reprendre pour le callback Smile ID (csrf_exempt + vérification HMAC + idempotence).
- Exemple Django officiel Smile ID de vérification de webhook (hmac.new(api_key, f'{timestamp}{partner_id}sid_request', sha256) → base64 + hmac.compare_digest), à compléter par la fenêtre de fraîcheur et la relecture du statut.
- Endpoint public Smile GET /v3/services/supported_documents?country_code=CI&locale=fr-FR (sans authentification) : alimenter dynamiquement la liste des pièces et le besoin de verso (has_back) côté React et Flutter.
