# agent3

## FINDINGS
## IDENTITÉ & AUTH — état actuel du backend (lecture seule, arbre de travail au 2026-10-08)

> Fichiers en cours de modification par d'autres agents (diff non commité) : `handy/api/serializers.py`, `handy/api/views.py`, `handy/api/urls.py` (lot 1 : catalogue public), `frontend/src/lib/types.ts`, et `handy/test_lot1_public.py` (nouveau). **Les parties auth de ces fichiers sont identiques à HEAD** (vérifié avec `git diff`). Les numéros de ligne ci-dessous correspondent à l'arbre de travail.

### 1. Modèle User — `handy/models.py:24-71`
- `class User(AbstractUser)`, sans manager personnalisé : `User.objects` est le `UserManager` standard. `create_user(username, email, password)`.
- `AUTH_USER_MODEL = 'handy.User'` (`tratra/settings/base.py:368`). Les valeurs effectives sont `USERNAME_FIELD='username'`, `REQUIRED_FIELDS=['email']` et `EMAIL_FIELD='email'` (vérifié dans le shell).
- Champs :
  - `email = EmailField(unique=True)` (l.25) : obligatoire, non nul, unique.
  - `username` (AbstractUser) : max 150 caractères, unique, `UnicodeUsernameValidator`.
  - `first_name`, `last_name`.
  - `user_type = CharField(max_length=20, choices=USER_TYPES, blank=True, null=True, default='client')` (l.34). Choix : `client`, `employeur`, `handyman` (« Artisan »), `entreprise`, `admin`.
  - `phone = CharField(max_length=20, blank=True, null=True, unique=True, db_index=True)` (l.37). Aucun validateur ni normalisation. Le commentaire dit « stocker en E.164 », mais rien ne l'impose. Comme `blank` est autorisé, une 2ᵉ valeur `''` provoquerait une IntegrityError.
  - Autres champs : `profile_picture` (ImageField `profile_pics/`), `address`, `city`, `postal_code`, `country`, `latitude`/`longitude` (Decimal), `last_location` (PointField), `last_location_ts`.
  - `is_verified = BooleanField(default=False, db_index=True)` (l.51). Seul `otp_verify` le met à True (views.py:1109).
  - `groups` et `user_permissions` sont redéfinis avec les `related_name` `handy_user_*`.
- Usages de `user_type` côté backend :
  - signaux `handy/signal.py:11-24` : un `HandymanProfile` est créé automatiquement si `created and user_type=='handyman'`, un `CompanyProfile` si `'entreprise'` ;
  - admin (`handy/admin.py:19-21,40,60`) ;
  - `validate_user_type` (serializers.py:155) ;
  - bloc `user` du login (l.204) ;
  - `handy/forms.py` (code mort) et `create_fake_data`.
  - **Aucune permission métier ne dépend de `user_type`.** `is_verified` n'est contrôlé nulle part : il ne conditionne ni la réservation ni le login.

### 2. Inscription — `POST /handy/users/` (`UserViewSet.create`)
- `views.py:303-325` : `get_permissions()` renvoie `AllowAny` pour `create` et `IsAuthenticated` sinon. `get_queryset` limite un non-staff à son propre compte (anti-IDOR, l.312-318). Le queryset utilise `.only("id","email","first_name","last_name","user_type","is_verified")`.
- `UserSerializer` (`serializers.py:139-175`) :
  - champs `id, username, email, first_name, last_name, user_type, phone, profile_picture, address, city, postal_code, country, latitude, longitude, is_verified, date_joined, last_login, password` ;
  - en lecture seule : `id, date_joined, last_login, is_verified` ;
  - `password = CharField(write_only=True, required=True)`.
  - `SELF_SIGNUP_ROLES = {"client","employeur","handyman","entreprise"}` ; `validate_user_type` refuse `admin` aux non-staff.
  - `create()` (l.167-175) force `is_staff=False` et `is_superuser=False`, puis appelle `set_password`.
- **`validate_password` n'est jamais appelé** : les `AUTH_PASSWORD_VALIDATORS` sont ignorés par l'API.
- **Aucun `update()` surchargé.** `PATCH /users/{id}/ {"password": "x"}` passe par `ModelSerializer.update`, qui fait un `setattr` : le mot de passe est **stocké en clair** et le compte devient inutilisable.
- Réponse 201 : le `UserSerializer` complet (téléphone, adresse, coordonnées).
- Énumération : les `UniqueValidator` sur `email`, `username` et `phone` renvoient « existe déjà ». Seul le throttle anon de 60/min protège cet endpoint.

