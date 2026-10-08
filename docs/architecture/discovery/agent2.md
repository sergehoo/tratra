# agent2

## FINDINGS
## Carte du frontend React (frontend/src) : auth, rôles, parcours

**Fichiers en cours de modification par d'autres agents (état lu à 13:57 GMT) :**
- `src/lib/auth.tsx` et `src/components/RoleGuard.tsx` ont changé à 13:57 (diff non commité, décrit plus bas).
- `src/app/search/` (`page.tsx`, `SearchClient.tsx`) a été créé à 13:56.
- `components/landing|site|search/*` modifiés entre 13:50 et 13:53.
- `src/app/login/page.tsx`, `src/app/register/page.tsx` et `src/app/page.tsx` (ancienne landing) sont encore identiques à HEAD. Le commentaire de `LandingData.tsx:17` indique que `app/page.tsx` va devenir un Server Component.
- `links.ts`, `public.ts`, `format.ts`, `trades.ts` et `usePublic.ts` ne sont pas suivis par git (nouveaux).

---
### 1. Socle auth et jetons : `src/lib/api.ts` (inchangé depuis le 4 octobre)

**Clés de stockage**
- `ACCESS="tratra_access"`, `REFRESH="tratra_refresh"` (l.4-5).
- `SESSION_EXPIRED_EVENT="tratra:session-expired"` (l.6).
- Stockage dans **sessionStorage**, donc un onglet par session : un nouvel onglet arrive déconnecté. `localStorage` n'est qu'un ancien emplacement :
  - `storage()` l.13-20 ;
  - `tokens.set` l.58-71 purge les anciennes copies ;
  - `tokens.migrateLegacy()` l.83-97 déplace une session créée par une ancienne version.

**Garde d'origine** : `apiUrl()` (l.30-42) refuse une URL absolue d'une autre origine que `API_BASE` (`throw "URL API non approuvée"`) et gère les chemins `/handy/...`.

**`expireSession()`** (l.44-49) : `tokens.clear()` puis émet `SESSION_EXPIRED_EVENT`.

**`refreshAccess()`** (l.110-150)
- Un seul refresh à la fois (`refreshInFlight`).
- `POST /auth/refresh/ {refresh}` avec `credentials:"omit"`.
- Réponse 4xx : session expirée. Erreur 5xx ou réseau : on garde la session.
- Stocke `data.access` et, si présent, `data.refresh` (rotation).

**Fonctions de requête**
- `apiFetch` (l.153-177) : ajoute le Bearer, sur 401 rafraîchit et rejoue une fois. Force `Content-Type: application/json` dès qu'il y a un body (l.160-162), donc un FormData ne doit pas passer par lui.
- `apiJson`, `get`, `post`, `patch`, `del` : l.189-204.
- `privateFileUrl(path)` (l.211-218) : blob avec authentification.
- `upload()` (l.221-248) : **POST multipart uniquement** (méthode codée en dur l.226 et 237), avec refresh sur 401.

**Contrat auth avec l'API**
- `login(username, password)` (l.251-258) : `POST /auth/login/ {username,password}`, puis `tokens.set`, puis renvoie `data.user ?? me()`.
- `me()` (l.260) : `GET /users/me/`.
- `register(payload)` (l.262-273) : payload `{username, email, password, user_type, first_name?, last_name?, phone?}`, puis `POST /users/`, puis `login(username, password)`.
- `logout()` (l.275-283) : `POST /auth/logout/ {refresh}` (blacklist), puis `tokens.clear()`.
- `apiErrorMessage(err, fallback)` (l.295-304) : concatène les messages DRF ; un TypeError donne le message réseau.
- `credentials:"omit"` partout (l.128, 170, 230, 240) : aucun cookie possible aujourd'hui.

**Ce que fait le backend** (lu en lecture, fichiers en cours de modification)
- La réponse de login, `serializers.py:196-207`, contient `user_type` mais pas `is_verified` ni `phone`. Elle lit `phone_number` et `profile_image`, des attributs absents du modèle, donc `None`.
  - Conséquence : juste après login, `user.is_verified` et `user.phone` sont indéfinis. Au rechargement, `/users/me/` (`UserSerializer` l.145-149) les fournit. La forme de `User` n'est donc pas cohérente.
