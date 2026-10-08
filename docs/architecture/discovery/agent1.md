# agent1

## FINDINGS
## APP FLUTTER — état actuel (lecture seule, 2026-10-08)

Racine : `/Users/ogahserge/Documents/handy_tratra/flutter_tratra`.

**Ce n'est pas un dossier « sans git ».** Le dossier parent `/Users/ogahserge/Documents/handy_tratra/.git` est un dépôt avec un seul commit (`916ecbe tratra1`, 21 juin 2026) et beaucoup de travail non commité :
- 37 fichiers `lib/` modifiés.
- Fichiers non suivis : `lib/core/session.dart`, `lib/core/auth_http_client.dart`, `lib/screens/worker/`, `lib/services/handyman_service.dart`, `test/models_contract_test.dart`, `.github/workflows/mobile-ci.yml`.
- La CI fait `flutter analyze` puis `flutter test` avec Flutter 3.38.5.

### 0. Stack et dépendances (`pubspec.yaml`)
- SDK : `sdk: ^3.6.1`. Le `pubspec.lock` exige `dart >=3.10.0`, `flutter >=3.38.0`. Flutter installé : 3.38.5 stable.
- Versions présentes :
  - `http` 1.5.0, `provider` 6.1.5+1, `flutter_secure_storage` 9.2.4, `image_picker` 1.2.2
  - `intl` 0.20.2, `geolocator` 14.0.2
  - `shared_preferences`, `url_launcher`, `share_plus`, `cached_network_image`