### 3. Profil
- `GET /handy/users/me/` uniquement (`@action me`, views.py:327-332). Pas de PATCH sur `/me/`.
- La modification passe par `PATCH /handy/users/{id}/` : c'est ce qu'utilise Flutter (`lib/services/user_service.dart:12-20`).
  - Un non-staff peut y changer `username`, `email` et `phone` **sans revérification** (`is_verified` reste True).
  - Il peut aussi changer `user_type` vers n'importe quel rôle de `SELF_SIGNUP_ROLES`, ce qui ne crée **pas** de `HandymanProfile`, car le signal ne réagit qu'à la création.
- `DELETE /users/{id}/` est permis au propriétaire (`ModelViewSet`). C'est une suppression définitive, avec CASCADE sur `Booking.client`/`handyman` (models.py:438-439), donc sur `Payment` (OneToOne booking CASCADE), les payouts, les dépôts, etc.
- `POST /users/{id}/update_location/` (l.334-348).
- Aucun endpoint de changement de mot de passe ni de réinitialisation : les URLs allauth ne sont pas montées (`tratra/urls.py:58-71`).

### 4. Login — `POST /handy/auth/login/` (`urls.py:41`)
- `EmailOrUsernameTokenObtainPairView` (views.py:299-301), avec `throttle_scope="login"`.
- `EmailOrUsernameTokenObtainPairSerializer` (serializers.py:177-208) :
  - Le champ attendu est `username`, imposé par `TokenObtainSerializer.__init__` (champ `USERNAME_FIELD` obligatoire). La branche `attrs.get("email")` est donc **morte**.
  - Appelle `authenticate(request, username=<saisie>, password)`. L'ordre des backends est `axes.AxesStandaloneBackend` (contrôle du verrouillage par IP), puis `ModelBackend` (username exact), puis `allauth.AuthenticationBackend`. Ce dernier, comme `ACCOUNT_LOGIN_METHODS={"username","email"}`, essaie d'abord l'email (iexact) puis le username. Il atténue la différence de temps de réponse et respecte `is_active`.
  - Appelle ensuite `super().validate({"username": user.get_username(), ...})`, ce qui provoque un **2ᵉ `authenticate`** (double hachage).
  - En cas d'échec : `raise self.fail("no_active_account")`, soit une **HTTP 400** `{"non_field_errors": [...]}` (et non 401). Le message est identique pour mot de passe faux, compte inactif ou verrou axes, ce qui est bon contre l'énumération.
  - Réponse : `{refresh, access, user:{id, email, username, first_name, last_name, is_active, date_joined, user_type, profile_image, phone_number}}`. `profile_image` et `phone_number` n'existent pas sur le modèle et valent **toujours `None`**. Le bloc ne contient pas `is_verified`.
- `POST /handy/auth/refresh/` : `TokenRefreshView` simplejwt, sans throttle dédié.
- `POST /handy/auth/logout/` : `TokenBlacklistView` (`{"refresh"}`, sans authentification).

### 5. SIMPLE_JWT — `base.py:230-236`
- `ACCESS_TOKEN_LIFETIME=30min`, `REFRESH_TOKEN_LIFETIME=7j`, `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`, `UPDATE_LAST_LOGIN=True`.
- Valeurs par défaut : `ALGORITHM='HS256'`, `SIGNING_KEY=SECRET_KEY`, `CHECK_USER_IS_ACTIVE=True`, `CHECK_REVOKE_TOKEN=False` (l'option `REVOKE_TOKEN_CLAIM='hash_password'` existe dans la version 5.5.1 mais n'est pas activée).
- `rest_framework_simplejwt.token_blacklist` est installé (base.py:113). Le refresh vérifie `is_active`.
- Le dev ne peut pas utiliser le fallback `SECRET_KEY='django-insecure-...'` en prod : `prod.py:23-24` le refuse.

### 6. django-axes 8.0.0, allauth 65.9.0 et backends
- Configuration (`base.py:441-446`) : `AXES_FAILURE_LIMIT=5`, `AXES_COOLOFF_TIME=1` (en heures), `AXES_LOCK_OUT_AT_FAILURE=True`, `AXES_ENABLE_ADMIN`, `AXES_VERBOSE`, `AXES_LOCKOUT_TEMPLATE='403.html'`.
- Valeurs effectives (vérifiées) : `AXES_LOCKOUT_PARAMETERS=['ip_address']` (le boot affiche « blocking by ip_address »), `AXES_USERNAME_FORM_FIELD='username'`, `AXES_RESET_ON_SUCCESS=False`, `AXES_HTTP_RESPONSE_CODE=429`, `AxesDatabaseHandler`, `AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT=True`.
  - Avec ce dernier réglage, `request.axes_locked_out` n'est jamais posé : `AxesMiddleware` (base.py:150) ne renvoie donc pas de 429, et le login renvoie simplement la 400 générique.
