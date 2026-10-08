# agent0

## FINDINGS
## 0. Contexte / fichiers en cours de modification
- Fichiers backend **modifiés et non commités** (Lot 1 « public », mtime 8 oct. 13:45–13:50) : `handy/api/views.py` (+438/-56), `handy/api/serializers.py` (+128), `handy/api/urls.py` (+`public/stats/`), nouveau `handy/test_lot1_public.py`. Ils ajoutent `/handymen/featured/`, `/reviews/public/`, `/public/stats/`, les filtres et tris publics des services, ainsi que `PublicUserMiniSerializer`/`PublicArtisan*Serializer`. Les numéros de ligne ci-dessous correspondent à l'état actuel du working tree.
- Non modifiés : `handy/models.py` (4 oct.), `handy/admin.py`, `handy/signal.py`, `handy/storage.py`, `handy/services/matching.py`.
- `handy/api/permissions.py` **n'existe pas** : les permissions sont définies en tête de `handy/api/views.py`.

## 1. HandymanProfile — `handy/models.py:76-196`
- Champs : `user` O2O→User `related_name='handyman_profile'` (77), `bio` (78), `skills` M2M→ServiceCategory `related_name='handymen'` (79), `experience_years` (80), `license_number` (81), `cni_number` (82), `insurance_info` (83), `commune`/`quartier` (84-85), `hourly_rate`/`daily_rate`/`monthly_rate`/`travel_fee` (87-90, CheckConstraint >=0 l.111-116), `availability = JSONField(default=dict)` (92), **`is_approved` Bool default False, db_index (93)**, `rating` (94), `completed_jobs` (95), `quality_score` 0-100 (96), `photo` (97, doublon de `User.profile_picture`), `location` PointField 4326 (100, GistIndex), `online` (102). Index `(is_approved, rating)` (106).
- `profile_completion()` (146-158) : 8 critères (bio, skills, experience>0, license_number, cni_number, insurance_info, photo, documents.exists()).
- `REQUIRED_KYC_DOCS = {'id_card'}` (165) et `has_required_kyc()` (167-171) : renvoie vrai si un doc `id_card` a le statut `approved`. **Seuls les tests l'utilisent** (test_sprint4bis). Aucun code métier ne l'appelle et rien ne relie ce calcul à `is_approved`.
- `compute_quality_score()` (178-188) : note sur 50 + missions sur 25 + **`kyc_pts = 15 if self.is_approved`** (185) + complétude sur 10. `refresh_quality_score()` (190-193) est appelé par `Booking.transition_to` (571-573) et par le signal avis (`signal.py:40-42`), **pas** lors d'une approbation.
- Format de `availability` : aucun schéma côté API (JSON libre). Le format legacy du formulaire web (`handy/forms.py:258-270, 413-418`, formulaire mort) est `{"Lundi": ["matin","aprem","soir","nuit"]}`. Les tests utilisent `{"lundi": "8h-18h"}` (`test_lot1_public.py:61`). Les modèles structurés existent mais ne sont pas exposés : `AvailabilitySlot` (385-389 : weekday 0=lundi, start_time, end_time), `ServiceArea` (378-382 : center, radius_km, polygon), `TimeOff` (426-430). Ils sont réutilisables pour « zone » et « disponibilité ».

**Qui crée le profil ?** Uniquement le signal `handy/signal.py:11-15`, au `post_save` User si `created and instance.user_type == 'handyman'` (`get_or_create`). Il est chargé par `handy/apps.py` (`ready → import handy.signal`). Le passage ultérieur de `user_type` à `handyman` via PATCH `/users/{id}/` (autorisé par `SELF_SIGNUP_ROLES`, serializers.py:153) **ne crée pas de profil**. L'API `POST /handy/handymen/` existe aussi (ModelViewSet sans `perform_create`), et ni React ni Flutter ne l'appellent. Le signal équivalent pour les entreprises est `signal.py:18-24`.