- `/users/me/` n'expose ni `is_staff` ni `is_superuser`.
- JWT (`tratra/settings/base.py:231-234`) : access 30 min, refresh 7 jours, `ROTATE_REFRESH_TOKENS` et `BLACKLIST_AFTER_ROTATION`.
- Limite de débit `login` à 10/min (l.213), plus django-axes (l.101, 150, 180).
- `/auth/otp/request/` et `/auth/otp/verify/` (`views.py:1083-1111`) :
  - exigent une session (`IsAuthenticated`) ;
  - `purpose="signup"` ;
  - renvoient le code si DEBUG ;
  - passent `user.is_verified=True`.
  - **Le front ne les appelle nulle part.**

### 2. `src/lib/auth.tsx`, contexte `AuthProvider`/`useAuth`

**HEAD**
- `restoreSession` (l.31-43) : `migrateLegacy` puis `me()` si un jeton existe.
- `handleSessionExpired` (l.25-29) : `router.replace("/login")` **sur n'importe quelle page**, y compris publique. Un visiteur avec des jetons périmés sur `/` ou `/search` est renvoyé vers `/login`.
- `login` et `register` (l.53-65) : `router.push(HOME_BY_ROLE[me.user_type] ?? "/client")`.
- `logout` (l.67-71) : `push("/login")`.

**Working tree (autre agent)**
- `handleSessionExpired` ne redirige que si `isProtectedPath(pathname)`, vers `loginHref(pathname+search)`.
- `login(u, p, next?)` et `register(payload, next?)` font `router.push(safeNext(next, me.user_type))`.

### 3. Rôles : tous les usages de `user_type` / `HOME_BY_ROLE` / `UserType` / `RoleGuard`

**Définitions**
- `types.ts:1` : `UserType = "client"|"employeur"|"handyman"|"entreprise"|"admin"`.
- `types.ts:3-12` : `User {id, username, email, first_name?, last_name?, user_type, phone?, is_verified?}`.
- `config.ts:34-40` : `HOME_BY_ROLE` vaut `client→/client`, `employeur→/client`, `handyman→/worker`, `entreprise→/company`, `admin→/admin`.

**`RoleGuard.tsx`**
- HEAD l.9-26 : pas d'utilisateur, alors `/login` ; rôle absent de `roles`, alors `HOME_BY_ROLE[user_type] ?? "/login"`. Affiche « Chargement… » tant que ce n'est pas autorisé.
- Working tree : ref `hadUser` (pas de redirection après une déconnexion) et `router.replace(loginHref(pathname+search))`.

**Gardes par espace**
- `worker/layout.tsx:7` : `roles={["handyman"]}`.
- `client/layout.tsx:7` : `roles={["client","employeur","entreprise"]}`.
- `company/layout.tsx:7` : `roles={["entreprise"]}` ; sa nav pointe aussi vers `/client/services` (l.13).
- `admin/layout.tsx:7` : `roles={["admin"]}`.

**`links.ts` (nouveau, miroir des gardes)**
- `AREA_ROLES` l.5-10 (même table que ci-dessus).
- `PROTECTED_PREFIXES` l.12, `isProtectedPath` l.18.
- `isSafeInternalPath` l.26-31 : anti open-redirect.
- `homeFor` l.33.
- `safeNext(next, role)` l.41-46 : refuse `/login` et `/register*`, ainsi qu'une zone non autorisée pour le rôle, et renvoie alors vers l'accueil du rôle.
- `loginHref(next)` l.48.
- `SignupType = "client"|"handyman"|"entreprise"` l.52 ; `registerHref(type, next)` l.54-60 (`?type=`).
- `spaceHref(user)` l.62.
- `bookingHref(serviceId, user)` l.72-76 : visiteur → `loginHref('/client/services/ID')` ; client, employeur ou entreprise → fiche ; **handyman ou admin → null (pas de CTA)**.

**Ce que ces rôles conditionnent ailleurs**
- `DashboardShell.tsx:63-64` affiche le badge `{user?.user_type}`.
- `app/page.tsx:23` (ancienne landing) : `HOME_BY_ROLE[user.user_type]` pour « Mon espace ». Liens `/register` aux l.45, 67-68 (« Trouver un artisan » et « Devenir artisan » vont tous deux vers `/register`), 93 et 161.
- `SiteHeader.tsx` :
  - `spaceHref(user)` l.54 ;
  - utilisateur connecté : seulement « Mon espace » (l.174-181) ;
  - visiteur : « Connexion » et « Devenir artisan » via `registerHref("handyman")` (l.192, l.282).