- **`django-ipware` n'est pas installé**, donc l'IP vient de `REMOTE_ADDR`. Or la prod lance daphne **sans `--proxy-headers`** derrière Traefik (Dockerfile:48, docker-compose.yml:110) : l'IP vue est celle du proxy.
- `AUTHENTICATION_BACKENDS` (base.py:179-183) : `AxesStandaloneBackend`, `ModelBackend`, `allauth...AuthenticationBackend`.
- allauth :
  - installé avec les providers sociaux linkedin, google et facebook (base.py:93-99) et `AccountMiddleware` (l.145) ;
  - `ACCOUNT_LOGIN_METHODS={"username","email"}`, `ACCOUNT_SIGNUP_FIELDS=[email*,password1*,password2*]`, `ACCOUNT_UNIQUE_EMAIL=True` (l.191-193) ;
  - `ACCOUNT_FORMS['signup']='handy.forms.CustomSignupForm'` (l.460-462) ;
  - **aucune URL allauth montée**. `handy/forms.py:34-125` (`CustomSignupForm`, `EmployerSignupForm`, `HandymanSignupForm`) est du code mort de l'ère SSR. allauth ne sert plus qu'au backend de login par email.
  - allauth 65.9 sait gérer `LoginMethod.PHONE` (`_authenticate_by_phone`, via `adapter.get_user_by_phone`), mais ce n'est pas configuré.