**Qui met `is_approved=True` ?**
1. L'action admin `approve_profiles` (`admin.py:159-162`) : `queryset.update(is_approved=True)`, **sans vérifier les documents**, sans `refresh_quality_score`, sans trace.
2. Le champ `is_approved`, éditable dans le fieldset « Validation » (`admin.py:133-135`).
3. **Faille** : l'API. `HandymanProfileSerializer` (`serializers.py:211-235`) n'a **aucun `read_only_fields`**, donc `is_approved`, `rating`, `completed_jobs` et `online` sont modifiables par le propriétaire via PATCH `/handy/handymen/{id}/` (IsOwnerOrAdmin). Le champ `user = PrimaryKeyRelatedField(queryset=User.objects.all())` (213) est aussi modifiable : un POST `/handymen/` permet de créer un profil pour n'importe quel user, et un PATCH permet de réattribuer le profil.
4. `create_fake_data` (`management/commands/create_fake_data.py:247`, 80 % de profils approuvés de façon aléatoire).
- **Approuver un document ne met pas `is_approved` à jour** (aucun signal ni hook dans `HandymanDocument.approve`).

## 2. HandymanDocument — `handy/models.py:199-250`
- `private_kyc_upload_path` (199-207) génère la clé `kyc/{profile_id}/{uuid4hex}{ext}`, sans le nom d'origine.
- `DOCUMENT_TYPES` (211-218) : `id_card`, `license`, `casier`, `insurance`, `certification`, `other`. **Pas de recto/verso ni de selfie.**
- `STATUS_CHOICES` (220) : `pending`, `approved`, `rejected`. Champs : `handyman` FK→HandymanProfile `related_name='documents'` CASCADE (222), `document_type` (223), `file = FileField(upload_to=private_kyc_upload_path, storage=KycPrivateStorage())` (224), `description` (225), `status` (226, indexé), `reviewed_by` FK User SET_NULL `related_name='documents_reviewed'` (227), `reviewed_at` (229), `rejection_reason` (230), `uploaded_at` (231). Pas de `Meta.ordering` ni d'historique : `reviewed_*` est écrasé à chaque revue.
- `approve(*, by)` (236-242) et `reject(*, by, reason='')` (244-250) : `save(update_fields=...)`. Aucun contrôle de l'état courant, motif non obligatoire.
- Migrations : 0021 a ajouté status, reviewed_by, reviewed_at et rejection_reason. 0027 (`AlterField file` → `KycPrivateStorage` + `private_kyc_upload_path`) n'est **PAS appliquée sur la base dev** (`showmigrations` : `[ ] 0027_private_kyc_document_storage`).

### Stockage privé — `handy/storage.py`
- `PrivateKycS3Storage` (17-25) : `default_acl=None`, `querystring_auth=True`, expiration 300 s, `file_overwrite=False`.
- `PrivateKycFileSystemStorage` (28-36) : `url()` **lève `NotImplementedError`**.
- `KycPrivateStorage` (39-100) : proxy `@deconstructible` vers l'alias `storages['private_kyc']`, avec repli sur `default_storage` si l'alias est absent.
- Settings `tratra/settings/base.py` : `KYC_MAX_UPLOAD_BYTES` (10 Mo), `KYC_ALLOWED_CONTENT_TYPES` (pdf, jpeg, png) et `KYC_SIGNED_URL_TTL_SECONDS` (l.293-304). STORAGES avec MinIO (306-347, bucket `KYC_STORAGE_BUCKET_NAME`). Sans MinIO (349-357) : `private_kyc` → `BASE_DIR/private_kyc`, dossier absent en dev. `prod.py:35-37` impose un bucket KYC distinct.
- Commande `handy/management/commands/migrate_kyc_documents_to_private_storage.py` : dry-run par défaut, `--apply`, `--delete-source` (exige `--apply`), `--limit`. Elle ignore les fichiers déjà sous `kyc/`, copie depuis `default_storage` vers `storages['private_kyc']`, vérifie `exists`, puis met à jour `file.name`.