- `SiteFooter.tsx:27-28` : `registerHref("handyman")` et `registerHref("entreprise")`.
- `ServiceCard.tsx:17-18` : `bookingHref` ; repli l.97-99 « Réservation ouverte aux comptes client et entreprise. »
- `search/SearchClient.tsx:247` (en cours) : `registerHref("handyman")`.

**Logique de redirection après login (HEAD)**
- Login ou inscription → `HOME_BY_ROLE[user_type] ?? "/client"`.
- Garde refusée → home du rôle.
- `user_type` null (le champ est nullable, `models.py:34`) : `/client`, puis RoleGuard refuse, puis `/login` alors que l'utilisateur est connecté (boucle visible).
- Le `?next=` produit par `bookingHref`/`loginHref` **n'est pas lu par la page login à HEAD**.

### 4. Pages : endpoints appelés et champs lus

**`login/page.tsx` (HEAD)**
- Un champ « Email ou nom d'utilisateur » (l.37-38), puis `login(username, password)` (l.19).
- `catch` générique « Identifiants invalides. » (l.20-21) : masque le 429 de la limite de débit, le verrou axes et l'erreur réseau.
- Pas de `next`, pas de « mot de passe oublié ». Lien vers `/register` (l.45).

**`register/page.tsx` (HEAD)**
- `ROLES` l.8-12 (client, handyman, entreprise) dans un `<select>` l.46-49.
- État l.16 : `{username, email, password, user_type:"client", first_name, last_name, phone}`, puis `register(f)` (l.27).
- Erreurs DRF via `Object.values(data).flat().join` (l.29-30).
- Pas de confirmation du mot de passe, pas d'étape OTP. `?type=` et `?next=` ignorés.

**`worker/page.tsx`**
- `GET /bookings/` (l.17), **sans filtre**. Lit `service_detail.title`, `client_detail.first_name|username`, `city`, `status`.
- `GET /payouts/available/` (l.18) : lit `available`.
- `POST /handymen/presence/ {online}` (l.25). L'état initial `online=null` ne lit jamais l'état réel du profil. Message d'erreur « profil non vérifié ? ».

**`worker/missions/[id]/page.tsx`**
- `GET /bookings/{id}/` (l.26).
- `POST /bookings/{id}/transition/ {status}` (l.34), carte `NEXT` l.9-16 (pending→confirmed|cancelled, confirmed→in_progress, in_progress→completed).

**`worker/kyc/page.tsx`**
- `GET /handyman-docs/` (l.26).
- `upload("/handyman-docs/", FormData{document_type, file})` (l.37-40).
- `DOC_TYPES` l.7-13 : `id_card`, `license`, `casier`, `insurance`, `certification`.
- Lit `document_type` et `status` (pending/approved/rejected).
- **Manque** : `rejection_reason`, recto/verso, selfie, consentement, resoumission.
- Erreur « profil artisan requis » (l.44). Le backend renvoie 403 sans `HandymanProfile` (`views.py:935-940`).

**`admin/page.tsx`**
- Comptages via `?page_size=1` sur `/bookings/`, `/services/`, `/handymen/`, `/disputes/` (l.22), lit `count`.

**`admin/kyc/page.tsx`**
- `GET /handyman-docs/` (l.18) : **1re page seulement** (taille 20, `views.py:179`), sans filtre de statut.
- `POST /handyman-docs/{id}/review/ {action:"approve"|"reject", reason}` (l.29) ; motif via `window.prompt` (l.28).
- `viewDocument` (l.38-57) : `privateFileUrl(download_url)`, puis blob ouvert dans un onglet, puis `revokeObjectURL` après 60 s.
- Lit `handyman_detail.user_detail.first_name|username`, `document_type`, `status`, `download_url`.
- `download_url` est absolu (`reverse(request=...)`, `serializers.py:586-588`), donc soumis à la garde d'origine de `apiUrl`.
- Approuver un document n'approuve **pas** le profil :
  - `HandymanDocument.approve` (`models.py:236-242`) ne met à jour que le document ;
  - `is_approved` n'est modifié que par l'action Django admin `approve_profiles` (`admin.py:158-161`, `queryset.update(is_approved=True)`), sans vérifier `has_required_kyc` (`models.py:165-171`).