- **Absents** :
  - pas de `camera`, ni `permission_handler`, ni SDK de liveness ou face match
  - pas de librairie téléphone (`phone_numbers_parser`, `intl_phone_field`, `libphonenumber`)
  - pas de champ OTP, ni `sms_autofill`, ni `firebase_messaging` (la clé `fcmTokenKey` existe mais n'est pas utilisée)
  - pas de `mime`/`http_parser` en dépendance directe
- Plateformes :
  - iOS : cible 13.0. `ios/Runner/Info.plist:48-51` contient NSPhotoLibrary et NSCamera (libellés KYC).
  - Android : `AndroidManifest.xml` ne déclare que la localisation et INTERNET. `image_picker` utilise la caméra système, donc pas de permission CAMERA. `minSdk = flutter.minSdkVersion`.

### 1. Couche réseau et auth
**`lib/core/constants.dart`**
- `baseUrl` = `String.fromEnvironment('TRATRA_API_BASE', defaultValue: 'https://tratra.net/handy')` (l.28-31).
- Endpoints : `usersEndpoint='/users'`, `usersMeEndpoint='/users/me/'`, `loginEndpoint`/`authLoginEndpoint='/auth/login/'`, `authRefreshEndpoint='/auth/refresh/'`, `authLogoutEndpoint='/auth/logout/'` (l.34-73).
- `otpRequestEndpoint='/auth/otp/request/'` et `otpVerifyEndpoint='/auth/otp/verify/'` (l.58-59) sont **définis mais jamais utilisés**.
- Rôles l.76-80 : `roleClient='client'`, `roleEmployer='employeur'`, `roleHandyman='handyman'`, `roleCompany='entreprise'`, `roleAdmin='admin'`.
- Clés de stockage : `auth_token`, `refresh_token`, `user_data`.

**`lib/core/base_api.dart`**
- Cache le token en mémoire (`_authToken`) avec `_didInit` : il ne lit le stockage chiffré **qu'une seule fois** (`initialize()` l.26-30).
- `setTokens()` l.43, `clearTokens()` l.52.
- `_refreshAccess()` l.60-85 : POST `/auth/refresh/ {refresh}` avec le client brut, puis enregistre `access` et le `refresh` tourné.
- `handleError` l.113-125 lance `Exception('Erreur ${code}: ${body}')`. Les erreurs ne sont pas typées.

**`lib/core/auth_http_client.dart`**
- Sur un 401 : un seul refresh puis rejoue la requête (l.19-37).
- Pas d'exclusion mutuelle ni de requête de refresh unique partagée.
- Si le refresh échoue, la requête est rejouée sans auth (l.29-31). L'utilisateur n'est ni déconnecté ni notifié.

**`lib/services/api_service.dart`** (ancien code, client `http.Client()` brut sans refresh, token uniquement en mémoire)
- `loginWithUsername(username, password)` l.72-110 : POST `/auth/login/` avec **`{'username', 'password'}`**. Écrit directement access et refresh dans `FlutterSecureStorage`, puis appelle `getCurrentUser()` (GET `/users/me/`).
- `registerWithDetails` l.511-595 : POST `/users/` avec `{first_name, last_name, email, username, phone, password}`. **Aucun `user_type`.** Ensuite connexion automatique via `/auth/login/` avec `{'username': username, ...}`.
- `register(...)` l.601-630 enveloppe cet appel.
- `_parseRegistrationError` l.632 renvoie le nom brut des champs (`email: ...`).
- `updateUser` l.151 : PATCH `/users/{id}/` avec `toProfileUpdateJson()`. **Jamais appelé.**
- `registerUser` l.54 envoie `user.toJson()`, qui contient `user_type`. **Code mort.**

**`lib/services/auth_service.dart`**
- `login({username,password})` l.14-35 envoie aussi `{'username', 'password'}`. **Jamais utilisé** (l'écran de login passe par ApiService).
- `logout()` l.37-57 : POST `/auth/logout/ {refresh}` en best-effort, puis `clearTokens`.
- `getCurrentUser()` l.59-66 : GET `/users/me/`.

**`lib/services/user_service.dart`** : `update(User)` en PATCH `/users/{id}/`. **Jamais utilisé.**

**`lib/services/storage_service.dart`** : stockage chiffré.
- `saveUserData` stocke `toStorageJson()`.
- `clearAuthData()` supprime token, refresh et user (l.47-51).

**`lib/models/user.dart`**
- Champs : `id`, `email` (String **non nullable**), `firstName`, `lastName`, `phoneNumber`, `profileImage`, `userType`, `dateJoined`, `isActive`, `preferences` (Map), `username`.
- Lecture (l.103-106) :
  - `phoneNumber` vient de `phone` ou `phone_number`
  - `profileImage` vient de `profile_picture` ou `profile_image`
  - `userType: _asString(json['user_type'], fallback: 'client')`
- **Non lus** alors que le backend les expose (`UserSerializer`, `handy/api/serializers.py:145-148`) : `is_verified`, `address`, `city`, `postal_code`, `country`, `latitude`, `longitude`.
- `toJson()` l.119-135 envoie toujours `'email': email` et `'user_type'`, plus `username`, `first_name`, `last_name` et **`phone`** s'ils sont non vides.
- `toProfileUpdateJson()` l.139-143 = toJson moins `user_type`. **Il envoie donc `phone` et `email`.**
- Test associé : `test/models_contract_test.dart:74-97` vérifie que `toProfileUpdateJson()` vaut `{email, username, first_name, last_name, phone}`.

**`lib/core/session.dart`** (ChangeNotifier)
- `isAuthenticated => _user != null` (l.21) : repose sur l'utilisateur en cache, **pas sur la validité du token**.
- `role => _user?.userType` (l.22).
- `isClient` couvre client et employeur. `isHandyman => role=='handyman'` (l.26).
- `homeRoute()` l.65-68 : `'/worker'` si handyman, sinon `'/'`.
- `refreshProfile()` l.44 et `logout()` l.55.

### 2. Écrans d'auth
**`lib/screens/auth/login_screen.dart`**
- Champ libellé « Email ou nom d'utilisateur » (l.262), validateur « Nom d'utilisateur requis » (l.305-308), clavier texte.
- `_login()` l.42-78 : `ApiService.loginWithUsername`, puis `saveAuthToken` et `saveUserData` en double, `Session.setUser`, puis `pushReplacementNamed(session.homeRoute())`.
- « Mot de passe oublié ? » est un `onPressed` vide (l.389-391).
- Les erreurs s'affichent brutes : `'Erreur de connexion : $e'`. Un mauvais mot de passe renvoie 401, affiché « Non autorisé - Veuillez vous reconnecter ». Un 429 affiche le corps brut.

**`lib/screens/auth/register_screen.dart`** (928 lignes)
- Champs : prénom, nom, **email obligatoire** (regex l.502-511), **username obligatoire** (l.568-571), téléphone (seulement non vide, l.628-631, aucun format ni indicatif), mot de passe (≥8, majuscule, minuscule, chiffre, l.114-131), confirmation, case CGU `_acceptTerms`.
- **Aucun choix Client/Artisan et aucun `user_type`** : tout compte créé depuis le mobile prend le défaut backend `client`.
- `_register()` l.65-112 : `ApiService.register`, puis enregistrement token et user, puis `pushReplacementNamed(RouteNames.home)`. **N'appelle pas `Session.setUser`**, donc la session n'est pas alimentée avant le prochain démarrage.
- Pas d'étape OTP.

**`lib/screens/auth/profile_screen.dart`** : lecture seule.
- Charge le cache puis `AuthService.getCurrentUser()`.
- Affiche avatar, nom, email, téléphone et « Type d'utilisateur » = `u.userType` (l.98-102), plus un bouton Déconnexion.
- Pas d'édition, ni upload photo, ni adresse, ni préférences, ni changement de téléphone.
- **Écran inaccessible depuis l'interface client** :
  - `home_screen.dart:598` contient `onProfileTap: () {}`.
  - Dans la barre du bas (`_PremiumBottomNav`, l.944-947 et 2578-2603), « Profil », « Réservations » et « Messages » ne font que `setState(_navIndex)`, que le body ignore.
  - Conséquence : **le client n'a ni profil ni déconnexion.**

### 3. Routage (`lib/main.dart`, `lib/routes.dart`)
- `main.dart:248-250` : `initialRoute = !session.isAuthenticated ? '/login' : (session.isHandyman ? '/worker' : RouteNames.home)`. **Le catalogue n'est donc pas consultable sans connexion.**
- `_generateRoute` l.132-222 : `/`, `/worker`, `/login`, `/register`, `/profile`, `/booking`, `/payment`, etc. Aucune garde d'auth par route ni redirection après connexion.
- Providers l.64-102 :
  - `Provider<BaseApi>.value`, `AuthService(baseApi)`, `ChangeNotifierProvider<Session>`
  - `ProxyProvider<BaseApi, X>` pour Booking, Payment, Handyman, Review, Messaging, Notification et Match
  - `Provider<ApiService>(create: (_) => ApiService())`

### 4. Catalogue (presque prêt à être public)
- `home_screen.dart:295-303`, `all_*_screen.dart` et `service_detail_screen.dart:51` ont un `_getPublic()` : appel avec auth, puis nouvel essai **sans** auth sur 401.
- Côté backend, `/services/` et `/categories/` sont `IsAuthenticatedOrReadOnly` et `/slides/` est AllowAny.
- **`artisan_profile_screen.dart:137`** appelle GET `/handymen/{id}/`, qui est `IsAuthenticated + IsOwnerOrAdmin` (`views.py:358`). Ce profil échoue donc hors connexion.
- Endpoints publics backend existants : `/handymen/featured/` (PublicArtisanSerializer) et `/reviews/public/`.
- `Artisan.fromJson` (`models/artisan.dart`) : `isCertified` vient de `is_approved | is_certified | isCertified`.
- `artisan_profile_screen.dart:119` ne lit que `isCertified`/`is_certified` et affiche le chip « Certifié » (l.311-315).
- `home_screen.dart:1466` et `1795` affichent en dur « Pros vérifiés » et « Vérifiés / Pros certifiés ».
- La réservation (`booking_screen.dart:133-203`, via `BookingApi`) n'a aucune garde de connexion : sans session, l'utilisateur ne voit qu'une erreur.
- Il n'existe aucun bouton « Proposer un service » ou « Devenir Handyman ».

### 5. Parcours Handyman (fichiers non suivis, modifiés le 7 oct. à 18:02)
**`lib/services/handyman_service.dart`** (155 l.), `class HandymanService extends BaseApi`, constructeur `HandymanService(BaseApi api, {super.client})`. **Le paramètre `api` est ignoré** : c'est une nouvelle instance BaseApi avec son propre token.

| Fonction | Requête | Remarque |
|---|---|---|
| `setPresence(bool)` l.17 | POST `/handymen/presence/ {online}` | 403 si `!is_approved`, 404 sans profil |
| `availableEarnings()` l.29 | GET `/payouts/available/` | lit `available` ou `amount` |
| `requestPayout(amount)` l.43 | POST `/payouts/` | |
| `getPayoutAccount()` / `upsertPayoutAccount(provider, accountRef)` l.55 / l.69 | `/payout-account/` | |
| `listDocuments()` l.84 | GET `/handyman-docs/` | |
| `uploadDocument(documentType, filePath, description?)` l.96-119 | multipart POST `/handyman-docs/`, champs `document_type`, `file`, `description` | voir bug ci-dessous |
| `plans(audience)`, `currentSubscription()`, `subscribe(planId)` l.123-154 | abonnements | |

**Bug KYC :** `uploadDocument` appelle `http.MultipartFile.fromPath('file', filePath)` sans `contentType`, ce qui donne par défaut `application/octet-stream` (source http-1.5.0 `multipart_file.dart:54`). Or `HandymanDocumentSerializer.validate_file` (`serializers.py` vers l.566-580) exige un content_type dans `KYC_ALLOWED_CONTENT_TYPES` (pdf, jpeg, png) cohérent avec l'extension. **Tout upload KYC mobile est donc rejeté en 400.**

**Rien ne couvre encore la candidature :** pas de création de profil artisan (POST `/handymen/`), pas de lecture de « mon profil artisan » ni de statut KYC, pas de skills, tarifs (`hourly_rate`, `daily_rate`...), zone, disponibilités ou `timeoffs` (constante `timeOffsEndpoint` inutilisée).

**`lib/screens/worker/kyc_screen.dart`** (227 l.)
- Types `_types` l.22-29 : `id_card`, `license`, `casier`, `insurance`, `certification`, `other`. Ils correspondent aux choix backend (`models.py:212-217`). Pas de recto/verso ni de selfie.
- Upload par `ImagePicker().pickImage(source, imageQuality: 80)` (l.82), avec choix galerie ou caméra.
- `_statusVisual` l.106-127 connaît seulement `approved` et `rejected` ; tout autre statut s'affiche « En attente ».
- Affiche `rejection_reason`.
- Pas de consentement, pas de statut KYC global, pas de resoumission ciblée.

**`lib/screens/worker/worker_home_screen.dart`** (754 l.) : onglets Missions, Gains, Compte.
- `_MissionsTab` : `BookingService.list()` (GET `/bookings/`) et bascule de présence. `_online` vaut `null` au départ ; l'état réel n'est jamais chargé.
- `_EarningsTab` : gains et compte de versement (om, mtn, moov, wave, bank).
- `_AccountTab` l.485-548 : nom, email, liens KYC et Abonnement Pro, déconnexion vers `/login`.
- Aucun affichage du statut KYC ou de publication, et pas de bascule vers le mode client.
- `StatusChip` est exporté (l.688).

**`lib/screens/worker/mission_detail_screen.dart`** : `BookingService.detail` puis `transition(id, status)`, soit POST `/bookings/{id}/transition/ {status}`.
- Actions : pending → confirmed/cancelled, confirmed → in_progress/cancelled, in_progress → completed (l.29-48).

**Autres services `extends BaseApi`** : `BookingService` (`list`, `detail`, `create`, `transition`), `PaymentService.initiate`, Review, Messaging, Notification, Match et `CategoryService`. Ils ont tous le même motif : `api` ignoré et une instance BaseApi distincte.

### 6. Bugs existants qui impactent la refonte
1. **Requêtes faites avec le compte précédent pendant ≤30 min.** Chaque service `extends BaseApi` garde son `_authToken` en mémoire (lu une seule fois), et `Session.logout()` ne vide que l'instance `Provider<BaseApi>`. Après une déconnexion suivie d'une connexion avec un autre compte, `BookingService` et `HandymanService` envoient encore l'access token du compte précédent jusqu'à son expiration (`ACCESS_TOKEN_LIFETIME=30min`). Le logout ne met en liste noire que le refresh.
2. **Refresh concurrent.** Il existe environ 9 instances BaseApi avec chacune son refresh, sans exclusion mutuelle. Avec `ROTATE_REFRESH_TOKENS` et `BLACKLIST_AFTER_ROTATION` actifs (`tratra/settings/base.py:230-236`), deux 401 simultanés font échouer le second refresh (token mis en liste noire) et provoquent des erreurs 401 visibles.
3. Après un refresh en échec, aucune déconnexion n'a lieu : l'interface reste « connectée » parce que `isAuthenticated` dépend du cache utilisateur.
4. L'upload KYC est rejeté (content-type, voir §5).
5. Le profil et la déconnexion sont inaccessibles côté client (voir §2).

### 7. Ce qui casse avec un compte unique et une connexion par téléphone
- **Login** : il faut envoyer `phone` (E.164) au lieu de `username`.
  - Code concerné : `api_service.dart:72-110`, `auth_service.dart:14-35`, libellé et validateur dans `login_screen.dart:262,305`, plus la connexion automatique `api_service.dart:550-557`.
  - Si le backend exige un OTP avant activation, la connexion automatique après inscription échoue.
- **Inscription** :
  - retirer `username` et l'email obligatoire (`register_screen.dart:455-571`) ;
  - normaliser le téléphone avec l'indicatif +225 ou international ;
  - ajouter un écran OTP (request puis verify) ;
  - les endpoints OTP actuels sont `IsAuthenticated` (`views.py:1083-1110`), ce qui ne convient pas à une vérification avant connexion ;
  - mapper les erreurs 400 par champ (`_parseRegistrationError`).
- **Rôle et routage** : `Session.isHandyman`, `homeRoute()`, `main.dart:248-250` et `profile_screen.dart:101` reposent sur `user_type == 'handyman'`.
  - Si `/users/me/` ne renvoie plus `user_type`, le repli `'client'` (`user.dart:106`) **fait perdre l'accès `/worker` aux artisans existants**.
  - Il faut un champ dérivé dans `/users/me/` (par exemple `handyman_status`, `kyc_status`, `is_handyman`, `capabilities`) et un sélecteur de mode client/artisan dans l'interface.
- **Email facultatif** : `User.email` est non nullable et `toJson` envoie toujours `'email': email`. Si l'email est vide, le PATCH envoie `""`, ce qui entre en conflit avec `email unique=True` (`handy/models.py:25`) dès le deuxième compte sans email.
  - `User.fullName` se rabat sur l'email (l.41).
  - `worker_home_screen.dart:511` et `profile_screen.dart:91` affichent l'email.
- **Changement de téléphone** : `toProfileUpdateJson()` envoie `phone`, ce qui contourne l'OTP si le backend accepte ce champ. Il faut le retirer du PATCH et mettre à jour le test `models_contract_test.dart:89-95`.
- **Profil** : il manque `is_verified`, l'adresse et la ville, l'upload multipart de `profile_picture` et les préférences en écriture. Aucun écran d'édition n'existe.
- **KYC** : statuts DRAFT/PENDING/REVIEW/APPROVED/REJECTED/SUSPENDED inconnus de l'interface. Il manque CNI recto/verso, selfie et liveness (aucune dépendance caméra ou SDK), consentement, et `contentType` sur le multipart.
- **Catalogue public** :
  - `initialRoute` doit devenir `/` ;
  - ajouter une garde « connexion requise » avec retour sur réservation, paiement, messagerie, profil et candidature ;
  - `/handymen/{id}/` doit passer par un endpoint public ;
  - le badge « Certifié » ne doit dépendre que d'un champ backend explicite d'identité vérifiée.

## DATA
Base dev Django (`DJANGO_ENV=dev`), lecture seule :
- **Utilisateurs** : 2 au total, répartis `user_type` handyman=1 et employeur=1. Aucun `client` en dev, ce qui ne représente pas la prod.
- **Téléphones** :
  - 1 utilisateur sans téléphone (null ou vide).
  - 0 téléphone ne commence par '+', '+225' ou '00225'.
  - Le seul téléphone présent est au format local à 10 chiffres commençant par '05'. Il faudra une normalisation E.164 et vérifier les doublons après normalisation.
- **Email** : 0 email vide. Le champ email est `unique=True` et non nullable (`handy/models.py:25`). Le téléphone est `unique=True`, `null=True`, max 20 caractères (`handy/models.py:37`).
- **Vérification et droits** : les 2 utilisateurs ont `is_verified=True` et `is_staff=True` ; l'un est superuser.
- **Profil artisan** : 1 seul (id=2, user_id=8), `is_approved=False`. Champs : `bio`, `experience_years`, `license_number`, `cni_number`, `insurance_info`, `commune`, `quartier`, `hourly_rate`, `daily_rate`, `monthly_rate`, `travel_fee`, `availability`, `is_approved`, `rating`, `completed_jobs`, `quality_score`, `photo`, `location`, `online`, `skills` ; relations `documents`, `service_area`, `availability_slots`, `time_off`.
- **Documents KYC** : 0 HandymanDocument.
- **JWT** (`tratra/settings/base.py:230-236`) : access 30 min, refresh 7 jours, `ROTATE_REFRESH_TOKENS` et `BLACKLIST_AFTER_ROTATION` à True.
- **Flutter** : SDK installé 3.38.5 ; lock `dart>=3.10.0`, `flutter>=3.38.0`.

## RISKS
- Fuite entre comptes : chaque service Flutter `extends BaseApi` ignore le `BaseApi` injecté et garde son propre `_authToken`, lu une seule fois (`base_api.dart:26-30`). Après une déconnexion puis une connexion avec un autre compte, BookingService et HandymanService envoient le token du compte précédent pendant ≤30 min. À corriger avant tout test de conversion Client→Handyman : un seul BaseApi partagé, vidé au logout.
- Refresh JWT non sérialisé (`auth_http_client.dart:19-37`) avec ROTATE et BLACKLIST actifs : les 401 simultanés de plusieurs instances provoquent des refresh en liste noire. Un échec de refresh ne déconnecte pas la Session (`isAuthenticated` dépend du cache utilisateur). Il faut une requête de refresh unique partagée et un callback onSessionExpired vers Session.logout.
- Repli `userType` = 'client' (`user.dart:106`) : si `/users/me/` cesse d'exposer `user_type`, les artisans existants perdent la route `/worker` (`main.dart:248-250`, `session.dart:26,65-68`). Il faut garder `user_type` en lecture pour la compatibilité, ou ajouter un champ dérivé (`handyman_status`, `kyc_status`) avant de changer le client. Les anciennes versions de l'app installées continueront d'envoyer `{username, password}` à `/auth/login/` et `{username, email, ...}` à `POST /users/`.
- Compatibilité des contrats : les apps mobiles déjà déployées appellent `POST /users/` (inscription), `POST /auth/login/` avec `username`, et `PATCH /users/{id}/` avec `email`, `username` et `phone`. Il faut versionner ou garder des alias (accepter `username` ou `email` ou `phone` au login) pendant la transition, sinon les apps existantes cassent.
- Email facultatif : `User.email` est non nullable côté Flutter et toujours envoyé (`user.dart:119-123`), alors que le backend a `email unique=True`. Si les emails vides deviennent `""`, il y aura une collision d'unicité. Il faut passer le champ en `null` (migration `null=True` et nettoyage des `''`) et ne pas l'envoyer quand il est vide.
- Changement de téléphone sans OTP : `toProfileUpdateJson()` envoie `phone` (`user.dart:131-133,139-143`). Le backend doit rendre `phone` en lecture seule au PATCH et passer par un flux dédié avec OTP. Le test `test/models_contract_test.dart:89-95` vérifie la présence de `phone` et devra être mis à jour (sinon la CI `.github/workflows/mobile-ci.yml` échoue).
- Upload KYC mobile actuellement cassé : `MultipartFile.fromPath` sans contentType envoie `application/octet-stream`, rejeté par `HandymanDocumentSerializer.validate_file`. Il faut ajouter `http_parser`/`mime` en dépendance directe et passer `MediaType('image','jpeg')`, etc. Cela vaut aussi pour la photo de profil et les justificatifs.
- Liveness et face match : aucune dépendance caméra ou SDK de prestataire dans le pubspec, et Android ne déclare pas la permission CAMERA. Un SDK comme Smile ID, Onfido ou Veriff demandera des changements natifs (Podfile iOS 13 minimum, minSdk Android) et un build natif. Ne jamais simuler un résultat de liveness ou d'APPROVED côté client.
- Catalogue public : `artisan_profile_screen.dart:137` appelle `/handymen/{id}/` (IsAuthenticated + IsOwnerOrAdmin), donc 401 hors connexion. `ServiceViewSet` (`views.py:484-491`, en cours de modification par d'autres agents) ne filtre pas sur `is_approved` : l'accueil Flutter peut afficher les services d'artisans non approuvés. Le badge 'Certifié' lit `is_approved`/`is_certified`, à aligner sur un champ explicite d'identité vérifiée.
- Passer `initialRoute` à `/` ouvre l'app sans session, mais `booking_screen`, `payment_screen`, `messaging` et `tracking` n'ont pas de garde d'auth : erreurs 401 brutes sans redirection. Il faut un helper `requireAuth` qui revient au point de départ après la connexion.
- Formats de téléphone hétérogènes en base : format local à 10 chiffres sans +225 en dev, `max_length=20`. La normalisation E.164 via une migration de données peut créer des collisions d'unicité. Il faut un script de détection de doublons avant la migration, et des fixtures de test avec indicatifs +225 et internationaux.
- Côté Flutter, le dépôt git parent `/Users/ogahserge/Documents/handy_tratra` a un seul commit et environ 50 fichiers modifiés ou non suivis (dont `session.dart`, `auth_http_client.dart`, `screens/worker/`, `handyman_service.dart`). Des commits par lots dans ce dépôt mélangeraient ce travail antérieur non commité : à clarifier avec l'utilisateur (commit de base séparé d'abord).
- Les endpoints OTP existants (`views.py:1083-1110`) exigent `IsAuthenticated` et envoient le SMS via `_send_sms`/`_resolve_msisdn`. Ils renvoient `code` en DEBUG et n'ont ni throttle dédié ni anti-énumération. Le futur contrat Flutter (OTP avant session) dépend d'une refonte de ces vues, actuellement modifiées par d'autres agents (`handy/api/views.py` modifié dans le git status).

## REUSE
- `lib/core/base_api.dart` : `setTokens`, `clearTokens`, `_refreshAccess` (gère déjà le refresh tourné), `headers`/`getHeaders(withAuth:)`, `decodeBody`, `extractResults`. À garder comme client unique partagé ; ne plus instancier un BaseApi par service.
- `lib/core/auth_http_client.dart` : intercepteur 401 → refresh → nouvel essai, qui fonctionne aussi pour le multipart car le corps est bufferisé. Ajouter seulement une requête de refresh unique partagée et un callback d'expiration.
- `lib/core/session.dart` (ChangeNotifier : `setUser`, `refreshProfile`, `logout`, `loadFromStorage`) : à garder comme source de vérité, en remplaçant `role`/`isHandyman` par des propriétés issues de `/users/me/` (statut handyman et KYC).
- `lib/services/storage_service.dart` : stockage chiffré Keychain/Keystore avec les mêmes clés que BaseApi (`auth_token`, `refresh_token`, `user_data`). Utilisable tel quel.
- `lib/services/auth_service.dart` : `logout()` (blacklist best-effort puis purge locale) et `getCurrentUser()` sont corrects. `login()` est à adapter au téléphone et doit devenir le seul chemin de connexion, à la place de `ApiService.loginWithUsername` et `registerWithDetails` (ancien code à retirer).
- `lib/models/user.dart` : parsing tolérant (`_firstPresent`, `_optionalString`, alias `phone`/`phone_number` et `profile_picture`/`profile_image`) et séparation `toJson`/`toProfileUpdateJson`/`toStorageJson`. À étendre (is_verified, adresse, statut handyman/KYC, email nullable).
- `lib/services/handyman_service.dart` : `setPresence`, `listDocuments`, `uploadDocument` (ajouter le contentType), versements, compte de versement et abonnements, déjà branchés sur les endpoints existants.
- `lib/screens/worker/worker_home_screen.dart` (onglets Missions, Gains, Compte, `StatusChip`), `mission_detail_screen.dart` (transitions de la machine à états `/bookings/{id}/transition/`) et `kyc_screen.dart` (sélection galerie/caméra via image_picker, affichage de `rejection_reason`). À enrichir plutôt qu'à réécrire.
- Le motif `_getPublic()` (avec auth, puis nouvel essai sans auth sur 401) de `home_screen.dart:295-303`, `all_*_screen.dart` et `service_detail_screen.dart` rend déjà le catalogue (services, catégories, slides) consultable sans connexion. Il suffit de changer l'`initialRoute`.
- Le validateur de mot de passe de `register_screen.dart:114-141` (≥8 caractères, majuscule, minuscule, chiffre, confirmation) et le flux CGU `_acceptTerms` peuvent être réutilisés tels quels.
- Backend réutilisable côté mobile : `/handymen/presence/` (garde `is_approved`), `/handymen/featured/` (PublicArtisanSerializer sans donnée sensible), `/reviews/public/`, `/handyman-docs/` (URL de téléchargement signée, `file` en écriture seule), le modèle `OTPCode.issue` et l'envoi SMS `handy.tasks._send_sms`/`_resolve_msisdn`.
- CI mobile existante `.github/workflows/mobile-ci.yml` (Flutter 3.38.5 : analyze, `test/models_contract_test.dart`, puis la suite complète) et les tests de contrat de `test/models_contract_test.dart`, à étendre pour les nouveaux contrats auth, profil et KYC.