### API — `HandymanDocumentViewSet` `handy/api/views.py:923-986` (route `handyman-docs`, basename `handyman-docs`)
- `OwnerScopedQuerysetMixin` avec `owner_lookups=("handyman__user",)` : non-staff = ses propres docs, staff = tout. `IsAuthenticated`, `http_method_names` get/post/delete. `authentication_classes=[JWTAuthentication, SessionAuthentication]` (933) pour le lien admin.
- `perform_create` (935-940) : exige un HandymanProfile, force `handyman=profile`, `status="pending"`.
- `perform_destroy` (942-945) : non-staff, seulement si `pending`.
- `download` (947-972) : `get_object()` scopé (404 pour un tiers), `FileResponse(as_attachment)` avec les en-têtes `Cache-Control: private, no-store, max-age=0`, `Referrer-Policy: no-referrer` et `nosniff`.
- `review` (974-986) : `permission_classes=[IsAdminUser]` (= `is_staff`), corps `{"action":"approve|reject","reason":""}`. Pas d'effet sur le profil, pas de notification, pas d'audit.
- Pas de filtre par statut : `filter_backends` n'est pas défini et `DEFAULT_FILTER_BACKENDS` est absent. `ordering=["-uploaded_at"]` est donc sans effet.
- `HandymanDocumentSerializer` (`serializers.py:547-588`) : `file` en write_only (552), `download_url` = `reverse('handyman-docs-download')` (586-588), `read_only_fields = handyman, status, reviewed_at, rejection_reason, uploaded_at` (560), `validate_file` taille + MIME + extension (562-583). `handyman_detail = HandymanProfileSerializer` (549) renvoie au propriétaire son profil complet, dont `cni_number`.

### Django admin KYC — `handy/admin.py`
- `HandymanDocumentInline` (80-94) : champs `document_type, file, preview_document, description, uploaded_at`. Le lien d'aperçu pointe vers `handyman-docs-download`.
- `HandymanDocumentAdmin` (165-190) : `list_display` sans `status`, `list_filter=('document_type','uploaded_at')` sans statut. Aucune action approve/reject. Le formulaire par défaut rend **status, reviewed_by, reviewed_at et rejection_reason éditables à la main**.
- **Bug confirmé** (test en lecture seule, sans écriture) : avec le stockage FS privé (dev, `MINIO_ENABLED=False`), `ClearableFileInput().is_initial(doc.file)` lève `NotImplementedError`. La page de modification d'un document, ou d'un profil dont l'inline contient un fichier, renvoie donc une erreur 500.
- `HandymanProfileAdmin` (97-162) : `list_filter=('is_approved','skills','experience_years')`. Seule action : `approve_profiles` (aucune suspension ni révocation).