**`admin/disputes/page.tsx`**
- `GET /disputes/` (l.14).
- `POST /disputes/{id}/resolve/ {action: refund_client|release_artisan|reject, resolution:""}` (l.24).
- Lit `id`, `booking`, `status`, `reason`.

**`client/page.tsx`** : `GET /bookings/` (l.21), sans filtre. Lit `service_detail.title`, `city`, `booking_date`, `status`.

**`client/services/page.tsx`** : `GET /services/?search=` (l.16), authentifié via `get`. Lit `category_detail.name`, `title`, `description`, `price`, `handyman_detail.first_name|username`.

**`client/services/[id]/page.tsx`**
- `GET /services/{id}/` (l.44).
- `POST /bookings/` (l.107-118) avec `{service, handyman: svc.handyman ?? handyman_detail.id, booking_date ISO, address, city, postal_code||"00000", description, type:"scheduled", minutes:60, category_id}`.
- `POST /payments/initiate/ {booking_id, method, minutes, category_id}` (l.60-65).
- Lit `payment_id`, `redirect_url` (contrôle https l.71-78), `instructions`.

**`client/bookings/[id]/page.tsx`**
- `GET /bookings/{id}/` (l.16).
- `transition {status:"cancelled"}` (l.23).
- `GET /bookings/{id}/replacements/` (l.31).
- `POST accept-replacement {suggestion_id}` (l.38).

**`company/page.tsx`**
- `GET /companies/me/` et `GET /subscriptions/current/` (l.33-34).
- `POST /companies/me/` (l.41), sans try/catch.
- Lit `company_name`, `registration_number`, `industry`, `city`, `contact_person`, `phone`, `website`, `verified`, `plan_detail`, `status`, `current_period_end`.

**`company/plans/page.tsx`** : `GET /subscription-plans/?audience=business` (l.15), `POST /subscriptions/ {plan}` (l.24).

**Catalogue public (en cours, autre agent)**
- `SearchClient.tsx:101-127` interroge `/services/?is_active=true&search&categories&commune&online&verified&...` ou `/services/nearby/`, via `publicGet` (sans Bearer).
- La liste publique inclut les services d'artisans **non approuvés**, sauf si `verified=1` (`views.py:~733-738`).

### 5. Briques UI et helpers réutilisables

**Composants**
- `components/ui.tsx` : `Button` (primary, ghost, accent), `Input`, `Card`, `Stat`, `Badge` (primary, accent, gray).
- `DashboardShell.tsx` : sidebar `nav` statique par layout, logout. Pas de nav mobile, pas de bascule client/handyman.
- `market/primitives.tsx` :
  - `VerifiedBadge` (doc : « uniquement si le profil a passé le KYC ») ;
  - `Avatar` (photo ou initiales) ;
  - `RatingStars`, `StarRow`, `OnlineDot`, `EmptyState`.
- `market/ServiceCard.tsx` : `serviceImage()` et CTA de réservation.
- `market/ArtisanCard.tsx` : badge si `artisan.is_verified`, lien `/search?handyman=user_id`.
- `market/Skeletons.tsx`, `landing/kit.tsx` (`CONTAINER`, `SECTION_Y`, variantes de boutons), `landing/Reveal.tsx`, `Providers.tsx` (`LazyMotion` + `AuthProvider`).

**Helpers (`lib/`)**
- `public.ts` : `publicGet` (sans Authorization, ISR côté serveur, timeout), `resultsOf`, `qs`.
- `usePublic.ts` : `usePublicData`.
- `format.ts` : `formatFCFA`, `priceLabel`, `formatRating`, `formatDuration`, `formatDistance`.
- `trades.ts` : `TRADE_FAMILIES` (slugs réels), `resolveTrades`, `iconForCategory`.
- `types.ts` : `Category` (`services_count`), `PublicArtisanMini` / `PublicArtisan`, `Service.artisan`, `HandymanDocument` (`status` pending|approved|rejected, l.130-138), `Booking`, `Dispute`, `SubscriptionPlan`.
- `config.ts` : `API_BASE`, `PAYMENT_METHODS`.