- `LOGIN_REDIRECT_URL='handydash'` est un résidu (la route n'existe plus).

### 7. OTP et SMS
- `OTPCode` (`models.py:995-1017`) :
  - champs `user` (FK CASCADE), `code` (CharField(6), **en clair**, indexé), `purpose` (choix `signup`, `login`, `phone`, défaut `signup`), `created_at`, `expires_at`, `used` (bool) ;
  - index sur `(user, used, -created_at)` ;
  - `is_valid()` vaut `not used and now <= expires_at` ;
  - `issue(user, purpose='signup', ttl_minutes=10)` génère le code via `secrets.randbelow(10**6)`.
  - Pas de compteur de tentatives, pas de champ téléphone cible, pas d'invalidation des codes précédents. Créé par la migration 0023.
- `otp_request` (`views.py:1081-1093`, `POST /handy/auth/otp/request/`, `IsAuthenticated`) :
  - émet toujours avec `purpose="signup"` et appelle `_send_sms(_resolve_msisdn(user.id), "Votre code de vérification Tratra : {code}")` ;
  - si `settings.DEBUG`, **le code est renvoyé dans la réponse**.
  - Aucune limitation propre : seul le throttle `user` de 1000/h s'applique.
- `otp_verify` (`views.py:1096-1111`, `POST /handy/auth/otp/verify/`, `IsAuthenticated`, body `{code}`) :
  - fait `filter(user, code, used=False).latest`, sans vérifier le `purpose` ;
  - en cas de succès, met `used=True` et `user.is_verified=True` ; sinon renvoie 400 « Code invalide ou expiré. ».
  - Plusieurs codes peuvent être valides en même temps, et le nombre d'essais n'est pas limité. **Un brute-force du code à 6 chiffres est donc possible.**
- `handy/tasks.py:14-17` : `_resolve_msisdn` renvoie `user.phone` tel quel.
- `handy/tasks.py:32-36` : `_send_sms` est un **stub** qui exécute `logger.info("SMS (stub) -> %s : %s", msisdn, message)`. Il **journalise donc le code OTP en clair** (niveau INFO en prod). Il n'y a aucun fournisseur branché.
- Le `.env` local (non suivi, `.gitignore:142`) contient des clés `TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE_NUMBER/MESSAGING_SERVICE_SID` et `ORANGE_SMS_CLIENT_ID/CLIENT_SECRET/SENDER` (valeurs non reproduites ici). Aucune n'est lue par le code ni présente dans `.env.example`.
- Autre usage SMS : `notify_arrival_imminent` (tasks.py:73-75). La seule autre notification, `notify_booking_status`, passe par la base et FCM (`_send_fcm`).

### 8. Throttling, CORS, CSRF, cookies, validateurs
- `REST_FRAMEWORK` (`base.py:195-216`) :
  - authentification JWT seule ; permission par défaut `IsAuthenticated` ;
  - throttles `Anon`, `User` et `Scoped` ;
  - taux : `anon` 60/min, `user` 1000/h, `login` 10/min, `webhook` 120/min (surchargeables par env).
  - `NUM_PROXIES` n'est pas défini. `get_ident` utilise alors **la chaîne X-Forwarded-For entière**, ce qui est falsifiable.
  - **Pas de `CACHES`**, donc `LocMemCache` par processus (vérifié).
- CORS (`base.py:126-135`) : liste blanche pilotée par env (localhost:3000 en dev), `CORS_ALLOW_CREDENTIALS=True`. En prod, la liste vient de l'env (`prod.py:64-65`).
- Cookies et CSRF :
  - en dev (`dev.py:45-55`) : `SESSION_COOKIE_SECURE` et `CSRF_COOKIE_SECURE` à False, plus des `CSRF_TRUSTED_ORIGINS` en localhost ;
  - en prod (`prod.py:45-63`) : cookies Secure et HttpOnly (session), `SameSite=Lax`, HSTS, `SECURE_PROXY_SSL_HEADER`, `CSRF_TRUSTED_ORIGINS` venant de l'env.
- `SessionAuthentication` n'est activée que sur `HandymanDocumentViewSet` (views.py:933), pour le téléchargement depuis l'admin.
- `AUTH_PASSWORD_VALIDATORS` (`base.py:240-253`) : les 4 validateurs Django standards. Ils rejettent `pass1234` (« trop courant », vérifié) mais ne sont pas appliqués par l'API.
- `IPBlacklistMiddleware` (`handy/middleware.py:16-22`) prend le 1er élément de X-Forwarded-For (falsifiable) et fait une requête en base à chaque appel.
- WebSocket (`tratra/asgi.py:23-25`) : `AuthMiddlewareStack` (session), donc pas de JWT.

### 9. Points Handyman/KYC qui touchent l'identité (à corriger dans la refonte)
- `HandymanProfileSerializer` (`serializers.py:211-265`) :
  - `user = PrimaryKeyRelatedField(queryset=User.objects.all())` est modifiable ;
  - **`is_approved`, `rating`, `completed_jobs`, `cni_number` et `license_number` sont modifiables** (pas de `read_only_fields`).
  - `HandymanProfileViewSet` (views.py:352-365) n'a **ni `perform_create` ni `get_queryset` restreint**. Conséquence : `POST/PATCH /handymen/` permet de s'auto-approuver ou de créer le profil d'un autre utilisateur, et la liste montre à tout utilisateur authentifié le `cni_number`, la licence, la position exacte et l'email (`UserMiniSerializer`).
- Le badge public est ambigu :
  - `PublicArtisanMiniSerializer.is_verified` vaut `is_approved` (serializers.py:84) ;
  - mais `PublicUserMiniSerializer` (l.72-78, utilisé dans `/services/` via `handyman_detail`) expose **`user.is_verified`**, c'est-à-dire l'OTP téléphone.
- `HandymanDocument.approve/reject` (models.py:236-250) ne met pas `is_approved` à jour. L'admin le fait via `approve_profiles` (`admin.py:159-162`, `queryset.update(is_approved=True)`, sans aucune vérification). `/handyman-docs/{id}/review/` est contrôlé par `IsAdminUser`, soit `is_staff` (views.py:974).
- Le seul RBAC existant est `is_staff`. Aucun groupe ni permission n'est utilisé.
- Les apps `simple_history` et `actstream` sont installées mais aucun modèle `handy` ne les utilise.
- `apply_public_service_filters` (views.py:236-263) n'impose `is_approved` que si `verified=1`. Par défaut, `/services/` liste donc aussi les artisans non approuvés.

### 10. Contrats consommés par les clients
- React (`frontend/src/lib/api.ts`) :
  - jetons en `sessionStorage` (l.13-20), `credentials:"omit"` ;
  - `login(username, password)` appelle `/auth/login/` et utilise `data.user ?? me()` (l.251-258) ;
  - `register` envoie `{username, email, password, user_type, first_name, last_name, phone}` sur `/users/`, puis appelle `login` (l.262-273) ;
  - `logout` passe par `/auth/logout/` ;
  - le routage dépend de `user_type` (`RoleGuard.tsx:27`, `HOME_BY_ROLE`, `links.ts:62-75`).
- Flutter (`/Users/ogahserge/Documents/handy_tratra/flutter_tratra`) :
  - endpoints déclarés dans `lib/core/constants.dart:35-73` (`/users/me/`, `/auth/login|refresh|logout/`, `/auth/otp/request|verify/`). Les constantes OTP sont **déclarées mais jamais appelées**.
  - `registerWithDetails` (`api_service.dart:~507-560`) envoie `first_name, last_name, email, username, phone, password` sans `user_type`, puis se connecte avec `username`.
  - `User.fromJson` lit `phone` ou `phone_number` (`models/user.dart:103`).
  - PATCH sur `/users/{id}/`.

### 11. Tests existants liés (à garder verts ou à migrer)
- `handy/test_security_sprint1.py:46` `test_signup_rejette_role_admin` et `:57` `test_signup_client_ok_sans_privilege` : POST `users-list` avec `username`, `email`, `password="pass1234"` et `user_type`. **Ils casseront** dès que `validate_password` sera appliqué ou que `user_type` disparaîtra.
- `handy/test_phase1.py:15` `test_inscription_entreprise_cree_profil` : inscription `user_type=entreprise` puis vérification du signal `CompanyProfile`. Même problème.
- `handy/test_sprint6.py:65` `test_otp_request_puis_verify` (lit `otp.code` en base) et `:84` `test_otp_expire_rejete` (crée `OTPCode(code="123456")`). Les deux dépendent du **code stocké en clair**.
- KYC et présence : `test_sprint4bis.py:68,97,114,129,145,156` et `test_sprint2.py:117`.
- Les fixtures de presque tous les tests font `create_user(..., user_type="handyman")` et comptent sur le signal pour créer `HandymanProfile` (au moins 14 appels à `HandymanProfile.objects.get(user=...)`).
- **Aucun test** ne couvre `/auth/login/`, `/auth/refresh/`, `/auth/logout/`, `/users/me/` ni `PATCH /users/{id}/`. Tous les tests s'authentifient avec `force_authenticate`.
- `pytest.ini` : `DJANGO_SETTINGS_MODULE=tratra.settings` (dev, PostGIS).

### 12. Dépendances (`requirements.txt`)
- Django 4.2.23, djangorestframework 3.16.0 (l.60), simplejwt 5.5.1 (l.61), django-axes 8.0.0 (l.39), django-allauth 65.9.0 (l.38), django-cors-headers 4.7.0, redis 6.2.0, celery 5.5.3.
- `django-otp==1.6.0` (l.52) est présent mais ne figure pas dans `INSTALLED_APPS`.
- **`django-phonenumber-field==8.1.0` (l.53) est présent, mais la bibliothèque `phonenumbers` est absente** : `import phonenumber_field.phonenumber` échoue avec `ModuleNotFoundError`.
- Pas de `django-ipware`, pas de `django-redis`. Django 4.2 propose en natif `RedisCache` avec le paquet `redis`.
- Versions de Python : venv local en 3.9, Docker et CI en 3.12.

## DATA
La base dev est PostGIS (`tratra` sur localhost:5433) ; les mesures ont été faites en lecture seule le 2026-10-08.

**Utilisateurs (2 au total)**
- Par `user_type` : `employeur` = 1 (id 1), `handyman` = 1 (id 8). Aucun `client`, `entreprise` ni `admin`, et aucun `user_type` nul.
- Superuser : 1 (id 1, de type `employeur`, sans téléphone).
- Staff : 2. L'artisan id 8 est `is_staff=True` (sans être superuser) : il passe donc `IsAdminUser` et peut réviser son propre KYC via `/handyman-docs/{id}/review/`.
- Tous les comptes sont actifs et `is_verified=True`. Tous ont un email (domaines gmail.com et yahoo.fr), un prénom, un nom et un mot de passe utilisable.
- Aucun username n'a la forme d'un email ou d'un téléphone.

**Téléphones**
- 1 renseigné, 1 NULL, 0 chaîne vide.
- Échantillon de formats (il n'en existe qu'un) : `057535XXXX`, soit 10 chiffres au format local ivoirien sans `+225`. La normalisation E.164 devra ajouter `+225` aux numéros CI à 10 chiffres.
- Doublons après normalisation naïve (chiffres seuls) : 0.

**Profils et KYC**
- `HandymanProfile` : 1 (id 2, user 8), `is_approved=False`, `online=False`, `commune=None`, `experience_years=5`.
- `HandymanDocument` : 0.
- `CompanyProfile` : 0.

**Activité et tables d'auth**
- `OTPCode` : 0 ; `Booking` : 1 ; `Payment` : 0 ; `Service` : 2 ; `Device` et `GCMDevice` : 0.
- simplejwt : `OutstandingToken` = 0, `BlacklistedToken` = 0.
- axes : `AccessAttempt` = 1, `AccessLog` = 32, `AccessFailureLog` = 0.
- allauth : `SocialAccount` = 0, `SocialApp` = 0, `EmailAddress` = 1.

**Migrations et base legacy**
- La dernière migration `handy` appliquée en dev est `0026_seed_subscription_plans`. **`0027_private_kyc_document_storage` n'est pas appliquée** (retard de la base dev).
- `db.sqlite3` (legacy, ouvert en lecture seule) : 0 utilisateur, seule `0001_initial` y est appliquée. Il n'y a rien à reprendre.

**Validateurs de mot de passe**
- `pass1234` (utilisé par les tests) est rejeté par `CommonPasswordValidator`.

**Volume réel à migrer :** la base dev est quasi vide. Le volume réel de prod est inconnu et doit être mesuré avant la migration de normalisation des téléphones et de rendu de l'email facultatif.

## RISKS
- CRITIQUE : PATCH /handy/users/{id}/ avec {"password": ...} stocke le mot de passe en clair. UserSerializer (handy/api/serializers.py:139-175) n'a pas d'update(), donc ModelSerializer.update fait un setattr. À corriger dès le 1er lot : retirer password des champs modifiables et créer un endpoint dédié de changement de mot de passe.
- CRITIQUE KYC : HandymanProfileSerializer (serializers.py:211-235) laisse modifiables is_approved, rating, completed_jobs, cni_number et user (PK sur tous les User), et HandymanProfileViewSet (views.py:352-365) n'a ni perform_create ni get_queryset restreint. Tout utilisateur authentifié peut donc s'auto-approuver (profil publié dans featured, matching et stats) ou créer le profil d'un autre. La liste /handymen/ expose aussi cni_number, licence, position exacte et email (UserMiniSerializer) à tout utilisateur connecté.
- Perte de données : DELETE /handy/users/{me}/ est autorisé au propriétaire (ModelViewSet) et fait une suppression définitive, avec CASCADE sur Booking.client/handyman (models.py:438-439), donc sur Payment (OneToOne CASCADE), Payout, DepositTransaction, HandymanProfile et les documents KYC. La refonte doit interdire cette action ou la remplacer par une désactivation.
- Anti-bruteforce inefficace derrière Traefik. Axes verrouille par ip_address seulement, avec REMOTE_ADDR, car django-ipware est absent et daphne tourne sans --proxy-headers (Dockerfile:48). En prod, toutes les requêtes partagent l'IP du proxy : 5 échecs par heure bloquent tous les logins, admin compris, et chaque échec pendant le verrou le prolonge (AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT=True). À l'inverse, le throttle DRF identifie le client par la chaîne X-Forwarded-For entière (NUM_PROXIES absent) : un en-tête falsifié suffit à le contourner. IPBlacklistMiddleware (handy/middleware.py:16-22) prend lui aussi le 1er élément de X-Forwarded-For, falsifiable.
- Pas de CACHES configuré, donc LocMemCache par processus : throttles, et futurs cooldowns OTP ou anti-énumération, ne sont pas partagés entre processus ou conteneurs. Il faut configurer django.core.cache.backends.redis.RedisCache (paquet redis déjà installé).
- OTP non sûr. Codes stockés en clair (OTPCode.code), pas de compteur de tentatives, codes précédents non invalidés, purpose ignoré au verify et pas de throttle_scope (seulement user 1000/h) : brute-force et envoi massif de SMS possibles. _send_sms (handy/tasks.py:32-36) est un stub qui journalise le code OTP en clair au niveau INFO. otp_request renvoie le code si DEBUG. Aucun fournisseur SMS réel n'est branché : il ne faut pas livrer un parcours dont l'OTP n'arrive jamais. Si les codes sont hachés, test_sprint6.py:65 et :84 (qui lisent et créent un code en clair) devront être migrés.
- Contrat de login : le champ attendu est 'username', imposé par TokenObtainSerializer à partir de USERNAME_FIELD ; axes utilise aussi AXES_USERNAME_FORM_FIELD = USERNAME_FIELD. Passer USERNAME_FIELD à phone renommerait le champ et casserait React (api.ts:251-258) et Flutter (api_service.dart loginWithUsername). Mieux vaut garder USERNAME_FIELD='username' et ajouter un backend ou serializer téléphone, ou accepter un identifiant normalisé, avec AXES_USERNAME_CALLABLE et AXES_LOCKOUT_PARAMETERS combinant identifiant et IP.
- Énumération à l'inscription : les UniqueValidator sur email, username et phone renvoient 'existe déjà' sur POST /users/, et seul le throttle anon (60/min, contournable via X-Forwarded-For) protège l'endpoint. Le futur flux d'inscription et de récupération doit répondre de façon uniforme.
- validate_password n'est jamais appelé par l'API. Le brancher cassera test_security_sprint1.py:46/:57 et test_phase1.py:15, qui inscrivent avec 'pass1234' (rejeté par CommonPasswordValidator).
- Email facultatif : User.email est unique=True, null=False, blank=False (models.py:25), donc une migration est nécessaire (null=True, conversion de '' en NULL, pour éviter les collisions uniques sur ''). Il faut aussi tenir compte d'allauth (ACCOUNT_UNIQUE_EMAIL, table EmailAddress, backend de login par email), de REQUIRED_FIELDS=['email'] pour createsuperuser et de l'index Meta sur email. username reste obligatoire et unique : il faudra en générer un (uuid ou dérivé) pour les comptes créés par téléphone.
- Téléphone : CharField(20) unique nullable sans normalisation ; '' passe par l'API et un 2e '' provoquerait une IntegrityError (erreur 500). Les données dev sont au format local à 10 chiffres sans +225 ; une migration E.164 est nécessaire avec détection préalable des doublons et une stratégie de conflit. django-phonenumber-field 8.1.0 est épinglé mais la bibliothèque phonenumbers (ou phonenumberslite) manque : à ajouter dans requirements.txt.
- Suppression du choix Client/Artisan : user_type sert au routage React (RoleGuard.tsx:27, HOME_BY_ROLE, links.ts), aux signaux de création de HandymanProfile et de CompanyProfile (signal.py:11-24), aux filtres admin et au B2B 'entreprise'. Il existe aussi des comptes 'employeur' (le superuser dev). Il faut garder le champ (déprécié, valeur 'client' par défaut) pour la compatibilité, et rendre la création du HandymanProfile explicite par la candidature plutôt que par le signal sur user_type. Les fixtures de nombreux tests créent des artisans via user_type='handyman' et ce signal.
- Sémantique des badges : user.is_verified signifie aujourd'hui 'OTP téléphone validé', mais il est aussi posé à la main par l'admin et les fixtures. PublicUserMiniSerializer l'expose publiquement dans /services/ (handyman_detail.is_verified), alors que PublicArtisanMiniSerializer.is_verified correspond à is_approved (KYC). Risque d'afficher un faux badge 'Identité vérifiée' : il faut des champs distincts (phone_verified et identity_verified ou statut KYC).
- is_verified n'est vérifié nulle part : ni au login, ni à la réservation. Le nouveau contrôle 'compte vérifié requis pour réserver' sera un changement de comportement pour les comptes existants non vérifiés ; prévoir une reprise (OTP au prochain login, par exemple).
- JWT : l'access token (30 min) n'est pas révoqué après un changement de mot de passe, de téléphone ou une suspension, car CHECK_REVOKE_TOKEN=False ; is_active n'est vérifié qu'au moment du refresh et de l'authentification. Le refresh dure 7 jours. Les jetons sont en sessionStorage côté React, donc exposés au XSS. Passer à un cookie HttpOnly impose de traiter CSRF et SameSite (CORS_ALLOW_CREDENTIALS=True, front et API sur des origines différentes) et de garder un mode bearer pour Flutter, qui utilise FlutterSecureStorage.
- Bloc user de la réponse de login (serializers.py:196-207) : profile_image et phone_number sont toujours None, is_verified est absent, et un échec renvoie 400 non_field_errors au lieu de 401. React utilise ce bloc à la place de /users/me/ (api.ts:257), ce qui donne des données incomplètes. Le nouveau contrat doit renvoyer le même objet que /users/me/.
- Fichiers partagés avec d'autres agents en cours (diff non commité) : handy/api/serializers.py, views.py et urls.py (lot 1 public), plus frontend/src/lib/types.ts. Risque de conflits : isoler la nouvelle auth dans des modules dédiés (par exemple handy/api/auth_views.py et auth_serializers.py, et handy/services/otp.py / sms.py), et ne toucher urls.py que de façon additive.
- Le venv local est en Python 3.9 alors que Docker et la CI sont en 3.12 : éviter la syntaxe 3.10+ (match, annotations X | None évaluées à l'exécution sans from __future__ import annotations).
- La base dev est en retard d'une migration : 0027_private_kyc_document_storage n'est pas appliquée. Les nouvelles migrations doivent dépendre de 0027 et s'appliquer proprement sur une base en 0026.
- Le WebSocket (tratra/asgi.py) n'authentifie que par session (AuthMiddlewareStack) : les clients JWT (React et Flutter) y sont anonymes. Hors périmètre immédiat, mais incohérent avec un compte unique en JWT.
- Les clés SMS Twilio et Orange existent dans le .env local non suivi, mais ne figurent ni dans .env.example ni dans les settings. Il faudra ajouter des variables SMS_PROVIDER et associées, sans valeur par défaut, et refuser l'envoi d'OTP en prod sans fournisseur configuré (comme payment_initiate le fait avec une 503).
- Le catalogue public /services/ (apply_public_service_filters, views.py:236-263) inclut par défaut les artisans non approuvés (le filtre verified=1 est optionnel), ce qui contredit l'exigence 7 de ne publier que les profils APPROVED, complets et actifs.

## REUSE
- OTPCode (handy/models.py:995-1017) et OTPCode.issue() : à étendre par migration (phone ou canal cible, code_hash, attempts, purpose reset/phone_change, consumed_at, ip) plutôt que de créer un nouveau modèle.
- Point d'entrée SMS handy/tasks.py:_send_sms/_resolve_msisdn (l.14-36) : y brancher un adaptateur fournisseur (Orange SMS CI ou Twilio, identifiants déjà présents dans le .env local) et l'appeler via une tâche Celery @shared_task (Celery 5.5.3 déjà configuré, CELERY_BROKER_URL=redis).
- rest_framework_simplejwt 5.5.1 avec token_blacklist installé, ROTATE_REFRESH_TOKENS et BLACKLIST_AFTER_ROTATION actifs ; option CHECK_REVOKE_TOKEN / REVOKE_TOKEN_CLAIM='hash_password' disponible pour révoquer les jetons après un changement de mot de passe.
- Routes existantes à conserver comme contrat : /handy/auth/login/ (EmailOrUsernameTokenObtainPairView, views.py:299), /auth/refresh/ (TokenRefreshView), /auth/logout/ (TokenBlacklistView), /auth/otp/request/ et /auth/otp/verify/, /users/me/ et /users/ (urls.py:41-49, router users).
- EmailOrUsernameTokenObtainPairSerializer (serializers.py:177-208) comme base du login par téléphone (ajouter la résolution identifiant -> username avant super().validate).
- ScopedRateThrottle et throttle_scope déjà actifs (scope 'login' à 10/min, base.py:205-215) : ajouter des scopes otp_request, otp_verify, signup et password_reset.
- django-axes 8.0.0 (AxesStandaloneBackend en tête d'AUTHENTICATION_BACKENDS) : le reconfigurer (AXES_LOCKOUT_PARAMETERS=[['username','ip_address']], AXES_USERNAME_CALLABLE pour normaliser le téléphone, AXES_CLIENT_IP_CALLABLE ou ipware avec nombre de proxys) plutôt que de le remplacer.
- AUTH_PASSWORD_VALIDATORS déjà configurés (base.py:240-253) : il suffit d'appeler django.contrib.auth.password_validation.validate_password.
- django-phonenumber-field 8.1.0 déjà épinglé (requirements.txt:53) : ajouter phonenumbers ou phonenumberslite pour parser et normaliser en E.164 (+225 et international).
- Paquet redis 6.2.0 installé : CACHES avec django.core.cache.backends.redis.RedisCache (natif Django 4.2) pour les throttles et cooldowns partagés.
- UserViewSet (views.py:303-348) : get_queryset owner-scoped (anti-IDOR) et action me à étendre en GET/PATCH ; à garder pour /users/{id}/, utilisé par le PATCH Flutter.
- OwnerScopedQuerysetMixin et IsOwnerOrAdmin (views.py:64-111) pour cloisonner la candidature et les documents KYC.
- Stockage KYC privé déjà en place : KycPrivateStorage, PrivateKycS3Storage et PrivateKycFileSystemStorage (handy/storage.py), private_kyc_upload_path opaque (models.py:199-207), action download en streaming protégé avec Cache-Control no-store (views.py:947-972), validation de type et de taille (HandymanDocumentSerializer.validate_file, KYC_MAX_UPLOAD_BYTES, KYC_ALLOWED_CONTENT_TYPES).
- HandymanDocument.approve/reject (models.py:236-250, avec reviewed_by, reviewed_at, rejection_reason) et HandymanProfile.has_required_kyc() / REQUIRED_KYC_DOCS comme base de la machine d'états KYC ; garder HandymanProfile.is_approved comme drapeau dénormalisé, utilisé par featured, matching, public_stats, quality_score, presence et de nombreux tests.
- Serializers publics sans données sensibles : public_display_name, PublicArtisanMiniSerializer/PublicArtisanSerializer, PublicReviewSerializer (serializers.py:51-134) ; HandymanProfileViewSet.featured filtre déjà sur is_approved et user__is_active (views.py:423-424).
- Signaux create_handyman_profile et create_company_profile (handy/signal.py:11-24) à conserver pour la compatibilité (fixtures de tests, B2B entreprise).
- Apps simple_history et actstream installées mais inutilisées : HistoricalRecords peut servir de piste d'audit KYC sans nouvelle dépendance.
- Django admin CustomUserAdmin et HandymanProfileAdmin (handy/admin.py) comme socle du back-office KYC, avec Groups et Permissions Django pour le RBAC (aujourd'hui seul is_staff est utilisé).
- drf-spectacular (extend_schema) déjà utilisé pour documenter les contrats communs à React et Flutter.