### Clients existants (contrats)
- React : `frontend/src/app/admin/kyc/page.tsx` (GET `/handyman-docs/`, POST `/handyman-docs/{id}/review/`, téléchargement via `privateFileUrl(download_url)`), `frontend/src/app/worker/kyc/page.tsx` (upload multipart, types id_card, license, casier, insurance, certification), `frontend/src/app/worker/page.tsx:25` (presence). Type `HandymanDocument` dans `frontend/src/lib/types.ts:130`.
- Flutter : `lib/services/handyman_service.dart` (presence l.17, KYC l.82-95), `lib/core/constants.dart:37-51`, `lib/models/artisan.dart:66` (badge = `is_approved`/`is_certified`), `lib/screens/artisan_profile_screen.dart:138` (GET `/handymen/{id}/`, qui exige d'être authentifié).
- Aucun des deux clients ne crée de Service ni de HandymanProfile via l'API.

## 3. Liste exhaustive des points où `is_approved` / le KYC conditionne un comportement
| Lieu | Effet |
|---|---|
| `handy/api/views.py:382` (`presence`) | 403 si `online=true` et `not profile.is_approved` |
| `handy/services/matching.py:13` | `filter(is_approved=True, online=True, skills__id=..., location__isnull=False)`, exclut les TimeOff. **Ne filtre pas `user__is_active`** |
| `handy/api/views.py:249-250` (`apply_public_service_filters`) | `?verified=1` → `handyman__handyman_profile__is_approved=True` (**optionnel**) |
| `handy/api/views.py:252-255` | `?online=1` → online ET approved |
| `handy/api/views.py:424` (`featured`, public) | `is_approved=True, user__is_active=True` |
| `handy/api/views.py:1170` (`compute_public_stats`) | `artisans_verified` / `artisans_online` = approved + actif. En revanche **`services` compte tous les services actifs** (1174) |
| `handy/models.py:490` (`Booking.generate_replacement_suggestions`) | remplaçants `handyman__handyman_profile__is_approved=True` |
| `handy/models.py:185` | +15 pts de quality_score |
| `handy/tasks.py:43` (`send_profile_completion_reminders`) | rappels aux seuls profils approuvés, tâche non planifiée (`CELERY_BEAT_SCHEDULE = {}`, base.py:387) |
| `handy/api/serializers.py:84` | `PublicArtisanMiniSerializer.is_verified = source="is_approved"`, **seule source du badge** (embarqué dans chaque Service et dans featured) |
| `handy/admin.py:98-99,134,159-162` | affichage, filtre et action d'approbation |

**Aucun contrôle KYC dans les cas suivants** :
- `ServiceViewSet` list/retrieve (`views.py:484-509`) : les services d'artisans non approuvés **et les services inactifs** sont publics. Le test `test_lot1_public.py:343-344` l'assume (« aucun filtre is_active implicite »).
- `search_services_nearby_qs` (141-149) : filtre `is_active` seulement.
- `suggest_alternatives_qs` (152-174).
- `ServiceCategoryViewSet.services_count` (465-467).
- Slides de repli (`views.py:1385-1390`).
- `BookingCreateSerializer` (`serializers.py:322-362`) : n'importe quel `handyman`/`service`, sans vérifier que `service.handyman == handyman`, ni l'approbation, ni l'activité. Seule protection : la contrainte DB `bk_client_not_handyman`.
- `payment_initiate` (1032), `PayoutViewSet.create` (740-754), `payout_account` (1139), `TimeOffViewSet` (exige seulement un profil), `match` (pas de check `user.is_active`).

## 4. Service et permissions
- Modèle `Service` (`models.py:330-365`) : `handyman` FK→**User** (pas HandymanProfile) `related_name='services'`, `category`, `title`, `description`, `price_type` hourly/fixed/quote, `price`, `duration`, `is_active`, `banner` (null=True, sans blank), `image_url`. Contrainte `svc_price_logic`.
- `ServiceViewSet` : `permission_classes=[IsAuthenticatedOrReadOnly, IsOwnerOrAdmin]` (491), `owner_lookup="handyman"`. **Pas de `perform_create`** et `ServiceSerializer.handyman = PrimaryKeyRelatedField(queryset=User.objects.all())` (`serializers.py:279`). Tout utilisateur authentifié (client compris) peut donc créer un service au nom de n'importe quel user. Lecture publique : list, retrieve et `nearby` (AllowAny, `authentication_classes=[]`).
- `ServiceImageViewSet` (`views.py:568-573`) : `IsAuthenticated`, queryset global, **sans scoping propriétaire**. Tout utilisateur authentifié peut modifier ou supprimer l'image de n'importe quel service (IDOR).
- `HandymanProfileViewSet` (`views.py:352-449`) : `[IsAuthenticated, IsOwnerOrAdmin]`. La liste et le détail exposent à **tout utilisateur authentifié** les `cni_number`, `license_number`, `insurance_info`, la `location` exacte et l'email (`user_detail = UserMiniSerializer`, `serializers.py:28-31`). Il n'existe pas de détail public d'un artisan, seulement `featured`.
- `PublicUserMiniSerializer` (`serializers.py:72-78`) expose `last_name` en entier dans `/services/` alors que le nom d'affichage public est « Prénom N. ».

## 5. Audit, historique et RBAC existants
- Journaux métier réutilisables comme patrons :
  - `PaymentLog` (`models.py:721-726` : previous_status, new_status, changed_at, notes), créé dans `Payment._set_status` et `refund`.
  - `BookingTimeline` (954-957 : status, at), créé dans `Booking.transition_to` (564).
  - `Dispute` (754-813) : machine d'états avec `resolved_by`, `resolved_at`, `resolution` et l'action admin `resolve` (`views.py:783`, IsAdminUser), c'est le modèle le plus proche d'une « décision motivée ».
  - Machines d'états : `Booking.TRANSITIONS` (508-517) et `Payment.ESCROW_TRANSITIONS` (626-633).
- `Notification.TYPES` (`models.py:858-868`) n'a aucun type KYC (la base contient aussi le type legacy `booking_response`, hors choices).
- Apps installées mais **non branchées** : `simple_history` (aucun `HistoricalRecords`, pas de middleware) et `actstream` (aucun `registry.register`). `django_cleanup` est actif : il supprime le fichier à la suppression ou au remplacement d'un document. Présents dans `requirements.txt` mais ni installés ni utilisés : `django-otp` 1.6.0, `django-phonenumber-field` 8.1.0, `guardian`.
- RBAC : uniquement `is_staff`, via DRF `IsAdminUser` (`views.py:783, 974, 1429`) et `OwnerScopedQuerysetMixin`/`IsOwnerOrAdmin`, qui accordent tout au staff. `CustomUserAdmin.get_form` (`admin.py:69-77`) désactive `is_superuser` et `user_permissions` pour les non-superusers. Aucun groupe Django en base dev, aucune permission custom.
- Anti-bruteforce existant : `axes` (backend base.py:180, middleware, `AXES_FAILURE_LIMIT=5`, `COOLOFF=1h`, l.440-446), scope de throttle `login` 10/min (base.py:213). SIMPLE_JWT (230-236) : access 30 min, refresh 7 j, rotation et blacklist actives.
- OTP existant : `OTPCode` (`models.py:995-1017`, purposes signup/login/phone, code en clair, sans compteur de tentatives). Vues `otp_request`/`otp_verify` (`views.py:1081-1111`, authentifiées) et `_send_sms` en stub de log (`tasks.py:32-36`).

## 6. Tests existants liés au KYC et aux artisans
- `handy/test_sprint4bis.py` : `test_artisan_televerse_sur_son_profil`, `test_kyc_file_url_is_guarded_and_not_serialized`, `test_kyc_rejects_unsafe_file_type`, `test_admin_approuve_document_valide_kyc`, `test_admin_rejette_document`, `test_revue_reservee_admin`, `test_presence_bloquee_si_non_verifie` (stockage `INMEM_STORAGES` sans alias `private_kyc`, donc repli sur default).
- `handy/test_sprint2.py:117` `test_presence_active_le_matching`.
- `handy/test_sprint6.py` : `test_quality_score_composite`, `test_avis_met_a_jour_quality_score`, `test_otp_request_puis_verify`, `test_otp_expire_rejete`.
- `handy/test_sprint5.py` : `test_matching_exclut_artisan_en_conge`, `test_declaration_absence_genere_remplacements`, `test_accept_replacement_reassigne_la_mission`.
- `handy/test_lot1_public.py` (non commité) : `test_featured_only_approved_active_and_no_sensitive_fields`, `test_services_filters` (l.343-344 : services d'artisans non approuvés et services inactifs listés publiquement), `test_public_stats_real_values_and_cache`, etc. `SENSITIVE_KEYS` (l.22-23) est réutilisable.
- `handy/tests.py:102` `test_match_endpoint` (fixture `is_approved=True`, l.61).
- `handy/test_security_sprint1.py` : `test_signup_rejette_role_admin`, `test_signup_client_ok_sans_privilege`, `test_idor_booking_invisible_aux_tiers`.
- Environ 60 occurrences dans 10 fichiers de tests reposent sur `user_type="handyman"` et sur la création automatique du profil par le signal.

## DATA
Base dev : PostgreSQL `tratra` (DJANGO_ENV=dev, MINIO_ENABLED=False, private_kyc = PrivateKycFileSystemStorage). Le dossier `private_kyc/` n'existe pas et la migration 0027 n'est pas appliquée (`[ ] 0027_private_kyc_document_storage`).
- Users : 2 au total, tous `is_verified=True` et actifs. id=1 `ogah`, user_type=`employeur`, is_staff + is_superuser, sans téléphone. id=8 `serge`, user_type=`handyman`, **is_staff=True** (un artisan staff peut donc approuver ses propres documents KYC via `/review/`). Son téléphone est stocké en **format local à 10 chiffres sans « + » (commence par 0575)**, donc pas en E.164, et son username n'est pas le téléphone. Aucun email vide. Groupes Django : 0. Permissions individuelles : 0.
- HandymanProfile : 1 au total (id=2, user 8). Approuvés : 0, non approuvés : 1. En ligne : 0. location NULL : 1. availability `{}` : 1. Skills : [1,2,3,5]. Complétion 75 %, `has_required_kyc()=False`, quality_score=0, cni_number renseigné, photo présente, commune vide.
- Users user_type=handyman sans profil : 0. Profils dont le user n'est pas handyman : 0 (répartition : handyman=1).
- HandymanDocument : **0** (tous types et statuts confondus). `media/handyman_documents/` existe mais contient 0 fichier, et `media` est gitignoré.
- Services : 2, tous actifs, tous d'un artisan **non approuvé** (user_type handyman). Ils sont aujourd'hui visibles publiquement dans `/services/`. Services d'un user sans profil : 0.
- Catégories : 55, toutes actives (50 racines, 5 enfants).
- Bookings : 1 (statut confirmed, client user_type=employeur, service.handyman == booking.handyman). Payments, PaymentLog, Payout, Review, Dispute, OTPCode, BookingTimeline, TimeOff, ServiceArea, AvailabilitySlot, CompanyProfile, DepositTransaction et PayoutAccount : 0 chacun. Notifications : 10 (dont le type legacy `booking_response`, hors `Notification.TYPES`).
- Vérification en lecture seule : avec le stockage privé FS, `ClearableFileInput().is_initial(HandymanDocument(file='kyc/1/x.pdf').file)` lève `NotImplementedError`. L'admin Django plantera donc dès qu'un document avec fichier existera.

## RISKS
- Faille actuelle à corriger dans la refonte : HandymanProfileSerializer (handy/api/serializers.py:211-235) n'a pas de read_only_fields. Un artisan peut faire PATCH /handy/handymen/{id}/ {is_approved:true} et apparaître ensuite dans le matching, featured et presence. Le champ `user` est aussi modifiable : POST d'un profil pour un autre user, réattribution par PATCH.
- Faille : ServiceViewSet (views.py:484) n'a pas de perform_create et ServiceSerializer.handyman est modifiable (serializers.py:279). Tout utilisateur authentifié peut créer un service au nom de n'importe quel user, approuvé ou non. ServiceImageViewSet (views.py:568) n'est pas scopé par propriétaire (IDOR en modification et suppression).
- Fuite de données d'identité : la liste et le détail de HandymanProfileViewSet (IsAuthenticated) renvoient cni_number, license_number, insurance_info, la location exacte et l'email de tous les artisans à n'importe quel compte connecté. Cela contredit l'exigence « ne jamais exposer les documents d'identité ».
- Le badge « vérifié » (PublicArtisanMiniSerializer.is_verified = is_approved, serializers.py:84 ; Flutter artisan.dart:66) peut s'afficher sans aucun document approuvé : approve_profiles (admin.py:159-162) fait queryset.update sans contrôle des documents, et approuver un document ne met pas à jour le profil. Il faut une source de vérité unique (statut KYC) et dériver is_approved de cette source.
- Le catalogue public n'est pas filtré aujourd'hui : /services/, /services/nearby/, alternatives, services_count des catégories, public_stats.services et les slides incluent les services d'artisans non approuvés ou inactifs. Restreindre aux profils APPROVED casse test_lot1_public.py:343-344 (comportement historique assumé) et cache les 2 services dev existants, tous d'un artisan non approuvé.
- La suspension ou révocation n'existe pas. Retirer is_approved ne remet pas online à False, et match_artisans (matching.py:13) ne filtre pas user__is_active. Il faut couper la présence, le matching, featured, la liste des services, les remplaçants et la réservation dans la même transaction.
- La réservation n'est pas conditionnée : BookingCreateSerializer accepte n'importe quel handyman ou service, sans vérifier la cohérence service.handyman == handyman ni le statut APPROVED. Après la refonte, il faut décider du sort des réservations existantes vers des artisans non approuvés (1 booking confirmé en dev vers un artisan non approuvé) : à conserver, sans les bloquer rétroactivement.
- Migration des statuts : HandymanDocument.status (pending/approved/rejected) et HandymanProfile.is_approved (booléen) doivent être mappés vers DRAFT/PENDING/REVIEW/APPROVED/REJECTED/SUSPENDED sans perte. Les profils is_approved=True sans id_card approuvé (0 en dev, inconnu en prod) ne doivent pas devenir APPROVED par défaut, ce qui reviendrait à un faux KYC validé. Il faut les placer en REVIEW, ou marquer « legacy approved » pour décision humaine.
- La migration 0027 n'est pas appliquée en dev. La prochaine migration doit dépendre de 0027, et la commande migrate_kyc_documents_to_private_storage doit passer avant toute reprise des fichiers. django_cleanup est actif : une resoumission ou un remplacement de fichier, ou la suppression d'un document ou d'un profil (CASCADE), efface la preuve KYC. C'est incompatible avec l'audit et la conservation, il faut un soft-delete ou une exclusion de cleanup pour les documents KYC.
- L'admin Django KYC renvoie une erreur 500 en environnement sans MinIO (confirmé : NotImplementedError via ClearableFileInput sur PrivateKycFileSystemStorage.url). Côté MinIO, le widget afficherait une URL S3 présignée directe qui contourne le endpoint gardé. Il faut retirer `file` des formulaires admin (lecture seule avec lien download).
- L'admin peut éditer status, reviewed_by et rejection_reason à la main (HandymanDocumentAdmin sans fields ni readonly), sans trace ; reviewed_at/by est écrasé à chaque revue. Aucun historique n'existe : simple_history et actstream sont installés mais non utilisés.
- RBAC limité à is_staff : en dev, l'artisan id=8 est is_staff et peut s'auto-approuver via POST /handyman-docs/{id}/review/. Il faut une permission dédiée (groupe « kyc_reviewer » ou permission de modèle) et interdire de revoir son propre dossier.
- La suppression de user_type à l'inscription casse le signal de création de profil (signal.py:11-15), une soixantaine d'usages dans 10 fichiers de tests, RoleGuard et auth.tsx côté React (redirection par user_type), ainsi que le seed create_fake_data. user_type doit rester en compatibilité de lecture pendant la transition.
- Téléphone : le champ User.phone est unique, CharField(20) et non normalisé (ex. dev : 10 chiffres locaux « 0575… » sans +225). La normalisation E.164 doit gérer les doublons et collisions avant d'ajouter une contrainte. User.email est EmailField(unique=True) non nullable : une inscription par téléphone seul avec email vide provoquera des collisions sur ''.
- OTP actuel faible pour un usage KYC ou récupération de compte : code stocké en clair, pas de compteur de tentatives, endpoints authentifiés uniquement, SMS en stub (tasks.py:32-36), code renvoyé dans la réponse si DEBUG.
- Fichiers en cours de modification par d'autres agents : handy/api/views.py, serializers.py, urls.py (non commités) et handy/test_lot1_public.py. Les modifications KYC dans ces fichiers risquent des conflits. Il vaut mieux isoler la logique KYC dans un nouveau module (handy/kyc/ ou handy/services/kyc.py) et n'insérer que des points d'accroche minimaux dans views.py.

## REUSE
- handy/storage.py : KycPrivateStorage (proxy d'alias), PrivateKycS3Storage (ACL privée, URL signées 300 s), PrivateKycFileSystemStorage, à réutiliser tels quels pour CNI recto/verso et selfie
- handy/models.py:199-207 private_kyc_upload_path (clé opaque kyc/{profile_id}/{uuid}.ext)
- HandymanDocumentSerializer.validate_file (serializers.py:562-583 : taille, MIME et extension) et les settings KYC_MAX_UPLOAD_BYTES, KYC_ALLOWED_CONTENT_TYPES, KYC_SIGNED_URL_TTL_SECONDS (base.py:293-304)
- HandymanDocumentViewSet.download (views.py:947-972) : streaming gardé, scoping propriétaire ou staff, 404 anti-énumération et en-têtes no-store, à généraliser aux preuves KYC
- HandymanDocument.approve/reject (models.py:236-250) et les champs reviewed_by/reviewed_at/rejection_reason comme base des décisions motivées
- Commande migrate_kyc_documents_to_private_storage (dry-run, --apply, --delete-source) pour la reprise des fichiers legacy
- OwnerScopedQuerysetMixin et IsOwnerOrAdmin (views.py:64-111) pour l'anti-IDOR
- Patrons de journal d'audit : PaymentLog (models.py:721-726, previous_status/new_status/notes) et BookingTimeline ; patron de décision admin motivée : Dispute.resolve/reject (models.py:783-813) et l'action DRF IsAdminUser (views.py:783)
- Machines d'états existantes Booking.TRANSITIONS / transition_to et Payment.ESCROW_TRANSITIONS / _check, à imiter pour les transitions KYC DRAFT→PENDING→REVIEW→APPROVED/REJECTED/SUSPENDED
- Gardes publiques existantes : featured (views.py:415-449, is_approved + user__is_active), apply_public_service_filters (views.py:236-263), compute_public_stats (1168-1180), PublicArtisanMiniSerializer/PublicArtisanSerializer/public_display_name (serializers.py:51-113) et SENSITIVE_KEYS de test_lot1_public.py
- Gate presence (views.py:382) et match_artisans (services/matching.py) : il suffit de remplacer is_approved par le prédicat « publiable »
- HandymanProfile.compute_quality_score/refresh_quality_score et profile_completion (models.py:146-193) pour le critère « profil complet »
- Modèles déjà présents mais inexploités pour la candidature : AvailabilitySlot (disponibilités structurées), ServiceArea (zone, centre et rayon), TimeOff, skills M2M ServiceCategory (55 catégories, hiérarchie parent/children pour métiers et spécialités)
- Modèles OTPCode (models.py:995-1017) et _send_sms/_resolve_msisdn (tasks.py), anti-bruteforce axes et throttle scope 'login' (base.py:210-215, 440-446), SIMPLE_JWT avec rotation et blacklist (base.py:230-236)
- Écrans clients existants à adapter plutôt que réécrire : frontend/src/app/admin/kyc/page.tsx (file de revue et téléchargement privé), frontend/src/app/worker/kyc/page.tsx, Flutter lib/services/handyman_service.dart (presence et KYC)
- Tests KYC existants (handy/test_sprint4bis.py, INMEM_STORAGES) comme base des nouveaux tests rejet/approbation/suspension/permissions