**PWA et SEO**
- `public/sw.js:30` : `NEVER_CACHE = ["/handy","/api","/client","/worker","/company","/admin","/login","/register"]`.
- `robots.ts:15` : disallow `/client`, `/worker`, `/company`, `/admin`, `/offline`.
- `sitemap.ts:23-24` : inclut `/register` et `/login`.

**Tests et build** : `package.json` n'a que `typecheck`, `build`, `lint` et `verify` (`typecheck && build`). **Aucun runner de test front** (ni jest, ni vitest, ni playwright, aucun `*.test.*`).

### 6. Ce qui casse si on supprime le choix de rôle et qu'un compte peut être client et handyman

1. **Gardes basées sur `user_type`** (4 layouts plus `AREA_ROLES`) : un client devenu handyman ne peut pas ouvrir `/worker` ; un compte passé à `user_type=handyman` ne peut plus ouvrir `/client` ni réserver. Il faut des gardes par capacité, dérivées de `/users/me/` : session, téléphone vérifié, profil handyman (statut KYC), staff, entreprise.
2. **`HOME_BY_ROLE`, `homeFor`, `safeNext`, `spaceHref`** supposent une seule home par rôle. Il faut une home unique (client ou compte) et un sélecteur « Espace Handyman » dans `DashboardShell`. Le badge `user_type` (l.64) doit disparaître.
3. **`bookingHref`** (`links.ts:72-76`) et le texte de `ServiceCard.tsx:97-99` interdisent la réservation au handyman. Nouvelle règle : tout compte vérifié par OTP ; un compte non vérifié est envoyé vers l'OTP.
4. **Inscription** : `register/page.tsx` (`ROLES` et `user_type` dans le payload, `api.ts:266`) et `SignupType`/`registerHref(type)` (Header l.192/282, Footer l.27-28, SearchClient l.247) doivent devenir « Proposer un service ». Ce CTA mène à une page publique de candidature ; la connexion ou l'inscription n'intervient qu'à la soumission, via `loginHref(next)`. `safeNext` refuse aujourd'hui `next=/register*`, à revoir pour une reprise de parcours.
5. **SiteHeader** n'affiche aucun CTA « Proposer un service » à un utilisateur connecté (seulement « Mon espace »).
6. **`GET /bookings/` non filtré** côté client (`client/page.tsx:21`) et worker (`worker/page.tsx:17`) : le backend renvoie client OU handyman (`views.py:585`), donc les listes se mélangent pour un double rôle. `filterset_fields` contient déjà `client` et `handyman` (l.588) : utiliser `?client=<me.id>` et `?handyman=<me.id>`.
   - `transition_to` (`models.py:535+`) ne contrôle pas le rôle de l'acteur.
   - Aucune garde contre la réservation de son propre service (`BookingCreateSerializer`, `serializers.py:348-360`).
7. **Création du profil handyman** : seul le signal à la création du User, si `user_type=='handyman'` (`signal.py:11-15`), crée un `HandymanProfile` ; même mécanisme pour `CompanyProfile` (l.18-24). Sans choix de rôle, aucun profil n'est créé, donc l'upload KYC renvoie 403 et la présence 404 (`views.py:373-376`). Il faut un endpoint de candidature qui crée le profil.
8. **KYC worker et admin** : types de documents et statuts incompatibles avec la cible (DRAFT, PENDING, REVIEW, APPROVED, REJECTED, SUSPENDED ; CNI recto/verso ; selfie et liveness ; consentement).
   - La revue se fait document par document, pas sur une décision de profil.
   - Pas d'historique, pas de pagination, motif saisi via `prompt`.
   - Le type `HandymanDocument` est à refaire.
9. **Admin React** : accès par `user_type==="admin"`, alors que l'API exige `IsAdminUser` (is_staff), que `/users/me/` n'expose pas. Sur la base dev, 0 utilisateur `user_type=admin` et 2 staff : `/admin` est inaccessible en React.
10. **Entreprise** : `company/layout` garde par `user_type entreprise`. À convertir en capacité (existence d'un `CompanyProfile`) si le compte devient unique.
11. **Login** : passer au téléphone (+225 et international, normalisation E.164) avec message générique anti-énumération, mais distinguer le 429 et le verrou ; ajouter « mot de passe oublié » (OTP) ; garder `next`.
12. **Collision de nom `is_verified`** :
    - `User.is_verified` (`types.ts:11`, flag OTP, `views.py:1109`) est aussi exposé publiquement par `PublicUserMiniSerializer` (`serializers.py:77`) dans `handyman_detail` ;
    - `PublicArtisanMini.is_verified` (`types.ts:36`) correspond à `source="is_approved"` (`serializers.py:84`).
    - Risque d'afficher « Identité vérifiée » à partir du flag OTP. Renommer, par exemple `phone_verified` et `identity_verified`.
13. **Upload de photo de profil** : `upload()` ne fait que du POST ; un PATCH multipart demande un paramètre `method`. Ne pas passer de FormData à `apiFetch`.
14. **CSP et Permissions-Policy** (`next.config.mjs`) :
    - `camera=()` (l.54) bloque le selfie et la liveness web ;
    - `connect-src` (l.34), `script-src` (l.30) et l'absence de `frame-src` (`default-src 'self'`) bloquent un SDK ou un iframe de prestataire KYC.
15. **Nouvelles routes privées** (compte, OTP, mot de passe oublié, candidature privée) : à ajouter à `sw.js` `NEVER_CACHE` et à `robots` disallow.
16. **`UserMiniSerializer`** (`serializers.py:28-31`) n'a pas de `username`, donc les replis `.username` du front valent toujours `undefined`.

## DATA
Base dev : postgis, base "tratra". Requêtes en lecture seule.

**Utilisateurs (2 au total)**
- Par `user_type` : 1 employeur et 1 handyman. Aucun `client`, `entreprise` ni `admin` ; aucun `user_type` null.
- Les deux sont staff (`is_staff=True`). Le superuser est de type employeur. Le handyman (id 8) est staff aussi.
- Conséquence : aucun compte ne passe `RoleGuard roles=["admin"]`, donc `/admin` est inaccessible dans le front React en dev.
- Les deux ont `is_verified=True` (flag OTP).

**Téléphones**
- 1 téléphone renseigné, 1 null ou vide.
- Le téléphone renseigné est au format local à 10 chiffres : pas de "+", pas de préfixe 225, uniquement des chiffres. Ce n'est pas du E.164, alors que `phone` est `unique` (`models.py:37`).

**Profils et KYC**
- `HandymanProfile` : 1 (user 8), `is_approved=False`, `online=False`.
- `HandymanDocument` : 0.
- `CompanyProfile` : 0.

**Activité**
- 1 réservation (booking), 2 services, 55 catégories.

**Pagination et JWT**
- Pagination DRF par défaut : 20 par page, `page_size` max 100 (`views.py:178-181`).
- JWT : access 30 min, refresh 7 jours, rotation et blacklist activées. Limite login : 10/min, plus django-axes (blocage par IP).

## RISKS
- Travail en parallèle : auth.tsx et RoleGuard.tsx ont été modifiés par un autre agent à 13:57 (redirection vers `/login` limitée aux pages protégées, `next` via `safeNext`/`loginHref`) ; `src/app/search/*` a été créé à 13:56 ; `links.ts` n'est pas suivi par git. Une refonte des gardes doit partir de ce working tree, pas de HEAD, sinon on écrase ces correctifs.
- Les gardes front reposent sur `user_type` (4 layouts, `AREA_ROLES` dans `links.ts`, `HOME_BY_ROLE`, `bookingHref`). Si `user_type` est supprimé ou figé sans les migrer vers des capacités, le compte handyman perd l'accès à `/client` et à la réservation, et un client converti en handyman n'accède pas à `/worker`.
- Admin : le front contrôle `user_type==='admin'`, l'API contrôle `is_staff` (`IsAdminUser`), et `/users/me/` n'expose pas `is_staff`. En dev, aucun compte n'est `admin`. Le RBAC du dashboard KYC doit s'appuyer sur un champ exposé par `/me` (`is_staff`, groupes ou permissions) et être revérifié côté serveur.
- Faux KYC validé possible côté backend : `HandymanProfileSerializer` (`serializers.py:223-235`) n'a pas de `read_only_fields`, donc `is_approved` et `user` sont modifiables. Le propriétaire peut faire `PATCH /handymen/{id}/ {is_approved:true}` (`IsOwnerOrAdmin`). De plus, `GET /handymen/` n'est pas cloisonné (aucun `get_queryset`, lecture permise à tout utilisateur connecté) et renvoie `cni_number`/`license_number` de tous les artisans. À corriger avant de publier automatiquement les profils APPROVED.
- L'approbation est incohérente : la revue React approuve un document (`HandymanDocument.approve`) sans toucher à `HandymanProfile.is_approved`. Seule l'action Django admin `approve_profiles` le fait, via `queryset.update`, sans vérifier `has_required_kyc`. Le badge public `artisan.is_verified` (= `is_approved`) peut donc diverger de l'état KYC réel.
- Confusion de badge : `User.is_verified` (OTP téléphone) est exposé publiquement dans `handyman_detail` (`PublicUserMiniSerializer`), alors que `PublicArtisanMini.is_verified` veut dire KYC approuvé. Si un composant utilise `handyman_detail.is_verified`, il affichera « vérifié » pour un simple OTP. Nommer distinctement `phone_verified` et `identity_verified`.
- Listes mélangées pour un compte double rôle : `/client` et `/worker` appellent `GET /bookings/` sans filtre, alors que le backend renvoie client OU handyman. Il faut filtrer par `client` ou `handyman`. Le backend n'empêche ni de réserver son propre service ni de déclencher une transition réservée à l'autre partie (`transition_to` sans contrôle d'acteur).
- Création du `HandymanProfile` : seul le signal post_save sur `user_type=='handyman'` la déclenche. Sans choix de rôle, aucun profil n'est créé, d'où un 403 à l'upload KYC et un 404 sur la présence. Il faut un endpoint de candidature idempotent, et reprendre les profils existants sans doublon (`OneToOne`).
- Migration des téléphones : le format stocké est local à 10 chiffres (dev), pas E.164, avec une contrainte unique. Une normalisation +225 peut créer des doublons ou casser le login si elle n'est pas faite en migration de données avec détection des collisions. L'email devient facultatif mais est `unique` et non nullable (`models.py:25`) : il faut une migration `null=True` sinon plusieurs chaînes vides entrent en collision.
- Contrat login incohérent : le bloc `user` de `/auth/login/` n'a ni `is_verified` ni `phone` (attributs `phone_number`/`profile_image` inexistants), alors que `api.login` renvoie `data.user`. Un contrôle « téléphone vérifié » juste après le login lira `undefined`. Aligner sur le `UserSerializer` de `/me` ou toujours rappeler `me()`.
- Anti-bruteforce et UX : la page login affiche « Identifiants invalides. » pour toute erreur, y compris le 429 (limite de débit) et le verrou django-axes. Il faut un message générique (anti-énumération) mais distinct pour « trop de tentatives » ou erreur réseau. Les endpoints OTP actuels exigent une session : la récupération par OTP demande de nouveaux endpoints anonymes, limités en débit.
- Si le refresh passe en cookie HttpOnly, `api.ts` utilise `credentials:'omit'` partout et sessionStorage. Il faudra `credentials:'include'`, du CSRF, CORS avec credentials et retirer le refresh du stockage JS. La session par onglet (sessionStorage) déconnecte déjà à chaque nouvel onglet, ce qui gêne un parcours OTP par lien.
- Liveness et selfie web : `Permissions-Policy camera=()` (`next.config.mjs:54`) bloque la caméra. La CSP (`connect-src` limité à l'API, `script-src 'self'`, pas de `frame-src`) bloque le SDK ou l'iframe d'un prestataire KYC. Il faut l'ouvrir pour l'origine exacte du prestataire seulement.
- Exposition des documents : `download_url` est une URL absolue de l'API, ouverte via `privateFileUrl` (blob authentifié). Il ne faut jamais renvoyer d'URL de stockage ni de document d'identité dans les payloads publics (`/services`, `/handymen/featured`, `/search`). Derrière un proxy, une origine différente entre `reverse(request)` et `API_BASE` fait échouer la garde de `apiUrl`.
- Pas de runner de test front : seuls typecheck et build existent (`npm run verify`). Les « tests ciblés » des parcours React demandent d'ajouter un outil (vitest ou playwright) ou de s'en tenir aux tests API Django et au build.
- Le catalogue public inclut actuellement les services d'artisans non approuvés (le filtre `verified=1` est optionnel). Pour l'exigence 7, il faut filtrer par défaut côté backend (`is_approved`, actif, complet), sans casser les réservations existantes liées à ces services.
- Routes privées à ajouter (compte, OTP, mot de passe oublié, candidature) : `sw.js` `NEVER_CACHE` et `robots` disallow, sinon une page de compte risque d'être mise en cache ou indexée. `sitemap.ts` référence déjà `/register` et `/login`.

## REUSE
- src/lib/api.ts : `tokens` (sessionStorage et `migrateLegacy`), `refreshAccess` (un seul refresh à la fois, 4xx vs réseau), `apiFetch`/`apiJson`/`get`/`post`/`patch`/`del`, `ApiError`, `apiErrorMessage`, garde d'origine `apiUrl`, `privateFileUrl` (preuves KYC en blob authentifié), `upload` (multipart, à étendre avec un paramètre `method` pour PATCH).
- src/lib/auth.tsx (version working tree) : `AuthProvider`/`useAuth`, `restoreSession`, `SESSION_EXPIRED_EVENT` limité aux pages protégées, `login`/`register` avec `next`. Remplacer seulement `register(payload)` et le calcul de la home.
- src/lib/links.ts : `isSafeInternalPath`, `safeNext`, `loginHref` (anti open-redirect et retour après connexion), `isProtectedPath`. Transformer `AREA_ROLES` en contrôles de capacité et faire de `registerHref(type)` un lien « Proposer un service ».
- src/components/RoleGuard.tsx (version working tree) : squelette réutilisable (ref `hadUser`, `loginHref` avec retour). Remplacer `roles: UserType[]` par un prédicat de capacité (session, téléphone vérifié, profil handyman, staff, entreprise).
- src/components/DashboardShell.tsx : shell des espaces. Ajouter une bascule Client/Handyman et retirer le badge `user_type`.
- src/components/ui.tsx : `Button`, `Input`, `Card`, `Stat`, `Badge`, pour les formulaires OTP, profil, candidature et l'admin KYC.
- src/components/market/primitives.tsx : `VerifiedBadge` (à brancher uniquement sur `identity_verified` = APPROVED), `Avatar` (photo de profil), `EmptyState`, `RatingStars`, `OnlineDot`. Aussi `ServiceCard` et `ArtisanCard` (adapter `bookingHref`).
- src/lib/public.ts (`publicGet`, `resultsOf`, `qs`) et src/lib/usePublic.ts (`usePublicData`) : pages publiques, dont « Proposer un service » avant authentification.
- src/lib/trades.ts (`TRADE_FAMILIES`, `resolveTrades`, `iconForCategory`) et `GET /categories/?page_size=100` : sélection des métiers et spécialités du formulaire Handyman. src/lib/format.ts (`formatFCFA`) pour les tarifs.
- src/app/admin/kyc/page.tsx : modèle `viewDocument` (`privateFileUrl` puis `revokeObjectURL`) pour consulter les preuves dans le futur dashboard KYC.
- src/app/client/services/[id]/page.tsx et src/app/client/bookings/[id]/page.tsx : parcours de réservation et de paiement à conserver tels quels (seule la garde change).
- Endpoints backend existants à réutiliser : `/auth/refresh/` et `/auth/logout/` (SimpleJWT avec rotation et blacklist), `/users/me/`, `/auth/otp/request|verify/` (logique `OTPCode.issue`/`is_valid` et `_send_sms`), `/handyman-docs/` et `download`, `/handymen/presence/`, `/bookings/?client=&handyman=` (`filterset_fields` existants), `/companies/me/`.
- Infra front : `public/sw.js` `NEVER_CACHE`, `robots.ts` disallow, Permissions-Policy et CSP de next.config.mjs (à étendre pour la caméra et le prestataire KYC), `tailwind.config.ts` (tokens `primary`, `primaryDark`, `accent`, `night`, `ink`, `ash`) et `landing/kit.tsx` (variantes de boutons, `CONTAINER`).
