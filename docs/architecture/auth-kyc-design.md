# Tratra : compte unique, OTP, Handyman et KYC (document de conception)

> **Version 2, 2026-10-08.** Auteur : architecte principal. Destinataires : développeurs backend (Django), React (Next.js) et Flutter.
> Périmètre : exigences contractuelles 1 à 10 du brief client. Le lot « public » (landing, `/search`, `/handymen/featured/`, `/reviews/public/`, `/public/stats/`, filtres services, migration `0028_clean_business_plan_features`) est **considéré comme commité** avant le début de ce chantier.
> Le document est autoportant : chaque référence au code (`fichier:ligne`) renvoie à l'état du dépôt au 2026-10-08. La version 1 est archivée à côté (`auth-kyc-design.v1.md`).

---

## Changements suite à la revue

La version 1 a été attaquée par trois critiques indépendants (sécurité, migration, produit). Ils ont soulevé 52 points bloquants et 52 points recommandés. **Tous les points bloquants sont intégrés.** Quelques-uns le sont sous une forme différente de celle proposée ; la justification figure dans la section « Arbitrages ». Les points recommandés sont intégrés, sauf mention contraire dans « Arbitrages ».

### Ce qui change structurellement

1. **Approbation KYC en quatre cas fermés** (§2.3). Le badge « Identité vérifiée » n'est accordé que si un prestataire a confirmé, par un appel authentifié, la liveness et la comparaison faciale. L'approbation automatique est réservée aux captures faites par le SDK du prestataire. Toute capture « maison » (web ou mobile) passe par une revue humaine. Toute dérogation exige deux approbateurs distincts.
2. **Le webhook Smile ID n'est plus qu'un signal** (`Job-ID`). Toutes les données de décision viennent d'un appel serveur à serveur authentifié (§5.8). Le cadrage sandbox devient un lot **L0**, placé avant la capture.
3. **Trains de release avec go/no-go** (§10.0). Le cœur KYC (dépublication des legacy) n'est déployé en production que lorsqu'un chemin d'approbation existe. Les 410 sur les anciens endpoints n'arrivent qu'à la clôture. Aucune bascule de lien ne précède la page cible.
4. **« Proposer un service » crée de vrais services** (§1.5, §4.7) ; le prédicat publiable exige au moins un service actif. Les profils publiés sont référencés (sitemap dynamique, métadonnées, 404 réels).
5. **Compte legacy retrouvé à l'inscription** : après un OTP réussi, le titulaire d'un numéro porté par un compte legacy peut **revendiquer** ce compte au lieu d'en créer un second (§4.1).
6. **Moindre privilège du staff** : permissions nommées, MFA TOTP obligatoire, interdiction d'agir sur ses propres dossiers ou réservations, plus aucun passe-droit `is_staff` (§1.7, §5.3).
7. **Append-only réel** : rôle PostgreSQL d'exécution sans UPDATE, DELETE ni TRUNCATE sur les journaux, chaînage par hachage et ancrage quotidien (§1.10).
8. **Migrations expand/contract au niveau de la base** : DEFAULT durables, contraintes `NOT VALID` puis validées, migrations jouées par un job unique avec un rôle dédié (§6).
9. **OTP durci** : journal d'envois sous verrou consultatif, clé IPv6 agrégée, plafonds par préfixe, budgets séparés par usage avec réserve, défi anti-bot adaptatif (§5.1).
10. **Contrats unifiés** : format d'erreur codé partout où un code de l'annexe D est émis, `GET /public/config/`, `is_verified` supprimé au lieu d'être réinterprété (§4.0, §3.5).
11. **Numérotation des migrations décalée** : le lot public a ajouté `0028_clean_business_plan_features`. Nos migrations commencent à `0029` (§6.1).

### Correspondance point par point

Identifiants : `S-M` et `S-S` pour la critique sécurité (bloquant, recommandé), `M-M` et `M-S` pour la migration, `P-M` et `P-S` pour le produit, `X` pour les écarts trouvés pendant la révision. L'ordre suit celui des critiques.

#### Sécurité, points bloquants

| # | Point | Résolution | § |
|---|---|---|---|
| S-M1 | Drapeaux calculés sur le corps non signé du webhook | Le corps du webhook n'est plus lu (seul `Job-ID` sert de signal). Statut, `actions`, `id_fields`, antifraude, `user_id` et `partner_params` viennent d'un appel authentifié. `user_id` et `partner_params.submission_id` sont vérifiés (`provider_identity_mismatch`). Une signature invalide incrémente un compteur, sans écriture en base. Sans endpoint authentifié complet, l'auto-approbation est désactivée au démarrage. | §5.8, §2.5 |
| S-M2 | Doublons ignorant les profils rejetés ou révoqués | Doublon = HMAC présent sur **toute** autre soumission soumise, quel que soit son statut. Doublon avec un profil écarté pour fraude : rejet définitif et alerte. Toute approbation avec doublon : 409 `duplicate_identity`, sauf dérogation Superviseur à quatre yeux. Trousseau de clés HMAC versionné. | §2.5, §2.3 |
| S-M3 | Liveness maison sans résistance à l'injection | Auto-approbation réservée aux captures SDK (`capture_channel` `sdk_*`) dont les signaux appareil sont relus côté serveur. Captures maison : revue humaine obligatoire. SDK web hébergé = chemin nominal web. `capture_metadata` déclaré non fiable. Tests d'injection en L0. | §2.3, §5.8, D8 |
| S-M4 | Règles d'approbation contradictoires | Quatre cas fermés A à D dans `KycService`, un test chacun. Jeu de preuves complet, `evidence_viewed` du décideur, `actions` conservées, legacy jamais approuvable, `sandbox` jamais badgé, plus de clause « ou DEBUG ». Approbation manuelle : sans badge, quatre yeux. | §2.3 |
| S-M5 | Nouvelle voie d'approbation en L1 | `approve_profiles` supprimée, `is_approved` en lecture seule partout, **gel des approbations** jusqu'au train R3. Test : aucun chemin ne fait passer `is_approved` à vrai. | §10 L1b, C3 |
| S-M6 | Escalade RBAC via l'admin Django | `groups`, `is_staff`, `is_superuser` et `user_permissions` désactivés pour les non-superusers ; personne ne modifie ses propres privilèges ; `GroupAdmin` réservé aux superusers ; événements `privilege_*` et `staff_flag_changed`, alerte Sentry ; recertification via `identity_report`. | §1.7, §10 L1b |
| S-M7 | Pouvoirs globaux d'`is_staff` | Passe-droit `is_staff` retiré des permissions et des querysets. Lecture globale par `view_all_records`, écritures par permissions nommées (`resolve_dispute`, `manage_payouts`). 403 `self_dealing_forbidden` sur toute action où l'agent est partie. Le staff ne modifie plus d'autre compte par l'API. `is_staff` refusé à un compte Handyman. | §1.7, §10 L1b |
| S-M8 | Garde par compte contournée par `/admin/`, pas de MFA | Garde déplacée dans le backend d'authentification (couvre l'admin). `ADMIN_URL` non devinable et allowlist IP. MFA TOTP obligatoire (claim `amr`) pour le staff dès R2, avant la visionneuse. Réinitialisation par SMS désactivée pour le staff. Refresh staff de 12 h. | §5.3, §5.6, §4.4 |
| S-M9 | Append-only contournable par le superuser PostgreSQL | Rôles `tratra_migrator` (propriétaire, job de migration) et `tratra_app` (exécution, `SELECT, INSERT` seulement sur les journaux). Trigger conservé. Chaîne de hachage par profil, ancrage WORM quotidien, commande de vérification. Instantané complet dans l'événement de décision. Inverse de la reprise bloqué dès qu'un vrai événement existe. | §1.10, §6.1 |
| S-M10 | Course sur les quotas OTP | Table `OtpSendLog` (une ligne par SMS, leurres compris) ; vérification et réservation sous `pg_advisory_xact_lock` par numéro et par pays ; le worker revérifie le budget. Test de concurrence à 20 threads. | §1.3, §5.1 |
| S-M11 | Pumping de SMS | Clé IP = IPv4 ou préfixe /64 (/48 au jour), y compris pour les throttles DRF. Défi Turnstile adaptatif. Plafond par préfixe national. Budgets séparés par usage avec réserve de 20 % pour les comptes existants. Coupure par pays. File Celery `otp` dédiée. | §5.1, C11 |
| S-M12 | Verrouillage ciblé d'un compte | Compteurs par famille d'usage (`signup`, `reset`, `phone`, `stepup`) : les leurres d'inscription ne touchent jamais le budget de réinitialisation. La garde ignore les appareils connus (jeton d'appareil signé), plafond d'1 h, au plus un SMS d'alerte par jour. | §5.1, §5.3 |
| S-M13 | Oracle à la réinitialisation | Avant le code : validateurs indépendants de l'utilisateur seulement. Après un code correct : validateurs de similarité, et en cas d'échec le challenge n'est pas consommé. Test d'indiscernabilité. | §4.3 |
| S-M14 | Prise de contrôle monétisable | Réinitialisation legacy non vérifiée refusée pour les comptes à valeur. Retenue de 72 h des versements après réinitialisation, changement de numéro ou de compte de versement. `POST /payout-account/` exige mot de passe et OTP. Artisan approuvé : dépublié jusqu'à une ré-authentification (revue humaine, puis SmartSelfie en L10). | §4.3, §4.5, §4.6, §2.7 |
| S-M15 | Pièces collectées avant le consentement | Tout upload exige le consentement de la version courante (409 `consent_required`). Changement de version : nouveau consentement et purge des pièces non soumises. | §4.8 |
| S-M16 | MinIO exposé, identifiants partagés | Console retirée de Traefik ; compte de service KYC dédié (Put, Get, rétention, tags ; ni Delete ni List) ; `url()` lève une erreur ; aucun repli silencieux ; chiffrement applicatif AES-GCM versionné ; versioning, verrouillage d'objet et cycle de vie par tag. | §5.9 |
| S-M17 | `create_fake_data` en production | Refus hors `DJANGO_ENV=dev` avec `DEBUG`, plus de superuser à mot de passe fixe, aucun profil approuvé (option `--dev-approve` en `verification_level=seed`, exclu hors dev). Même garde sur `CREATE_SUPERUSER` de l'entrypoint (X-2). | §6.7, §10 L1b |
| S-M18 | Rotation des refresh non atomique | Rotation sous `select_for_update` avec création unique de la liste noire ; détection de réutilisation au-delà de 30 s, qui révoque toutes les sessions. | §5.6 |
| S-M19 | Sentry envoie les variables locales | `include_local_variables=False`, `before_send` qui vide les frames sensibles, denylist étendue, `send_default_pii` forcé à faux en production, breadcrumbs coupés pour `handy.identity`, filtre de journal étendu aux formats locaux. | §5.10 |

#### Sécurité, points recommandés

| # | Point | Résolution | § |
|---|---|---|---|
| S-S1 | Oracle de l'inscription legacy | Dès L1, le numéro saisi à l'inscription legacy est ignoré (enregistré à NULL, à prouver ensuite par OTP). Conflits d'email et de username sous un code générique `signup_unavailable`. Throttle `auth_register` avec la clé /64 (L2). | §4.12 |
| S-S2 | Trilatération via `/services/nearby/` | `public_location` (cellule de 0,01° ≈ 1,1 km) pour tout calcul public, rayons par paliers. | §1.5, §3.3 |
| S-S3 | EXIF, IDOR `ServiceImage`, `image_url`, `?handyman` | Réencodage Pillow de toutes les images publiques ; `service` en lecture seule après création et propriété vérifiée ; `image_url` limité aux hôtes du projet ; égalité stricte avec `request.user.id`. | §10 L1a |
| S-S4 | Portée de l'accès aux preuves | Accès limité aux soumissions en revue prises en charge, ou au Superviseur ; sinon « bris de glace » motivé et alerté ; throttle à 60/h. L1 : téléchargement legacy par un tiers réservé aux superusers et journalisé. L'admin Django n'affiche aucun lien vers une preuve. | §5.9, §4.11 |
| S-S5 | Visionneuse en `blob:` et CSP | Images en `<img>`, PDF en téléchargement seulement, type du Blob forcé, CSP à nonce et Trusted Types sur `/admin`, caméra autorisée uniquement sur les routes de capture. | §5.11, §7.3 |
| S-S6 | Réponses authentifiées cachables | Middleware `no-store, private` et `Vary` sur toute réponse authentifiée et tout `/handy/auth/*` et `/handy/admin/*`. | §5.3 |
| S-S7 | Épuisement du stockage | 10 remplacements par type et par tentative, quota de 200 Mo par profil, purge à 30 jours des brouillons et pièces remplacées par cycle de vie. | §4.8, §5.9 |
| S-S8 | Versements d'un artisan révoqué | Gel des fonds (`funds_frozen`) dès une révocation ou un motif de fraude, levé par le Superviseur. | §2.4 |
| S-S9 | `Booking.transition_to` sans contrôle d'acteur | Table des transitions par rôle ; la fin déclarée par l'artisan ne libère le séquestre qu'après confirmation du client ou 48 h sans litige (voir Arbitrages A6). | §10 L1c |
| S-S10 | Clé JWT partagée, pas d'`aud` | `JWT_SIGNING_KEY` dédiée, `aud` et `iss`, access de 10 min en mode web, liste de refus des `jti` à la déconnexion, `Origin: null` refusée, contrôle de CORS au démarrage. | §5.6 |
| S-S11 | `kyc_subject_id` sans défaut, `HandymanDocument` en CASCADE | Défaut `uuid4` côté Python et `gen_random_uuid()` en base ; PROTECT en 0029. | §6.1 |
| S-S12 | Migrations au démarrage, barrière qui échoue | `RUN_MIGRATIONS=0` en production, job de migration unique, contrôles préalables à la place des barrières. | §6.8 |
| S-S13 | Email non vérifié servant d'identifiant | Changement d'email par lien, réponse identique ; connexion par email réservée aux emails vérifiés ou présents avant la bascule (voir Arbitrages A5) ; unicité insensible à la casse. | §4.4, §6.3 |
| S-S14 | Fichiers temporaires et captures d'écran Flutter | Suppression des fichiers après envoi ou abandon, `FLAG_SECURE` et masquage de l'aperçu iOS sur OTP et KYC. | §8.2, §8.3 |
| S-S15 | Biométrie collectée sans autorisation ARTCI | En production, uploads de selfie et de liveness refusés (503 `kyc_unavailable`) sans `KYC_LEGAL_APPROVAL_REF`. | §4.8, C6 |
| S-S16 | Proxys de confiance trop larges, SSR | Seule l'IP fixe de Traefik est de confiance ; le rendu serveur Next porte un en-tête HMAC qui l'exempte du throttle anonyme, jamais des quotas OTP. | §5.3, §3.6 |
| S-S17 | Oracle de temps si `OTP_SEND_ASYNC` est faux | `ImproperlyConfigured` en production ; écriture de taille équivalente pour un leurre ; test de temps. | §5.1, §5.2 |

#### Migration, points bloquants

| # | Point | Résolution | § |
|---|---|---|---|
| M-M1 | `kyc_subject_id` et `challenge_id` sans défaut | État final `UUIDField(default=uuid4, unique=True)` et `DEFAULT gen_random_uuid()` en base. Test du signal `user_type='handyman'`. | §6.1 |
| M-M2 | DEFAULT supprimé par Django, ancienne image cassée | DEFAULT durable posé par `RunSQL` (état inchangé) pour chaque colonne NOT NULL ajoutée ; test qui vérifie leur présence ; runbook : arrêt de `worker` et `beat`, job de migration unique, redémarrage sur la même image. | §6.1, §6.8 |
| M-M3 | Inverses des migrations d'identité faux (0029 et 0030 en v1, désormais 0032 et 0033) | Vrais inverses (OTP sans utilisateur supprimés, codes NULL neutralisés, emails NULL remplacés par une valeur traçable), ordre de rollback fixé, test aller-retour avec des lignes NULL. Rollback déclaré destructif après la première inscription par téléphone (Arbitrages A13). | §6.9 |
| M-M4 | `create_permissions` sans effet en migration | Recette `models_module = True` le temps de l'appel, puis recherche par `content_type__app_label`. Test sur base fraîche. | §6.1 |
| M-M5 | Normalisation des téléphones incohérente | Aucune écriture E.164 avant `normalize_user_phones --apply` : l'inscription legacy n'enregistre plus le numéro (L1), `PHONE_SIGNUP_ENABLED` est faux par défaut et refusé tant qu'il reste un numéro non E.164. Règle « le compte vérifié l'emporte ». `--rollback` exclut les comptes vérifiés, libérés ou en conflit. | §6.2 |
| M-M6 | `User.save()` qui normalise | `save()` ne fait plus que `''` → `NULL`. Normalisation dans les serializers, le formulaire admin et la commande. | §1.1 |
| M-M7 | Course sur la dérivation dans `HandymanProfile.save()` | Champs « KYC » réservés : une sauvegarde ordinaire les exclut, seuls `KycService` et `refresh_publication` (sous verrou) les écrivent. Test d'instance périmée. | §1.5 |
| M-M8 | Frais d'annulation à 0 pour tous les legacy | Gratuité limitée aux artisans suspendus ou révoqués **après** la création de la réservation (`withdrawn_at`). `test_sprint4` reste vert. La dépublication legacy ne modifie pas les réservations. | §2.4 |
| M-M9 | `BOOKING_REQUIRES_PHONE_VERIFIED=true` par défaut | Défaut `false` partout ; activation par le runbook après R2 et la mise à jour forcée des apps ; période de grâce pour les clients sans `X-Tratra-Client`. | §3.4, §6.8 |
| M-M10 | Catalogue vidé en L5 | Barrière de train : R3 n'est déployé en production qu'avec un chemin d'approbation opérationnel (L10, ou C2 accepté par écrit). | §10.0, C2 |
| M-M11 | Correspondance legacy incomplète | Table de décision exhaustive, branche par défaut, fonction pure partagée par la migration et le rapport, `mode=legacy` exclu des tentatives, `submitted_at` renseigné, demande de nouvelle vérification dans la même fenêtre. | §6.4 |
| M-M12 | CHECK sur des données invalides | Correction des données dans la migration précédente, contraintes ajoutées en `NOT VALID` puis validées ; aucune migration qui échoue volontairement. | §6.1 |
| M-M13 | L1 non commitable | `test_lot1_public.py` mis à jour en L1 ; critère « Done » : suite complète et `makemigrations --check` (ajouté à la CI). | §10 |
| M-M14 | Connexion par username devenue sensible à la casse | Backend équivalent à allauth : username `iexact`, email via `EmailAddress` puis `User.email`, liste de candidats, nombre de hachages constant. | §5.3 |
| M-M15 | Vérification des réglages de production en CI | Chaque lot met à jour `ci.yml`, `.env.example` et les prérequis de déploiement ; refus de démarrer uniquement si la fonctionnalité concernée est active. | §6.8, annexe A |
| M-M16 | Réglages de test non appliqués | `handy/conftest.py` avec fixture autouse ; aucun défaut dérivé de `DEBUG` dans `base.py` ; `on_commit` exécuté dans les tests concernés. | §9.1 |

#### Migration, points recommandés

| # | Point | Résolution | § |
|---|---|---|---|
| M-S1 | Relations encore en CASCADE | PROTECT étendu à `HandymanDocument`, `Invoice`, `Subscription`, `Review`, `Dispute`, `PayoutAccount` ; service avec réservations désactivé au lieu d'être supprimé ; suppression de compte réservée aux superusers dans l'admin. | §6.1 |
| M-S2 | Inverse de la reprise et fonction de trigger | Ordre d'inverse explicite ; la fonction n'est supprimée que par l'inverse de sa migration de création. | §6.1 |
| M-S3 | Passage de la connexion de 400 à 401 | 401 seulement pour les clients qui envoient `X-Tratra-Client` ; connexion appelée sans rejeu. | §4.2 |
| M-S4 | Profil public indexé par id de profil | Profil public indexé par **id utilisateur** ; `GET /handymen/{pk}/` d'un tiers : 404. | §4.13 |
| M-S5 | 410 prématurés, groupes sans membres | 410 seulement en L11 (drapeau `LEGACY_KYC_DOCS_WRITE_ENABLED`) ; commande `grant_role` dans le runbook. | §4.12, §6.8 |
| M-S6 | Données legacy contraires aux nouvelles règles | Règles appliquées aux seuls champs modifiés ; `legacy_constraints_violations` et `legacy_availability` exposés. | §4.7 |
| M-S7 | Capacités avant L5 | Correspondance intermédiaire spécifiée, fixture « pré-L5 ». | §4.4 |
| M-S8 | Runbook trop léger | Sauvegarde, répétition chronométrée sur une copie, `lock_timeout`, contrôle de 0027, copie des fichiers privés juste après. | §6.8 |
| M-S9 | Unicité de l'email sensible à la casse | Contrôle `iexact` dès L3, index unique fonctionnel en L11 (`CONCURRENTLY`). | §6.3 |
| M-S10 | Instantané en `__init__`, `.only()` | Instantané dans `from_db()`, `.only()` retiré, recalcul conditionné à `update_fields`. | §3.2 |
| M-S11 | `JWTAuthentication` déclarée explicitement | Remplacée partout par `TratraJWTAuthentication`. | §5.6 |
| M-S12 | Synchronisation `Meta` et migrations | Liste exhaustive par migration, `makemigrations --check` en CI, callables référencés jamais renommés. | §6.1 |
| M-S13 | Titulaire vérifié mais désactivé, téléphone legacy invalide | Revendication avec réactivation (§4.1) ; numéro ignoré à l'inscription legacy ; message de 410 lisible. | §4.1, §4.12 |
| M-S14 | Incrément d'essai qui viole la CHECK | `UPDATE … WHERE attempts < max_attempts`, sinon `otp_locked` sans écriture. | §5.1 |
| M-S15 | Flush des tests transactionnels, clé `availability` | Groupes et plans recréés par fixture ; clé publique renommée `availability_slots`. | §9.1, §4.13 |

#### Produit, points bloquants

| # | Point | Résolution | § |
|---|---|---|---|
| P-M1 | « Proposer un service » ne crée aucun service | Étape « Mes services » dans la candidature, page de gestion React et Flutter, condition 11 « au moins un service actif » (code `services`). | §1.5, §3.1, §4.7 |
| P-M2 | Référencement absent | `GET /public/handymen/` (liste publiable), sitemap dynamique, `generateMetadata`, JSON-LD sans PII, 404 réels. | §4.13, §7.3 |
| P-M3 | Cadrage Smile ID trop tardif | Lot **L0** avant L6, avec tests d'injection ; `requirements` figés sur ses résultats. | §10 L0 |
| P-M4 | Ruptures entre lots | Bascule du CTA en L7a ; en L6 un simple en-tête `Deprecation` ; 410 en L11 ; trains de release R1 à R6. | §10.0 |
| P-M5 | Second compte créé sur un numéro legacy | Après OTP réussi : 409 `legacy_account_found` et revendication (`POST /auth/register/claim/`), création explicite d'un nouveau compte, ou récupération si la politique le permet. | §4.1 |
| P-M6 | Préférences sans effet | Schéma réduit à `notifications.sms`, la seule préférence branchée ; toute nouvelle clé arrive avec son branchement. | §1.1 |
| P-M7 | Filtre « Vérifiés » inactif | Retiré dans le train R3 (L7d), paramètre d'URL ignoré. | §7.3 |
| P-M8 | `is_verified` à double sens | `is_verified` n'est plus émis nulle part à partir de R3 ; `phone_verified` et `identity_verified` seulement ; badge sans chaîne de repli ; test de contrat. | §3.5 |
| P-M9 | Format d'erreur variable | Règle unique : tout code de l'annexe D est émis sous la forme `{code, detail, …}` ; `fields` = `{champ: [{code, message}]}`. | §4.0 |
| P-M10 | Configuration serveur introuvable | `GET /handy/public/config/`. | §4.13 |
| P-M11 | Pages CGU et confidentialité absentes | Textes versionnés fournis par le juriste, servis par l'API et hachés ; routes `/cgu` et `/confidentialite` ; drapeaux refusés au démarrage tant qu'ils manquent. | §4.13, §7.2, C6 |
| P-M12 | Capture Flutter irréaliste | Résolution moyenne, compression en isolate, tailles cibles, JPEG forcé, prévalidation locale, nettoyage. | §8.3 |
| P-M13 | Justificatifs perdus à chaque tentative | Modèle `HandymanProof` indépendant du KYC, endpoints dédiés, revue admin. | §1.6, §4.9 |
| P-M14 | Candidature publique qui écrase un profil | `create_only` et 409 `handyman_profile_exists`, écran de comparaison. | §4.7, §7.3 |
| P-M15 | Décisions engageantes appliquées par défaut | C2, C3, C6 et C9 bloquants (go/no-go écrit), journal daté ; aucun commit dans le dépôt Flutter sans accord explicite de l'utilisateur. | §0.3, §0.4 |
| P-M16 | Composants du lot public basés sur `user_type` | Trois fichiers ajoutés à L4 ; garde-fou `grep` dans `npm run verify`. | §7.1 |
| P-M17 | Aucun test de parcours | `handy/test_journeys.py` (un test par parcours du point 10), tests de widgets Flutter, smoke Playwright React (Arbitrages A12). | §9 |

#### Produit, points recommandés

| # | Point | Résolution | § |
|---|---|---|---|
| P-S1 | L5 et L7 trop gros | L5a/L5b et L7a/L7b/L7c/L7d ; L1, L3 et L9 aussi découpés. | §10 |
| P-S2 | Fixtures trop tardives | Me et erreurs en L3, admin en L5b, KYC en L6 ; script de synchronisation et contrôle d'empreinte en CI mobile. | §4.14 |
| P-S3 | Caches et SSR | `/artisans/[id]` en `no-store`, tags et revalidation dans le train R3, en-tête HMAC de rendu interne. | §3.6 |
| P-S4 | Pas de liste des profils en admin | `GET /admin/kyc/profiles/`, page « Handymen », permissions sans préfixe dans `Me`, `grant_role`. | §4.11 |
| P-S5 | CGNAT, budgets, file `otp` | Seuils IP comme signaux (défi) et plafond dur élevé ; budgets par usage ; file dédiée ; `expires_at` posé à l'envoi effectif. | §5.1 |
| P-S6 | Réinitialisation et retenue | Fusionné avec S-M13 et S-M14. | §4.3 |
| P-S7 | UUID et création concurrente de tentative | Défauts UUID ; tentative créée sous verrou du profil. | §4.8 |
| P-S8 | Boucle 401 → refresh sur `/auth/*` | Exclue dans les deux clients ; purge immédiate sur `session_revoked` ou `account_inactive`. | §7.1, §8.1 |
| P-S9 | Notifications invisibles | `handyman_available` et `cancellation_fee_waived` dans les réservations, bandeaux, page de notifications ; aucune promesse de push. | §2.4, §7.3, §8.2 |
| P-S10 | Badge en approbation manuelle | Pas de badge « Identité vérifiée » ; libellé « Pièce contrôlée par Tratra ». | §3.5 |
| P-S11 | Spécialités vides, communes libres | Étape sautée sans sous-catégorie, `specialties_extra`, liste fermée de communes réelles (Arbitrages A16). | §4.7 |
| P-S12 | Libellés trompeurs | « Continuer vers la vérification d'identité », `application_submitted_at` posé au submit KYC, `copy.fr.json` partagé. | §4.14, §7.3 |
| P-S13 | Repli caméra et support fictifs | Lien vers l'app seulement s'il est configuré, sinon QR code ; contact support réel exposé par la configuration ou messages reformulés. | §7.3 |
| P-S14 | Défauts Flutter existants | Onglets branchés ou masqués, parseur réécrit sur la fixture, mémorisation de l'espace. | §8.2 |
| P-S15 | `create_fake_data` | Fusionné avec S-M17. | §6.7 |
| P-S16 | Endpoints legacy ouverts au staff | Superusers en L1b, permissions KYC en L5b. | §4.12 |
| P-S17 | `DELETE` avec corps, réactivation, PATCH de `phone` identique | `POST /users/me/deactivate/`, réactivation par revendication, `phone` identique accepté sans effet. | §4.4 |
| P-S18 | Présence sans position | `can_go_online` exige la position (`missing_for_online`). | §3.1 |
| P-S19 | Photo publique, avis et favoris | `profile_picture` puis `photo` en repli ; `/reviews/public/` et favoris ajoutés au §3.3. | §3.3, §4.13 |
| P-S20 | Gabarit SMS et branche | Ligne WebOTP ; branche `feat/compte-unique-kyc` créée après le commit du lot public. | §5.1, §10 |

#### Écarts trouvés pendant la révision

| # | Écart | Résolution |
|---|---|---|
| X-1 | Le lot public ajoute `handy/migrations/0028_clean_business_plan_features.py` (non suivi) : les numéros de la v1 entraient en collision | Toutes nos migrations sont renumérotées à partir de `0029` (§6.1). |
| X-2 | `entrypoint.sh` crée un superuser avec le mot de passe par défaut `admin` si `CREATE_SUPERUSER=1` | Refus si `DJANGO_ENV=prod` et mot de passe vide, égal à `admin` ou de moins de 16 caractères (L1b). |
| X-3 | Le tableau de bord React `/admin` compte `/bookings/`, `/services/`, `/handymen/` et `/disputes/` grâce au passe-droit `is_staff` | Lecture globale conservée via la permission `view_all_records` (groupes Support et Opérations), pour ne pas casser la page. |
| X-4 | L'app Flutter installée affiche un badge « certifié » à partir de `is_approved` (`artisan.dart:66`) | `is_approved` n'apparaît plus dans aucun payload public à partir de R3 : les anciennes apps n'affichent plus de badge plutôt qu'un badge faux. |
| X-5 | `handy/conftest.py` n'existe pas | Créé en L1a (fixtures et réglages de test). |

---

## Arbitrages

Points acceptés sous une forme différente de celle proposée, ou refusés en partie, avec la justification.

| # | Point | Décision | Justification |
|---|---|---|---|
| A1 | S-M2 : « commande de recalcul en cas de rotation » de la clé HMAC | **Remplacé** par un trousseau de clés versionné : chaque soumission stocke `identity_hmac_key_version`, et la détection calcule le HMAC du nouveau numéro sous **toutes** les versions actives. | Le numéro de pièce n'est jamais stocké en clair : un recalcul est impossible sans le réintroduire. Le trousseau donne le même résultat sans donnée en clair. |
| A2 | S-M3 : SDK pour toutes les captures | **Partiel.** Web : SDK hébergé v12 (chemin nominal, approbation automatique possible). Mobile : capture maison, toujours en revue humaine. | Le SDK Flutter 12 exige Flutter 3.44 ; l'environnement est en 3.38.5 et le dépôt mobile contient du travail non commité. La montée de version est proposée au client (C14). La sécurité n'est pas affaiblie : sans SDK, pas d'approbation automatique. |
| A3 | S-M6 : modification de ses propres groupes « sans un second superuser » | **Simplifié** : personne, superuser compris, ne peut modifier ses propres privilèges ; un autre superuser doit le faire. Chaque changement est journalisé et alerté. | Même effet (deux personnes impliquées) sans construire un circuit d'approbation à deux étapes dans l'admin Django. |
| A4 | S-M7 (3) : « limiter la lecture staff aux vues explicitement listées » | **Équivalent** : la lecture globale exige la permission nommée `view_all_records`, contrôlée dans le mixin partagé. | Garde le tableau de bord React existant fonctionnel (X-3) tout en supprimant le passe-droit d'`is_staff`. |
| A5 | S-S13 : connexion par email réservée aux emails vérifiés | **Partiel** : les emails présents avant la bascule de L3 (`email_login_legacy=True`) restent des identifiants valides ; tout email ajouté ou modifié ensuite doit être vérifié par lien. Sans envoi d'email configuré, l'email reste une simple donnée de contact. | Appliquer la règle aux comptes existants couperait la connexion de tous les utilisateurs actuels qui se connectent par email (contraire à M-M14 et à « ne rien casser »). |
| A6 | S-S9 : nouvel état `awaiting_client_confirmation` | **Partiel** : pas de nouvel état de réservation ; table des transitions par rôle appliquée ; la libération du séquestre est différée (confirmation du client ou 48 h sans litige). | Les apps installées ne connaissent pas un nouvel état et l'afficheraient mal. Le risque visé (libération des fonds par l'artisan seul) est couvert. |
| A7 | S-M14 (d) : ré-authentification faciale | **Par étapes** : avant L10, revue humaine d'une nouvelle capture selfie et liveness comparée au selfie enrôlé ; SmartSelfie Authentication en L10. | Le prestataire n'est pas contractualisé avant L10. La dépublication immédiate est, elle, effective dès L5a. |
| A8 | S-S5 : PDF dans une `iframe sandbox` sans scripts | **Remplacé** : les PDF ne sont jamais rendus dans l'origine du front ; ils sont proposés au téléchargement (pièce jointe). Les pièces d'identité n'acceptent que JPEG et PNG. | La visionneuse PDF de Chromium ne fonctionne pas dans une iframe sandboxée sans scripts. Le téléchargement supprime le risque d'exécution. |
| A9 | S-M16 : SSE-KMS (MinIO KES) ou chiffrement applicatif | **Chiffrement applicatif AES-GCM** par objet, clé versionnée (`KYC_ENCRYPTION_KEYS`). | Pas de nouveau service à opérer ; KES reste possible plus tard sans changement de modèle. |
| A10 | S-M10 : verrou consultatif ou compteurs Redis | **Verrou consultatif PostgreSQL** et journal `OtpSendLog`. | La base est la source de vérité et existe partout (dev, CI, prod) ; Redis reste un cache. |
| A11 | S-M11 : défi anti-bot sur mobile | **Webview** chargeant une page minimale du front web (Turnstile). Sans fournisseur anti-bot (C11 refusé), seuls les plafonds durs s'appliquent. | Turnstile n'a pas de SDK Flutter officiel. |
| A12 | P-M17 : automatisation React | **Smoke Playwright exécuté en local** contre le backend dev (3 parcours), pas en CI. La CI garde `npm run verify` et des garde-fous `grep`. | Le smoke exige un backend et une base ; l'installer en CI demande un service complet et des navigateurs, hors de proportion pour ce chantier. |
| A13 | M-M3 : inverses des migrations d'identité | Inverses **écrits et testés**, mais déclarés destructifs après la première inscription par téléphone ; la politique de production reste « corriger en avant + drapeaux ». | Un rollback qui efface des comptes créés par OTP serait une perte de données. |
| A14 | M-S3 : statut du login en échec | 401 `invalid_credentials` pour les clients qui envoient `X-Tratra-Client` ; 400 (avec `detail`) pour les autres jusqu'en L11. | Le bundle React et l'app installés rejouent la connexion sur un 401, ce qui doublerait les échecs comptés. |
| A15 | M-M10 : drapeau `PUBLICATION_FILTER_ENFORCED` ou déploiement différé | **Déploiement différé** (barrière du train R3). | Évite deux chemins de code en production pour la visibilité publique. |
| A16 | P-S11 : référentiels de lieux et de spécialités | Liste fermée des **communes et villes réelles** (données administratives factuelles, pas inventées), plus « autre localité » en saisie normalisée. Aucune sous-catégorie inventée : spécialités libres `specialties_extra`. | Règle client « aucune donnée fictive ». |
| A17 | S-M8 : récupération des comptes staff | Réinitialisation par SMS désactivée pour le staff ; récupération par un superuser avec vérification d'identité hors ligne (runbook). | Le SMS seul n'est pas un facteur suffisant pour un compte qui ouvre des pièces d'identité. |
| A18 | P-S5 contre S-M11 : quotas IP | **Compromis** : seuil IP souple (20/h, déclenche le défi) et plafond dur élevé (300/h) ; plafonds stricts par numéro, par préfixe et par usage. | Le CGNAT ivoirien fait partager une IP à des milliers d'abonnés ; le pumping vise des plages de numéros. |
| A19 | S-S17 : test de temps | Test marqué `slow`, tolérance de 50 ms sur la médiane ; la garantie principale est structurelle (les deux branches suivent le même chemin de code jusqu'au worker). | Les tests de temps sont instables en CI partagée. |
| A20 | S-M2 : « alerte superviseur » | Notification in-app aux membres du groupe Superviseur et événement Sentry (niveau warning). | Aucun envoi d'email n'existe aujourd'hui ; pas de nouveau canal à inventer. |
| A21 | S-M14 (c) : step-up sur le compte de versement | Les clients qui n'envoient pas `X-Tratra-Client` (apps installées) reçoivent 403 `step_up_required` avec un message de mise à jour, au lieu d'un enregistrement sans contrôle. | L'ancienne app Flutter enregistre le compte de versement sans mot de passe ni OTP (`handyman_service.dart:68`) ; maintenir ce chemin laisserait ouverte la prise de contrôle monétisable. Le refus est explicite, jamais silencieux. |

---

## Table des matières

0. Résumé, décisions clés, décisions client, journal, conventions, failles corrigées
1. Modèle de données
2. Machine d'états KYC et cas d'approbation
3. Prédicat unique « publiable »
4. Contrats API (React et Flutter)
5. Sécurité
6. Migrations, reprise sans perte, runbook
7. Frontend React
8. Application Flutter
9. Stratégie de tests
10. Trains de release et lots

Annexes : A. variables d'environnement, B. codes de motif, C. types de notification, D. catalogue des codes d'erreur, E. risques résiduels et backlog.

---

## 0. Résumé, décisions clés, décisions client

### 0.1 Résumé

Le schéma « un rôle choisi à l'inscription » (`User.user_type`) est remplacé par **un compte unique vérifié par téléphone**. Ce compte peut réserver dès que son numéro est prouvé par OTP. Il devient Handyman en déposant une **candidature** (qui réutilise `HandymanProfile` et crée de vrais `Service`), puis en passant un **KYC** : CNI recto/verso, selfie et liveness, consentement horodaté. Le KYC suit une machine d'états à six états (`draft`, `pending`, `review`, `approved`, `rejected`, `suspended`), dont la source de vérité est `HandymanProfile.kyc_status`. Le booléen historique `is_approved` en devient un miroir dénormalisé, protégé par une contrainte en base et réservé au service KYC.

L'approbation obéit à **quatre cas fermés**. Seule une capture faite par le SDK du prestataire, dont le résultat est relu par un appel authentifié et dont toutes les vérifications ont réussi, peut être approuvée automatiquement. Toute autre approbation est humaine, motivée, précédée de la consultation des preuves, et passe par deux personnes distinctes dès qu'un contrôle prestataire manque ou a échoué. Le badge « Identité vérifiée » n'est accordé que si un prestataire a confirmé la liveness et la comparaison faciale.

Un **prédicat unique « publiable »** décide de toute visibilité publique : catalogue, recherche, featured, matching, présence, statistiques, avis publics, profil public, sitemap, nouvelles réservations. Il exige un KYC approuvé, un profil complet avec au moins un service actif, un compte actif et l'absence de ré-authentification en attente. Un profil suspendu ou révoqué disparaît **dans la même transaction** ; les caches publics sont invalidés à la validation de cette transaction.

Le prestataire recommandé est **Smile ID**. Le webhook n'est qu'un signal : les données de décision viennent d'une relecture authentifiée. Un lot de cadrage en sandbox (**L0**) valide les champs, l'acceptation des captures et la résistance à l'injection avant toute capture côté client. Sans prestataire configuré, le système est en **mode manuel** : toute soumission part en revue humaine et **aucune approbation n'est automatique** ; l'approbation manuelle n'est possible que si le client l'accepte par écrit (C2), à quatre yeux et sans badge d'identité.

L'OTP est généré et haché localement. L'envoi passe par une abstraction SMS (console ou locmem en dev, Orange SMS CI pour le +225, Twilio pour l'international). Les quotas reposent sur un journal d'envois verrouillé, avec des budgets séparés par usage et un défi anti-bot adaptatif.

La refonte corrige aussi les failles existantes : auto-approbation par l'API, fuite du numéro de CNI, IDOR sur les services et leurs images, mot de passe stocké en clair, suppressions en cascade, pouvoirs globaux du staff, auto-arbitrage des litiges, IP falsifiable, MinIO exposé, données de démonstration en production.

Le travail est découpé en **lots commitables** (L0 à L11, plusieurs découpés en sous-lots) regroupés en **six trains de release** avec go/no-go (§10.0).

### 0.2 Décisions clés (architecte)

| # | Décision | Justification courte |
|---|---|---|
| D1 | **Compte créé seulement après OTP réussi.** Le challenge OTP contient le mot de passe déjà haché et les noms. Si le numéro prouvé est porté par un compte legacy (non vérifié ou désactivé), l'utilisateur **choisit** : revendiquer ce compte, ou en créer un nouveau (le numéro est alors libéré de l'ancien). | Un compte non vérifié ne bloque aucun numéro ; la possession étant prouvée, révéler le compte existant ne fuit rien ; aucun second compte n'est créé à l'insu du titulaire. |
| D2 | `User.phone` reste la colonne canonique, **E.164, unique**. La valeur historique est copiée dans `phone_legacy_raw`. **Aucune écriture E.164 avant** `normalize_user_phones --apply`. | Peu de changements de contrat ; pas de doublons sous deux formes. |
| D3 | `USERNAME_FIELD` reste `username`. `PhoneEmailUsernameBackend` reproduit allauth (username et email insensibles à la casse, table `EmailAddress`), essaie une liste bornée de candidats avec un **nombre constant de hachages**, et porte la **garde par compte**, donc couvre aussi `/admin/`. | Rétrocompatibilité ; temps de réponse uniforme ; plus de contournement par l'admin. |
| D4 | Source de vérité KYC : `HandymanProfile.kyc_status`. `is_approved`, `is_published`, `online` et les autres champs « KYC » ne sont écrits **que** par `KycService` et `refresh_publication`, sous verrou ; une sauvegarde ordinaire les exclut. CHECK en base. | Une seule vérité ; plus d'écriture périmée ni d'auto-approbation, même par l'ORM. |
| D5 | Publication **dénormalisée** (`is_published`), recalculée par une seule fonction ; filtre public **défensif** (`is_published`, `kyc_status`, `user.is_active`) ; réconciliation chaque nuit. | Performance et retrait garanti. |
| D6 | Nouveaux modèles KYC (`KycConsent`, `KycSubmission`, `KycDocument`, `KycAuditEvent`, `KycWebhookEvent`). Justificatifs professionnels dans `HandymanProof`, **indépendant** des tentatives. `HandymanDocument` conservé en lecture seule. | L'ancien modèle ne porte ni recto/verso, ni selfie, ni historique ; les justificatifs doivent survivre aux tentatives. |
| D7 | **Append-only réel** : le rôle PostgreSQL d'exécution n'a que `SELECT, INSERT` sur les journaux ; trigger en défense en profondeur ; chaîne de hachage par profil et ancrage quotidien en stockage WORM. | Exigence 8 ; un trigger seul est neutralisable par le propriétaire des tables. |
| D8 | **Deux canaux de capture.** SDK web hébergé Smile ID v12, avec jeton v3 émis par le backend : seul canal éligible à l'approbation automatique. Capture maison (web `getUserMedia`, mobile plugin `camera`) : transmise au prestataire par le backend, **toujours suivie d'une revue humaine**. | L'injection d'images n'est détectable que par les SDK. Flutter 3.38 ne peut pas utiliser le SDK 12 (Arbitrages A2). |
| D9 | Le webhook Smile ID **n'est qu'un signal** (`Job-ID`). Toutes les données de décision viennent d'un **appel authentifié** au prestataire, avec contrôle de `user_id` et `partner_params`. | La signature Smile ne couvre ni le corps ni le job, et elle est rejouable. |
| D10 | Révocation des JWT par **claim `sv`** ; rotation des refresh **atomique** avec détection de réutilisation ; clé de signature dédiée, `aud` et `iss`. | Révocation immédiate et vol de refresh détecté. |
| D11 | **Web : refresh en cookie HttpOnly** (`SameSite=Strict`, `Path=/handy/auth/`), access en mémoire (10 min), CSRF par en-tête personnalisé et contrôle de l'Origin. **Mobile : bearer**, refresh dans `flutter_secure_storage`. | Le refresh n'est plus exfiltrable par XSS ; session partagée entre onglets. |
| D12 | IP client : X-Forwarded-For lu **depuis la droite**, seulement si la requête vient de l'IP fixe de Traefik ; clé de quota IPv6 agrégée au /64. | L'anti-bruteforce actuel est inopérant derrière Traefik. |
| D13 | **Format d'erreur codé** `{"code","detail","fields"?}` pour toute réponse qui porte un code de l'annexe D, quel que soit l'âge de l'endpoint ; `fields` vaut `{champ: [{"code","message"}]}`. Les autres erreurs DRF gardent leur format. | Les clients distinguent les erreurs sans casser l'existant. |
| D14 | `user_type` **déprécié** : conservé, en lecture seule, jamais écrit par les nouveaux parcours. Le signal de création de profil sur `user_type='handyman'` est conservé. | Exigence 2 ; apps installées et tests existants. |
| D15 | **Capacités calculées côté serveur** (`/users/me/ → capabilities`) ; elles remplacent `RoleGuard`, `HOME_BY_ROLE`, `AREA_ROLES` et `Session.role`. Le serveur revérifie toujours. | Un même compte est client et Handyman. |
| D16 | Code nouveau dans des **modules dédiés** (`handy/identity/`, `handy/kyc/`, `handy/api/auth_*`, `kyc_*`, `me_*`, `public_*`). | `views.py` dépasse 1 400 lignes. |
| D17 | **Quatre cas d'approbation fermés** (§2.3) ; quatre yeux pour toute dérogation et toute approbation sans contrôle prestataire ; badge seulement si liveness et visage confirmés par le prestataire. | Exigence 6 sans faux KYC. |
| D18 | **Trains de release** avec go/no-go écrit ; une barrière de déploiement plutôt qu'un double chemin de code. | Aucun parcours cassé entre deux lots. |
| D19 | **Expand/contract au niveau de la base** : DEFAULT durables, contraintes `NOT VALID` puis validées, migrations jouées une fois par un job dédié avec le rôle propriétaire, `RUN_MIGRATIONS=0` en production. | Ancienne et nouvelle image cohabitent ; pas de boucle de redémarrage. |
| D20 | Drapeaux **désactivés par défaut en production** ; le démarrage n'est refusé que si une fonctionnalité **activée** manque de configuration. | Chaque lot se déploie avec le `.env` existant. |
| D21 | **Moindre privilège du staff** : permissions nommées, MFA TOTP, pas d'action sur ses propres dossiers, réservations ou privilèges, pas de passe-droit `is_staff`. | Exigence 8 (RBAC) et sécurité des preuves. |
| D22 | **OTP** : journal `OtpSendLog` sous verrou consultatif, budgets séparés par famille d'usage avec réserve pour les comptes existants, plafonds par numéro, préfixe et IP, défi anti-bot adaptatif. | Anti-pumping et anti-verrouillage ciblé. |

### 0.3 Décisions à faire valider par le client

Chaque point a une recommandation par défaut. Une décision marquée **bloquante** n'est jamais appliquée par défaut en production : le code l'implémente derrière un drapeau désactivé, et le go/no-go du train concerné exige la décision écrite, consignée au journal (§0.4).

| # | Question | Défaut proposé | Bloquante pour | Conséquence ou alternative |
|---|---|---|---|---|
| C1 | Prestataire KYC et approbation automatique | **Smile ID** Document Verification v3 (CNI CI recto/verso, liveness, comparaison faciale). Approbation automatique **uniquement** pour un résultat `clear` capturé par le SDK web, toutes vérifications réussies, sans drapeau interne. | Mise en production du mode prestataire (L10) | Contrat et clés sandbox puis production. Second choix : Sumsub (CNI CI non confirmée). |
| C2 | Approbation humaine **sans** prestataire | **Interdite** (`KYC_MANUAL_APPROVAL_ALLOWED=false`). Si le client l'accepte : quatre yeux, permission `kyc_approve_manual`, `verification_level=manual`, **pas** de badge « Identité vérifiée » mais la mention « Pièce contrôlée par Tratra », revérification par le prestataire dès qu'il est branché. | **R3 en production** si L10 n'est pas prêt | Sans C2 ni L10, R3 n'est pas déployé en production (§10.0) : sinon le catalogue se viderait. |
| C3 | Artisans legacy `is_approved=True` et approbations | **Gel des nouvelles approbations dès R1.** Au déploiement de R3 : legacy dépubliés, placés en revue « legacy » puis invités à refaire une vérification complète. **Jamais d'approbation automatique.** | R1 (gel) et R3 (dépublication) | Le catalogue de production peut se réduire jusqu'à ce que les artisans aient refait leur KYC. |
| C4 | Téléphone prouvé avant de réserver | Drapeau `BOOKING_REQUIRES_PHONE_VERIFIED` **faux** ; activé après R2, la publication des apps (R4a) et un SMS de production actif, avec une période de grâce pour les anciennes apps. | Activation du drapeau | L'ancien `is_verified=True` ne vaut pas preuve (l'OTP était un stub). |
| C5 | Fournisseurs SMS et pays | Orange SMS API CI pour le +225 (sender « Tratra », environ 3 semaines d'enregistrement), Twilio pour l'international. Pays : CI, UEMOA et CEDEAO (SN, ML, BF, BJ, TG, NE, GN, GH, NG), FR, BE, CA, US. Budget journalier CI 5 000 (dont 20 % réservés aux comptes existants), autres 300. | `PHONE_SIGNUP_ENABLED` | Pays hors liste : `unsupported_country`. |
| C6 | Juridique ARTCI (biométrie, transfert hors CEDEAO), textes CGU, confidentialité et consentement KYC, durée de conservation | **Aucun texte inventé.** Les textes versionnés sont fournis ou validés par le juriste. Sans eux, `PHONE_SIGNUP_ENABLED` et `KYC_SUBMISSIONS_ENABLED` sont refusés au démarrage. Aucune collecte de selfie ou de liveness en production sans `KYC_LEGAL_APPROVAL_REF`. Conservation : 3 ans après la dernière décision (pièces soumises), 30 jours (brouillons). | R2 (inscription) et R3 (KYC) | À confirmer par écrit. |
| C7 | Pièces acceptées | CNI ivoirienne uniquement (recto et verso). | — | Option : passeport ou carte de résident via `KYC_ALLOWED_ID_TYPES`. |
| C8 | Réservations vers un artisan suspendu ou révoqué | Conservées ; le client est notifié et peut annuler sans frais si le retrait est **postérieur** à la réservation ; paiements en ligne et versements bloqués pendant le retrait. | — | Alternative : annulation automatique (déconseillée). |
| C9 | Dépôt Flutter (un seul commit, environ 56 fichiers non commités) | Commit « baseline » du travail existant sur une branche dédiée, **uniquement avec l'accord explicite de l'utilisateur dans la conversation**. | **L8 et L9** | Sans accord, les lots Flutter ne démarrent pas ; rien n'est commité dans ce dépôt. |
| C10 | Inscription legacy `POST /handy/users/` | Maintenue et durcie jusqu'à l'adoption des nouvelles apps, puis 410 (`LEGACY_SIGNUP_ENABLED=false`). | L11 | Les très anciennes apps devront être mises à jour. |
| C11 | Défi anti-bot | **Cloudflare Turnstile**, déclenché seulement au-delà de seuils de risque. | — | Sans Turnstile : plafonds durs seuls (plus de 429 en cas d'attaque). Tiers à mentionner dans la politique de confidentialité. |
| C12 | Libération du séquestre quand l'artisan déclare la fin | Sur confirmation du client, ou automatiquement 48 h après sans litige. | R1 | Alternative : libération immédiate (actuel), déconseillée. |
| C13 | Comptes staff | MFA TOTP obligatoire ; `is_staff` retiré des comptes qui ne sont pas des employés (donnée dev : l'artisan id 8) ; un employé n'a pas de profil Handyman. | R2 (MFA), R3 (preuves) | — |
| C14 | Montée de version Flutter (3.44) pour le SDK mobile | **Non** pendant ce chantier : captures mobiles en revue humaine. | — | Option ultérieure : approbation automatique aussi sur mobile. |

### 0.4 Journal des décisions

- Fichier `docs/decisions/journal.md` dans le dépôt backend, une entrée datée par décision : identifiant (C1…), décision, auteur côté client, date, référence écrite (email, compte rendu), trains concernés.
- Le go/no-go d'un train (§10.0) cite les entrées du journal dont il dépend. Une décision absente vaut « non ».
- Les décisions d'architecture ultérieures (écart à ce document) y sont aussi consignées.

### 0.5 Conventions

- **Python 3.9 en local** (Docker et CI en 3.12) : pas de `match`, pas d'annotations `X | None` évaluées à l'exécution, pas de `zip(strict=)`, pas de gestionnaires de contexte parenthésés, pas de `dataclass(slots=True)`. `typing.Optional`, `List`, `Dict`, `Tuple` ; `from __future__ import annotations` permis.
- Django 4.2 : `CheckConstraint(check=...)` ; `UniqueConstraint(condition=...)` sur PostgreSQL ; pas de `db_default` ni de `nulls_distinct` (Django 5) : les DEFAULT en base passent par `RunSQL` (§6.1).
- **Valeurs d'état en minuscules** (`draft` … `suspended`), qui correspondent aux états DRAFT … SUSPENDED du brief.
- Routes préfixées par `/handy/` ; nouvelles routes explicites déclarées **avant** `include(router.urls)`.
- Dates ISO 8601 avec fuseau ; montants décimaux en chaînes (`"5000.00"`).
- Permissions exposées aux clients **sans préfixe** (`kyc_decide`), codenames Django `handy.kyc_decide`.
- Nouveaux modules backend :

```
handy/identity/   phones.py otp.py otp_quota.py tokens.py authentication.py backends.py client_ip.py
                  guards.py devices.py sessions.py events.py capabilities.py accounts.py claims.py
                  antibot.py mfa.py context.py legal.py logging.py
                  sms/{__init__,base,console,locmem,orange_ci,twilio,router}.py
handy/kyc/        states.py service.py approval.py publication.py evidence.py crypto.py consent.py
                  permissions.py audit.py reasons.py duplicates.py legacy_mapping.py tasks.py
                  providers/{__init__,base,manual,smile_id}.py
handy/media/      sanitize.py (réencodage des images publiques)
handy/geo/        communes_ci.py (référentiel factuel des communes et villes)
handy/api/        errors.py auth_serializers.py auth_views.py auth_urls.py me_serializers.py me_views.py
                  kyc_serializers.py kyc_views.py kyc_admin_views.py kyc_urls.py public_views.py
handy/legal/      terms/<version>.fr.md privacy/<version>.fr.md kyc_consent/<version>.fr.md (fournis par le client)
handy/management/commands/  identity_report.py normalize_user_phones.py grant_role.py staff_mfa_enroll.py
                  kyc_legacy_report.py kyc_legacy_request_resubmission.py kyc_reconcile_publication.py
                  kyc_verify_audit_chain.py kyc_reverify_manual.py purge_otp_challenges.py db_validate_constraints.py
handy/conftest.py (fixtures et réglages de test partagés)
docs/api-contracts/*.json, docs/api-contracts/copy.fr.json, docs/decisions/journal.md
deploy/sql/{roles.sql,grants.sql}
```

- Les nouveaux modèles sont ajoutés **à la fin de `handy/models.py`**, dans une section délimitée.
- Un callable référencé par une migration (`default_user_preferences`, `kyc_evidence_upload_path`, `private_kyc_upload_path`, `proof_upload_path`) n'est **jamais** renommé ni supprimé.

### 0.6 Failles existantes corrigées (référence)

| Faille | Localisation | Correctif | Lot |
|---|---|---|---|
| Auto-approbation par `PATCH /handymen/{id}/ {is_approved:true}`, création ou réattribution d'un profil pour autrui | `serializers.py:211-235`, `views.py:352-365` | Champs sensibles en lecture seule, queryset du propriétaire, création et suppression en 405 ; champs KYC réservés (D4) | L1a, L5a |
| Numéro de CNI, licence, assurance, position exacte et email des artisans lisibles par tout compte connecté | `HandymanProfileViewSet` | Liste limitée au propriétaire ; un tiers reçoit 404 | L1a |
| Création d'un service au nom d'autrui | `ServiceViewSet` sans `perform_create` | `handyman` forcé à `request.user`, profil Handyman requis | L1a |
| IDOR sur `ServiceImage`, déplacement d'image vers le service d'un concurrent | `views.py:568-573` | Queryset du propriétaire, `service` en lecture seule après création | L1a |
| EXIF (GPS) dans les images publiques, `image_url` arbitraire | `ServiceImage`, `Service.banner`, médias d'avis | Réencodage Pillow, hôtes autorisés | L1a |
| `PATCH /users/{id}/ {"password"}` stocke le mot de passe en clair | `UserSerializer` | 400 ; endpoint dédié en L3a | L1a |
| `DELETE /users/{id}/` supprime en CASCADE | `ModelViewSet` | 405, puis désactivation (L3b) ; PROTECT étendu | L1a |
| Action admin `approve_profiles` sans contrôle | `admin.py:160` | Supprimée ; gel des approbations jusqu'à R3 | L1b |
| Escalade de privilèges dans l'admin Django | `admin.py:69-77` | Champs de privilège réservés aux superusers, journalisés | L1b |
| Pouvoirs globaux d'`is_staff` (lecture et écriture de tout, résolution de ses propres litiges) | `views.py:64-111`, `views.py:824` | Permissions nommées, `self_dealing_forbidden` | L1b |
| Artisan staff qui révise ses propres documents | `views.py:1035`, donnée dev user 8 | Revue legacy réservée aux superusers non concernés ; RBAC KYC en L5b | L1b, L5b |
| Erreur 500 dans l'admin sur un document KYC | `admin.py:80-94,165-190` | Aucun widget ni lien de fichier dans l'admin | L1b |
| `django_cleanup` efface une preuve | `INSTALLED_APPS` | `@cleanup.ignore` sur `HandymanDocument` et les modèles KYC | L1b, L5a |
| `create_fake_data` crée un superuser `password123` et de faux artisans approuvés | `create_fake_data.py:247,283-292` | Refus hors dev, aucun profil approuvé | L1b, L5a |
| Libération du séquestre par l'artisan seul | `models.py:535-590` | Transitions par rôle, libération différée | L1c |
| `last_name` complet et `is_verified` exposés publiquement | `PublicUserMiniSerializer` | `id`, `first_name`, `display_name` uniquement | L1a |
| IP falsifiable ou unique (Traefik) ; axes bloque tout le monde | `base.py:440-446`, `middleware.py:16-22` | §5.3 | L2 |
| Pas de `CACHES` partagé | `base.py` | Redis (§5.4) | L2 |
| Sentry envoie les variables locales | `base.py` | §5.10 | L2 |
| Console MinIO et API S3 publiées, identifiants root partagés | `docker-compose.yml:47-63` | §5.9 | L2 |
| `validate_password` jamais appelé | `UserSerializer.create` | Appelé partout | L1a, L3a |
| OTP en clair, sans limite, journalisé, renvoyé si DEBUG | `models.py:995-1017`, `views.py:1081-1111`, `tasks.py:32-36` | §5.1 | L3a |
| Compte de versement modifiable sans contrôle | `views.py:1200` | Mot de passe, OTP et retenue de 72 h | L3b |
| Catalogue public incluant des artisans non approuvés et des services inactifs | filtres publics | Prédicat « publiable » (§3) | L5a |
| Réservation vers n'importe quel artisan ou service | `BookingCreateSerializer` | Cohérence (L1a), publication (L5a) | L1a, L5a |

---

## 1. Modèle de données

### 1.1 `User` (`handy/models.py:24-71`)

| Champ | Avant | Après | Remarques |
|---|---|---|---|
| `email` | `EmailField(unique=True)` | `EmailField(unique=True, null=True, blank=True)` | `''` devient NULL (0033). Unicité **insensible à la casse** contrôlée par les serializers dès L3a, puis par un index fonctionnel en L11 (§6.3). Simple donnée de contact tant qu'il n'est pas vérifié ou « legacy » (§4.4). |
| `email_verified_at` | — | `DateTimeField(null=True, blank=True)` | Posé par le lien de vérification. |
| `email_login_legacy` | — | `BooleanField(default=False)`, DEFAULT en base `false` | Mis à `true` par 0033 pour tout compte qui a déjà un email : cet email reste un identifiant de connexion (Arbitrages A5). Remis à `false` dès que l'email change. |
| `email_pending` | — | `EmailField(null=True, blank=True)` | Nouvel email en attente de vérification par lien. |
| `phone` | `CharField(20, unique, null, blank, db_index)` | **Inchangé en schéma**, sémantique **E.164** (`^\+[1-9]\d{6,14}$`) | Normalisé par `handy/identity/phones.normalize()` dans les serializers, le formulaire admin et la commande `normalize_user_phones` ; **jamais** dans `save()`. CHECK E.164 ajoutée en L11 (0040). |
| `phone_legacy_raw` | — | `CharField(32, null=True, blank=True)` | Valeur historique (audit, rollback). Jamais exposée, jamais utilisée pour se connecter. |
| `phone_verified_at` | — | `DateTimeField(null=True, blank=True, db_index=True)` | Preuve de possession (OTP). |
| `is_verified` | `BooleanField` | Conservé, **déprécié** | Jamais lu par la logique ; écrit à `True` en miroir d'une vérification de téléphone ; **plus exposé par l'API** (§3.5). Suppression de colonne au backlog. |
| `user_type` | `CharField(..., default='client')` | Conservé, **déprécié**, lecture seule | Nouveaux comptes : `'client'`. Aucune permission ne s'appuie dessus. |
| `commune`, `quartier` | — | `CharField(100, null=True, blank=True)` | Adresse ivoirienne ; `commune` validée contre le référentiel `handy/geo/communes_ci.py` (§4.7). |
| `preferences` | — | `JSONField(default=default_user_preferences, blank=True)`, DEFAULT en base | Schéma **fermé** : `{"notifications": {"sms": bool}}` (défaut `true`). C'est la seule préférence branchée (SMS KYC et SMS d'arrivée imminente). Toute nouvelle clé n'est ajoutée qu'avec son branchement. |
| `session_version` | — | `PositiveIntegerField(default=1)`, DEFAULT en base `1` | Claim `sv` des JWT. |
| `terms_accepted_at`, `terms_version`, `privacy_version` | — | `DateTimeField(null=True)`, `CharField(32, default='')` ×2, DEFAULT en base `''` | Versions des textes acceptés à l'inscription (§4.13). |
| `deactivated_at` | — | `DateTimeField(null=True, blank=True)` | Désactivation au lieu de suppression. |
| `payout_hold_until` | — | `DateTimeField(null=True, blank=True)` | Retenue des versements (§4.6). |
| `profile_picture` | `ImageField('profile_pics/')` | Inchangé | **Photo publique unique** ; `HandymanProfile.photo` sert de repli en lecture. |

Contraintes :
- `CheckConstraint(check=Q(phone_verified_at__isnull=True) | Q(phone__isnull=False), name="user_verified_phone_requires_phone")` (0034).
- `user_phone_e164` : ajoutée à `Meta` **seulement** avec 0040 (L11), en `NOT VALID` puis validée.
- Index unique fonctionnel `user_email_ci_unique` sur `Lower('email')` (condition `email IS NOT NULL`) : 0041 (L11), `CREATE UNIQUE INDEX CONCURRENTLY`.

`User.save()` convertit uniquement `email=''` et `phone=''` en `None`. Le formulaire `CustomUserAdmin` normalise `phone` dans `clean_phone` et l'email en minuscules dans `clean_email`.

Instantané pour les signaux : `User.from_db()` mémorise `is_active`, `first_name`, `last_name` et `phone_verified_at` (en ignorant `get_deferred_fields()`) ; le `.only()` de `UserViewSet` (`views.py:336`) est retiré.

Username des nouveaux comptes : `handy/identity/accounts.generate_username()` produit `"u" + secrets.token_hex(5)`, cinq essais en cas de collision. Jamais affiché publiquement.

### 1.2 `OTPCode` (extension) et `SignupClaim` (nouveau)

```python
class OTPCode(models.Model):
    PURPOSES = [
        ("signup", "Inscription"), ("phone_verify", "Vérification du téléphone"),
        ("password_reset", "Réinitialisation du mot de passe"), ("phone_change", "Changement de téléphone"),
        ("payout_change", "Confirmation du compte de versement"),
        ("login", "(legacy) Connexion"), ("phone", "(legacy) Vérification téléphone"),
    ]
    BUCKET_OF = {"signup": "signup", "password_reset": "reset", "phone_verify": "phone",
                 "phone_change": "phone", "phone": "phone", "login": "phone", "payout_change": "stepup"}
    challenge_id = models.UUIDField(default=uuid4, unique=True, editable=False)   # état final (0034)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name="otp_codes")
    phone_e164 = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    country_code = models.CharField(max_length=2, blank=True, default="")
    purpose = models.CharField(max_length=20, choices=PURPOSES, db_index=True)
    code = models.CharField(max_length=6, null=True, blank=True)            # LEGACY : plus jamais écrit
    code_hash = models.CharField(max_length=64, blank=True, default="")     # HMAC-SHA256 hex
    is_decoy = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    send_count = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    next_send_allowed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()                 # recalculé par le worker à l'envoi effectif
    challenge_expires_at = models.DateTimeField(null=True, blank=True)   # fin de vie (30 min)
    code_verified_at = models.DateTimeField(null=True, blank=True)       # code juste, action non terminée (§4.3)
    consumed_at = models.DateTimeField(null=True, blank=True)
    used = models.BooleanField(default=False)           # legacy, miroir de consumed_at
    ip = models.GenericIPAddressField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["user", "used", "-created_at"]),
                   models.Index(fields=["phone_e164", "purpose", "-created_at"])]
        constraints = [models.CheckConstraint(check=Q(attempts__lte=F("max_attempts")),
                                              name="otp_attempts_le_max")]          # 0034
```

- `payload` : `signup` → `{"first_name","last_name","password_hash","terms_version","privacy_version"}` ; `phone_change` → `{"new_phone"}` ; `payout_change` → empreinte du compte demandé (`sha256` du JSON canonique) ; autres → `{}`. Vidé à la consommation ou à l'expiration.
- `code` perd son index et devient nullable ; les codes en clair existants sont neutralisés (0033).
- `is_valid()` est conservée : `consumed_at is None and now <= expires_at and attempts < max_attempts`.
- `issue()` est supprimée, remplacée par `OtpService` (§5.1). Tests `test_sprint6.py:65,84` migrés.

```python
class SignupClaim(models.Model):          # revendication d'un compte legacy après OTP réussi (§4.1)
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    phone_e164 = models.CharField(max_length=20)
    legacy_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    payload = models.JSONField(default=dict)     # copie du payload signup (mot de passe haché, noms, versions)
    attempts = models.PositiveSmallIntegerField(default=0)      # mots de passe legacy essayés (max 5)
    expires_at = models.DateTimeField()                          # 10 min
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(max_length=16, blank=True, default="")   # claimed|recovered|created_new|expired
    created_at = models.DateTimeField(auto_now_add=True)
```

Le jeton remis au client est `signing.dumps({"claim": id}, salt="signup-claim")`. `payload` est vidé à la résolution ou à l'expiration (purge horaire).

### 1.3 `OtpSendLog` (nouveau)

Une ligne par SMS **réellement émis ou réservé**, leurres et SMS d'information compris. C'est la seule base de calcul des quotas (§5.1).

```python
class OtpSendLog(models.Model):
    BUCKETS = [("signup","signup"),("reset","reset"),("phone","phone"),("stepup","stepup"),("info","info")]
    STATUS = [("reserved","réservé"),("sent","envoyé"),("failed","échec"),("skipped","non envoyé")]
    challenge = models.ForeignKey(OTPCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    phone_e164 = models.CharField(max_length=20)
    national_prefix = models.CharField(max_length=12)     # "+225" + 6 premiers chiffres nationaux
    country_code = models.CharField(max_length=2)
    ip_key = models.CharField(max_length=64)               # IPv4, ou préfixe /64 en IPv6
    ip_key_day = models.CharField(max_length=64)           # IPv4, ou préfixe /48
    bucket = models.CharField(max_length=8, choices=BUCKETS)
    existing_account = models.BooleanField(default=False)  # compte réel existant (réserve de budget)
    is_decoy = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATUS, default="reserved")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        indexes = [models.Index(fields=["phone_e164", "bucket", "created_at"]),
                   models.Index(fields=["ip_key", "created_at"]), models.Index(fields=["ip_key_day", "created_at"]),
                   models.Index(fields=["national_prefix", "created_at"]),
                   models.Index(fields=["country_code", "bucket", "created_at"])]
```

Rétention : 30 jours (purge quotidienne). Les numéros y sont nécessaires au comptage ; la table n'est exposée par aucune API.

### 1.4 `AccountEvent` (nouveau en L1b, append-only)

```python
class AccountEvent(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name="account_events")
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name="+")
    event_type = models.CharField(max_length=40, choices=ACCOUNT_EVENT_TYPES, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)   # téléphones MASQUÉS ; jamais de code, de mot de passe ni de jeton
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
```

Types (liste fermée, `handy/identity/events.py`) :
- L1b : `privilege_granted`, `privilege_revoked`, `staff_flag_changed`, `legacy_evidence_viewed`, `self_dealing_blocked` ;
- L3a : `signup_completed`, `account_claimed`, `account_recovered`, `phone_verified`, `phone_released`, `phone_normalized`, `password_reset`, `sessions_revoked`, `refresh_reuse_detected`, `account_locked`, `rollback_placeholder_email` ;
- L3b : `phone_changed`, `password_changed`, `deactivated`, `reactivated`, `email_change_requested`, `email_verified`, `payout_account_changed`, `payout_hold_set`, `mfa_enrolled`, `mfa_verified`, `admin_user_edit`.

Les changements de privilèges sont captés par les signaux `m2m_changed` sur `User.groups` et `User.user_permissions`, et `pre_save` sur `is_staff` et `is_superuser`. L'acteur vient de `handy/identity/context.py` (variable de contexte posée par le middleware `RequestContextMiddleware`) ; sans requête (commande), l'acteur est NULL et `metadata.source` vaut le nom de la commande. Chacun de ces événements émet un avertissement Sentry.

### 1.5 Candidature Handyman : `HandymanProfile` et modèles liés

On **réutilise `HandymanProfile`** (`models.py:76-196`). Champs ajoutés (0035) :

| Champ | Type | Rôle |
|---|---|---|
| `kyc_status` | `CharField(16, choices=KycStatus, default='draft', db_index=True)`, DEFAULT en base | **Source de vérité** KYC (§2). |
| `kyc_status_changed_at` | `DateTimeField(null=True)` | |
| `kyc_subject_id` | `UUIDField(default=uuid4, unique=True, editable=False)` ; DEFAULT `gen_random_uuid()` en base | Identifiant opaque envoyé au prestataire (`user_id`). Ajout en trois temps (§6.1). |
| `current_submission` | `ForeignKey('KycSubmission', on_delete=PROTECT, null=True, related_name='+')` | Dernière tentative pertinente. |
| `identity_verified_at` | `DateTimeField(null=True)` | Date de la dernière approbation. |
| `verification_level` | `CharField(20, blank=True, default='')`, valeurs `provider`, `provider_reviewed`, `manual`, `sandbox`, `seed` | Détermine le badge (§3.5). |
| `is_published`, `published_at` | `BooleanField(default=False, db_index=True)`, `DateTimeField(null=True)` | Publication dénormalisée (§3). |
| `status_reason_code`, `status_message` | `CharField(40)`, `CharField(500)`, défaut `''` | Dernier motif et message à l'artisan. |
| `resubmission_allowed` | `BooleanField(default=True)` | |
| `status_before_suspension` | `CharField(16, default='')` | Réhabilitation. |
| `withdrawn_at` | `DateTimeField(null=True)` | Dernier retrait depuis `approved` (T11, T14) ; effacé par la réhabilitation. Sert à la gratuité d'annulation (§2.4). |
| `reauth_required_at`, `reauth_reason` | `DateTimeField(null=True)`, `CharField(40, default='')` | Ré-authentification exigée (§2.7). |
| `funds_frozen` | `BooleanField(default=False)` | Gel des versements après révocation ou motif de fraude (§2.4). |
| `application_submitted_at` | `DateTimeField(null=True)` | Première **soumission KYC** (et non le premier enregistrement du formulaire). |
| `public_location` | `PointField(null=True, srid=4326)` | Centre de la cellule de `PUBLIC_LOCATION_GRID_DEG` (0,01°, environ 1,1 km) contenant `location` ; seul point utilisé par les calculs publics. |
| `specialties_extra` | `JSONField(default=list, blank=True)` | Au plus 10 spécialités libres de 40 caractères (sans référentiel inventé). |
| `legacy_is_approved` | `BooleanField(null=True)` | Instantané avant la reprise. |
| `legacy_flags` | `JSONField(default=list, blank=True)` | Par exemple `["legacy_approved", "legacy_slots_archived"]`. |

**Champs réservés au KYC** (`KYC_OWNED_FIELDS`) : `kyc_status`, `kyc_status_changed_at`, `is_approved`, `is_published`, `published_at`, `online`, `identity_verified_at`, `verification_level`, `current_submission`, `status_reason_code`, `status_message`, `resubmission_allowed`, `status_before_suspension`, `withdrawn_at`, `reauth_required_at`, `reauth_reason`, `funds_frozen`, `legacy_is_approved`, `legacy_flags`.

```python
def save(self, *args, **kwargs):
    uf = kwargs.get("update_fields")
    if getattr(self, "_kyc_write", False):          # posé par KycService, refresh_publication, set_presence
        self.is_approved = (self.kyc_status == KycStatus.APPROVED)
        if self.kyc_status != KycStatus.APPROVED:
            self.is_published = False
        if not self.is_published:
            self.online = False
        if uf is not None:
            kwargs["update_fields"] = sorted(set(uf) | {"is_approved", "is_published", "online"})
    elif not self._state.adding:
        if uf is None:                               # sauvegarde complète : on n'écrit JAMAIS les champs KYC
            kwargs["update_fields"] = [f.name for f in self._meta.concrete_fields
                                       if not f.primary_key and f.name not in KYC_OWNED_FIELDS]
        elif set(uf) & KYC_OWNED_FIELDS:
            raise KycFieldWriteForbidden(sorted(set(uf) & KYC_OWNED_FIELDS))
    elif any(getattr(self, f) != DEFAULTS[f] for f in KYC_CREATE_GUARDED):
        raise KycFieldWriteForbidden(["création avec un état KYC non initial"])
    if uf is None or "location" in (uf or []):
        self.public_location = snap_to_grid(self.location)    # ajouté à update_fields si fourni
    super().save(*args, **kwargs)
```

Conséquences : `refresh_quality_score()` (`save(update_fields=['quality_score'])`) sur une instance périmée ne peut plus republier un profil suspendu ; une sauvegarde complète par l'admin ou par `PATCH` n'écrit jamais l'état KYC ; les `.update()` de l'ORM restent possibles pour du code interne et sont rattrapés par la réconciliation (§2.8) et le filtre défensif.

Champs du formulaire (exigence 5). Les règles ne s'appliquent qu'aux champs **présents dans la requête** ; un profil legacy qui ne les respecte pas reste enregistrable tant qu'il ne modifie pas le champ fautif, et l'écart est exposé dans `legacy_constraints_violations` (§4.7).

| Exigence | Stockage | Règles |
|---|---|---|
| Métiers | `skills` (`ServiceCategory` avec `parent IS NULL`) | 1 à 3, catégories actives. |
| Spécialités | `skills` avec `parent` parmi les métiers choisis ; `specialties_extra` | 0 à 10 ; `specialty_without_trade` sinon. L'étape est sautée si aucun métier choisi n'a de sous-catégorie. |
| Expérience | `experience_years` | 0 à 60, obligatoire (0 = moins d'un an). |
| Zone | `commune` (référentiel factuel `handy/geo/communes_ci.py` : communes du District d'Abidjan et chefs-lieux de région, extensible par le client ; normalisation casse et accents), `quartier`, `ServiceArea.radius_km` (1 à 50, défaut 10), `location` facultative | Position exacte jamais publique. |
| Description | `bio` | 30 à 2 000 caractères. |
| Tarifs | `hourly_rate`, `daily_rate`, `travel_fee` (XOF, ≥ 0) | Au moins un tarif horaire ou journalier > 0. |
| Justificatifs | `HandymanProof` (§1.6) | 0 à 5 actifs. |
| Disponibilité | `AvailabilitySlot` | Au moins 1 créneau, au plus 3 par jour, sans chevauchement, `end > start`. Le JSON `availability` est exposé en lecture seule (`legacy_availability`) pour préremplir la grille. |
| **Services** | `Service` (existant, `handyman = user`) | Au moins un service actif dont la catégorie est un métier choisi ou l'une de ses sous-catégories ; titre, `price_type`, prix et durée obligatoires à la création par le parcours de candidature. |

Contraintes (ajoutées en `NOT VALID` puis validées, §6.1) :
- `AvailabilitySlot` : `slot_end_after_start` ; index `(handyman, weekday)`.
- `ServiceArea` : `area_radius_bounds` (1 à 100).
- `HandymanProfile` : `hm_is_approved_mirrors_kyc`, `hm_published_requires_approved`, `hm_online_requires_published` ; index `(is_published, kyc_status)`.

Champs `cni_number`, `license_number`, `insurance_info` : legacy, jamais écrits par l'API, jamais exposés hors du détail admin (masqués). Purge au backlog.

Managers : `HandymanProfile.objects = HandymanProfileQuerySet.as_manager()` (`.publishable()`), `Service.objects = ServiceQuerySet.as_manager()` (`.public()`).

### 1.6 `HandymanProof` (nouveau, L6)

Justificatifs professionnels, **indépendants des tentatives KYC** : ils survivent aux resoumissions et restent modifiables après approbation.

```python
@cleanup.ignore
class HandymanProof(models.Model):
    TYPES = [("certification","Certification"),("work_certificate","Certificat de travail"),("casier","Casier judiciaire"),
             ("insurance","Assurance"),("license","Licence"),("other","Autre")]
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    profile = models.ForeignKey(HandymanProfile, on_delete=models.PROTECT, related_name="proofs")
    proof_type = models.CharField(max_length=32, choices=TYPES)
    title = models.CharField(max_length=120, blank=True, default="")
    file = models.FileField(upload_to=proof_upload_path, storage=KycPrivateStorage(), max_length=255)
    content_type = models.CharField(max_length=64)          # application/pdf, image/jpeg, image/png
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    encryption = models.JSONField(default=dict)              # §5.9
    status = models.CharField(max_length=10, default="pending")   # pending|accepted|rejected
    reviewed_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True, default="")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
```

Jamais publics. Un justificatif n'est pas une condition de publication ; sa revue est tracée (`proof_reviewed`).

### 1.7 RBAC et comptes staff

**Permissions** (codenames `handy.*`) :

| Codename | Porté par (`Meta.permissions`) | Lot | Rôle |
|---|---|---|---|
| `view_all_records` | `Booking` | L1b | Lecture globale des réservations, paiements, litiges, versements, services et profils (tableau de bord `/admin`). |
| `resolve_dispute` | `Dispute` | L1b | Résoudre un litige. |
| `manage_payouts` | `Payout` | L1b | Actions staff sur les versements. |
| `kyc_view_queue`, `kyc_view_evidence`, `kyc_decide`, `kyc_approve_manual`, `kyc_suspend`, `kyc_view_audit`, `kyc_override` | `KycSubmission` | L5a | File, preuves, décision, approbation sans prestataire, suspension et réhabilitation, historique, dérogations Superviseur (doublon, échec prestataire, bris de glace). |

**Groupes** (migrations de données, recette `create_permissions` du §6.1) :

| Groupe | Permissions | Lot |
|---|---|---|
| `Opérations` | `view_all_records`, `resolve_dispute`, `manage_payouts` | L1b |
| `Support` | `view_all_records` ; plus `kyc_view_queue`, `kyc_view_audit` en L5b (aucune pièce) | L1b, L5b |
| `KYC – Reviewer` | `kyc_view_queue`, `kyc_view_evidence`, `kyc_decide`, `kyc_view_audit` | L5b |
| `KYC – Superviseur` | les sept permissions `kyc_*` | L5b |

**Règles transverses** (`handy/kyc/permissions.py`, `handy/identity/guards.py`, revérifiées dans les services) :
1. `is_staff` seul n'ouvre **aucun** accès API. Le passe-droit `is_staff` de `IsOwnerOrAdmin` et `OwnerScopedQuerysetMixin` (`views.py:64-111`) est remplacé par `user.has_perm("handy.view_all_records")` **en lecture seulement** ; toute écriture sur l'objet d'autrui exige une permission nommée. `IsAdminUser` est remplacé par `HasStaffPerm("handy.<perm>")`.
2. **Aucune action sur soi** : 403 `self_review_forbidden` sur son propre dossier KYC ; 403 `self_dealing_forbidden` sur une réservation, un paiement, un litige ou un versement dont l'agent est partie (client ou artisan) ; personne, superuser compris, ne modifie ses propres privilèges.
3. Routes `/handy/admin/*` : permission nommée **et** MFA (claim `amr` contenant `otp`) si `STAFF_MFA_REQUIRED` (vrai en production à partir de R2) ; sinon 403 `mfa_required`.
4. Un compte staff ne peut pas avoir de `HandymanProfile` : `grant_role` refuse, le formulaire admin refuse `is_staff` pour un tel compte, `identity_report` liste les violations (C13).
5. Le staff ne modifie plus un autre compte par l'API (`PATCH /users/{id}/` d'autrui : 403) ; les modifications passent par l'admin Django (journal `LogEntry` et `AccountEvent admin_user_edit`).
6. Admin Django : pour un non-superuser, `groups`, `is_staff`, `is_superuser` et `user_permissions` sont désactivés ; pour **soi-même**, ils le sont aussi pour un superuser ; `GroupAdmin` est réservé aux superusers ; la suppression d'un `User` est réservée aux superusers (action « désactiver » proposée) ; les modèles KYC et `HandymanDocument` sont en lecture seule, **sans aucun lien vers un fichier**. L'admin est servi sous `ADMIN_URL` (non devinable en production) par `OTPAdminSite` (django-otp).
7. **MFA** (L3b) : TOTP django-otp. L'enrôlement est fait par un superuser (`staff_mfa_enroll --user <id>` affiche une seule fois l'URI `otpauth://`). `POST /handy/auth/mfa/verify/ {"code"}` échange la session courante contre des jetons portant `amr=["pwd","otp"]`. Refresh staff limité à 12 h. Réinitialisation du mot de passe par SMS désactivée pour le staff (leurre, puis procédure superuser, Arbitrages A17).
8. Commande `grant_role --user <id> --role ops|support|reviewer|supervisor [--revoke]` : superuser seulement, refuse un compte avec profil Handyman ou sans MFA enrôlé (en production), écrit `privilege_granted` ou `privilege_revoked`.
9. Recertification : `identity_report` liste le staff, ses groupes, `last_login` et la date du dernier événement `evidence_viewed`, pour une revue trimestrielle.

### 1.8 Modèles KYC (nouveaux, L5a)

```python
class KycStatus(models.TextChoices):
    DRAFT = "draft", "Brouillon"
    PENDING = "pending", "Vérification automatique en cours"
    REVIEW = "review", "Revue humaine"
    APPROVED = "approved", "Approuvé"
    REJECTED = "rejected", "Rejeté"
    SUSPENDED = "suspended", "Suspendu"


class KycConsent(models.Model):                       # append-only
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    profile = models.ForeignKey(HandymanProfile, on_delete=models.PROTECT, related_name="kyc_consents")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    version = models.CharField(max_length=32)         # ex. "2026-10-v1", = nom du fichier handy/legal/kyc_consent/
    text_sha256 = models.CharField(max_length=64)     # empreinte du texte exact servi (§4.13)
    locale = models.CharField(max_length=8, default="fr")
    channel = models.CharField(max_length=16)         # web|android|ios|unknown
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, blank=True, default="")
    granted_at = models.DateTimeField(auto_now_add=True)


class KycSubmission(models.Model):                    # une tentative
    class Status(models.TextChoices):
        DRAFT="draft"; PENDING="pending"; REVIEW="review"; APPROVED="approved"; REJECTED="rejected"; CANCELLED="cancelled"
    class Mode(models.TextChoices):
        PROVIDER="provider"; MANUAL="manual"; LEGACY="legacy"
    class Channel(models.TextChoices):
        SDK_WEB="sdk_web"; INHOUSE_WEB="inhouse_web"; INHOUSE_ANDROID="inhouse_android"; INHOUSE_IOS="inhouse_ios"; LEGACY="legacy"
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    profile = models.ForeignKey(HandymanProfile, on_delete=models.PROTECT, related_name="kyc_submissions")
    attempt_number = models.PositiveSmallIntegerField()
    purpose = models.CharField(max_length=16, default="verification")      # verification|reauth (§2.7)
    status = models.CharField(max_length=16, choices=Status.choices, default="draft", db_index=True)
    mode = models.CharField(max_length=16, choices=Mode.choices, blank=True, default="")     # figé au submit
    capture_channel = models.CharField(max_length=20, choices=Channel.choices, blank=True, default="")
    id_type = models.CharField(max_length=32, default="IDENTITY_CARD")
    id_country = models.CharField(max_length=2, default="CI")
    consent = models.ForeignKey(KycConsent, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    # --- prestataire (uniquement des données relues par appel AUTHENTIFIÉ, §5.8) ---
    provider = models.CharField(max_length=32, blank=True, default="")
    provider_environment = models.CharField(max_length=16, blank=True, default="")          # sandbox|production
    provider_job_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    provider_status = models.CharField(max_length=16, blank=True, default="")               # clear|attention|block|error|processing
    provider_reason = models.CharField(max_length=64, blank=True, default="")
    provider_result = models.JSONField(default=dict, blank=True)    # assaini, AVEC le verdict de chaque contrôle (actions)
    provider_result_authenticated = models.BooleanField(default=False)
    provider_device_signals_ok = models.BooleanField(null=True)       # SDK uniquement, relu côté serveur
    provider_submitted_at = models.DateTimeField(null=True, blank=True)
    provider_completed_at = models.DateTimeField(null=True, blank=True)
    provider_attempts = models.PositiveSmallIntegerField(default=0)
    provider_last_error = models.CharField(max_length=255, blank=True, default="")
    # --- contrôles internes ---
    flags = models.JSONField(default=list, blank=True)                # §2.5
    document_number_hmac = models.CharField(max_length=64, blank=True, default="", db_index=True)
    identity_hmac_key_version = models.PositiveSmallIntegerField(null=True, blank=True)
    document_number_last4 = models.CharField(max_length=4, blank=True, default="")
    document_expires_on = models.DateField(null=True, blank=True)
    capture_metadata = models.JSONField(default=dict, blank=True)     # NON FIABLE : affiché, jamais utilisé pour décider
    # --- décision ---
    decision = models.CharField(max_length=32, blank=True, default="")    # approve|reject|request_resubmission|provider_clear|provider_block|revoked|cancelled
    approval_case = models.CharField(max_length=1, blank=True, default="")  # A|B|C|D (§2.3)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="kyc_decisions")
    second_approver = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    pending_approval_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    pending_approval_at = models.DateTimeField(null=True, blank=True)
    pending_approval_payload = models.JSONField(default=dict, blank=True)   # checklist, expiration, numéro (HMAC)
    reason_code = models.CharField(max_length=40, blank=True, default="")
    user_message = models.CharField(max_length=500, blank=True, default="")
    internal_note = models.TextField(blank=True, default="")
    review_checklist = models.JSONField(default=dict, blank=True)
    resubmission_allowed = models.BooleanField(default=True)
    claimed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "attempt_number"], name="kyc_attempt_unique"),
            models.UniqueConstraint(fields=["profile"], condition=Q(status__in=["draft", "pending", "review"]),
                                    name="kyc_one_open_submission"),
        ]
        indexes = [models.Index(fields=["status", "submitted_at"])]
        permissions = [
            ("kyc_view_queue", "Voir la file de validation KYC"),
            ("kyc_view_evidence", "Consulter les pièces d'identité KYC"),
            ("kyc_decide", "Approuver / rejeter un dossier KYC"),
            ("kyc_approve_manual", "Approuver sans contrôle prestataire (quatre yeux)"),
            ("kyc_suspend", "Suspendre / réhabiliter / révoquer un Handyman"),
            ("kyc_view_audit", "Consulter l'historique KYC"),
            ("kyc_override", "Dérogations Superviseur (doublon, échec prestataire, bris de glace)"),
        ]


def kyc_evidence_upload_path(instance, filename):
    sub = instance.submission
    return f"kyc/{sub.profile_id}/{sub.id.hex}/{uuid4().hex}.bin"     # clé opaque, contenu chiffré (§5.9)


@cleanup.ignore
class KycDocument(models.Model):
    class Kind(models.TextChoices):
        ID_FRONT="id_front"; ID_BACK="id_back"; SELFIE="selfie"; LIVENESS_FRAME="liveness_frame"
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    submission = models.ForeignKey(KycSubmission, on_delete=models.PROTECT, related_name="documents")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    sequence = models.PositiveSmallIntegerField(null=True, blank=True)   # 0..7 pour la liveness
    source = models.CharField(max_length=10, default="client")          # client|provider (copie depuis le résultat SDK, L10)
    file = models.FileField(upload_to=kyc_evidence_upload_path, storage=KycPrivateStorage(), max_length=255)
    content_type = models.CharField(max_length=64)                      # image/jpeg ou image/png (jamais de PDF)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)             # du contenu en clair
    encryption = models.JSONField(default=dict)                         # {"alg":"AES-256-GCM","key_version":1,"nonce":"…"}
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    uploaded_ip = models.GenericIPAddressField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)             # objet expiré par le cycle de vie (§5.9)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["submission", "kind"],
                condition=Q(superseded_at__isnull=True, kind__in=["id_front", "id_back", "selfie"]), name="kyc_doc_single_kind"),
            models.UniqueConstraint(fields=["submission", "sequence"],
                condition=Q(superseded_at__isnull=True, kind="liveness_frame"), name="kyc_doc_frame_sequence"),
        ]


class KycAuditEvent(models.Model):                     # append-only, chaîné par profil
    profile = models.ForeignKey(HandymanProfile, on_delete=models.PROTECT, related_name="kyc_events")
    submission = models.ForeignKey(KycSubmission, on_delete=models.PROTECT, null=True, blank=True, related_name="events")
    seq = models.PositiveIntegerField()                 # 1, 2, 3… par profil
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    actor_type = models.CharField(max_length=16)        # user|reviewer|admin|system|provider
    actor_label = models.CharField(max_length=120)      # instantané lisible, ex. "reviewer #12 Awa K."
    action = models.CharField(max_length=40, db_index=True)
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16, blank=True, default="")
    reason_code = models.CharField(max_length=40, blank=True, default="")
    note = models.TextField(blank=True, default="")     # interne
    metadata = models.JSONField(default=dict, blank=True)   # assaini ; instantané complet pour une décision
    ip = models.GenericIPAddressField(null=True, blank=True)
    prev_hash = models.CharField(max_length=64)          # hash de l'événement seq-1 ("0"*64 pour le premier)
    hash = models.CharField(max_length=64)               # sha256(prev_hash || JSON canonique des champs ci-dessus)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["profile", "seq"], name="kyc_audit_seq_unique")]
        indexes = [models.Index(fields=["profile", "-created_at"])]


class KycWebhookEvent(models.Model):                   # uniquement pour une signature VALIDE
    provider = models.CharField(max_length=32)
    job_id = models.CharField(max_length=64, db_index=True)
    timestamp_header = models.CharField(max_length=40)
    outcome = models.CharField(max_length=32)           # queued|duplicate|stale|unknown_job
    ip = models.GenericIPAddressField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "job_id", "timestamp_header"],
                                               name="kyc_webhook_once")]
```

- Une tentative est comptée si `submitted_at` est renseigné, `mode != legacy`, `purpose = verification`, et qu'elle n'a pas été rejetée pour `document_unreadable`.
- L'écriture d'un `KycAuditEvent` passe **uniquement** par `handy/kyc/audit.record()`, appelé dans la transaction qui verrouille le profil (`select_for_update`) : `seq` et `prev_hash` sont lus sous ce verrou.
- L'événement d'une décision embarque un instantané complet dans `metadata` : `decision`, `approval_case`, `reason_code`, `review_checklist`, `decided_by`, `second_approver`, `document_number_last4`, `document_expires_on`, `flags`, verdicts prestataire, et les `sha256` de `user_message` et `internal_note`.

Actions de `KycAuditEvent.action` (liste fermée, `handy/kyc/audit.py`) :
- candidature et consentement : `application_created`, `consent_granted`, `consent_superseded` ;
- pièces : `document_uploaded`, `document_superseded`, `documents_purged`, `evidence_viewed`, `evidence_break_glass`, `proof_uploaded`, `proof_reviewed` ;
- soumission et prestataire : `submitted`, `provider_sent`, `provider_result`, `provider_error`, `provider_identity_mismatch`, `escalated_review` ;
- décisions : `approval_first`, `approval_cancelled`, `approved`, `rejected`, `resubmission_requested`, `duplicate_override`, `claimed`, `released`, `retry_provider` ;
- cycle de vie : `suspended`, `reinstated`, `revoked`, `funds_frozen`, `funds_released`, `reauth_required`, `reauth_cleared`, `document_expired` ;
- publication et reprise : `published`, `unpublished`, `legacy_migrated`, `legacy_data_fixed`.

### 1.9 Legacy `HandymanDocument`

Modèle et données conservés ; `on_delete=PROTECT` (0029, L1a) et `@cleanup.ignore` (L1b).
- `GET /handy/handyman-docs/` : ses propres documents ; `download` par le propriétaire.
- Liste globale, `review` et téléchargement par un tiers : **superusers uniquement** en L1b (avec `AccountEvent legacy_evidence_viewed`, interdiction sur son propre dossier), puis `kyc_view_evidence` avec les règles du §5.9 en L5b.
- `POST`, `DELETE` et `review` : en-tête `Deprecation: true` et `Link` vers le nouveau parcours à partir de L6 ; **410** `endpoint_deprecated` seulement en L11, quand `LEGACY_KYC_DOCS_WRITE_ENABLED=false` (après L7 et la publication de L9b).
- Admin Django : lecture seule, sans lien ni aperçu de fichier.

### 1.10 Invariants, journaux append-only et rôles PostgreSQL

| Invariant | Mécanisme |
|---|---|
| `is_approved ⇔ kyc_status='approved'` | CHECK `hm_is_approved_mirrors_kyc` ; champs réservés (§1.5) |
| `is_published ⇒ approved`, `online ⇒ is_published` | CHECK `hm_published_requires_approved`, `hm_online_requires_published` |
| Au plus une soumission ouverte par profil | `kyc_one_open_submission` |
| Une seule pièce active par type et par tentative | `kyc_doc_single_kind`, `kyc_doc_frame_sequence` |
| Téléphone vérifié ⇒ téléphone renseigné | `user_verified_phone_requires_phone` |
| Journaux non modifiables | Rôle `tratra_app` limité à `SELECT, INSERT` ; trigger ; chaîne de hachage |
| Preuves non supprimables par cascade | `PROTECT` sur `KycSubmission`, `KycDocument`, `KycAuditEvent`, `KycConsent`, `HandymanProof`, `AccountEvent`, `HandymanDocument` ; `@cleanup.ignore` |
| Données financières et contractuelles non supprimables par cascade | `PROTECT` (état Python seul, 0029) sur `Booking.client`, `Booking.handyman`, `Payment.booking`, `Payout.handyman`, `DepositTransaction.handyman`, `Invoice.booking`, `Subscription.user`, `Review.booking`, `Dispute.booking`, `PayoutAccount.handyman` |

**Rôles PostgreSQL** (production ; `deploy/sql/roles.sql` et `grants.sql`, exécutés par l'exploitant) :
- `tratra_migrator` : propriétaire du schéma et des tables ; utilisé **uniquement** par le job de migration (`docker compose run --rm migrate`, §6.8).
- `tratra_app` : rôle d'exécution de `web`, `worker` et `beat` ; ni superuser, ni propriétaire. `grants.sql`, rejoué après chaque migration :

```sql
GRANT USAGE ON SCHEMA public TO tratra_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tratra_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tratra_app;
REVOKE UPDATE, DELETE, TRUNCATE ON handy_kycauditevent, handy_kycconsent, handy_accountevent FROM tratra_app;
REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM tratra_app;
```

  Les tables d'audit n'existant qu'à partir de leur lot, le script ignore celles qui sont absentes (bloc `DO` avec `to_regclass`).
- Dev et CI restent sur `postgres` (le flush des tests `transactional_db` exige TRUNCATE). Le test `test_db_roles.py` crée un rôle temporaire avec les mêmes droits, fait `SET ROLE` et vérifie que UPDATE, DELETE et TRUNCATE sont refusés.

**Trigger** (défense en profondeur ; la fonction est créée en 0030 et n'est supprimée que par l'inverse de 0030) :

```sql
CREATE OR REPLACE FUNCTION handy_forbid_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'append-only table %', TG_TABLE_NAME USING ERRCODE = 'integrity_constraint_violation'; END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER accountevent_append_only BEFORE UPDATE OR DELETE ON handy_accountevent
  FOR EACH ROW EXECUTE FUNCTION handy_forbid_mutation();          -- 0030 ; idem kycauditevent et kycconsent en 0037
```

**Chaîne et ancrage** : `kyc_verify_audit_chain [--profile <id>]` recalcule chaque chaîne et signale toute rupture (code de sortie non nul). La tâche quotidienne `kyc_anchor_audit_heads` exporte la liste `(profile_id, seq, hash)` des têtes de chaîne, signée HMAC, vers `KYC_AUDIT_ANCHOR_BUCKET` (bucket MinIO avec verrouillage d'objet en mode conformité) ; c'est un prérequis du go/no-go de R3.

Conséquence : un `User` ou un reviewer référencé par un journal ne peut plus être supprimé physiquement ; on le **désactive**. Une purge RGPD future passera par le rôle migrateur et une procédure documentée (backlog).

---

## 2. Machine d'états KYC et cas d'approbation

### 2.1 États

| État | Signification | Visible publiquement | Présence en ligne |
|---|---|---|---|
| `draft` | Candidature ou KYC en préparation, rien de soumis | Non | Non |
| `pending` | Soumis au prestataire, résultat attendu | Non | Non |
| `review` | Décision humaine attendue (mode manuel, capture maison, `attention`, signal interne, erreur prestataire, legacy) | Non | Non |
| `approved` | Vérification approuvée selon l'un des cas du §2.3 | **Oui si publiable** (§3) | Oui si publiable et position renseignée |
| `rejected` | Tentative refusée ou vérification révoquée ; resoumission possible si `resubmission_allowed` | Non | Non |
| `suspended` | Gel administratif (fraude, plaintes, enquête) | Non | Non |

Les statuts de `KycSubmission` (`draft`, `pending`, `review`, `approved`, `rejected`, `cancelled`) suivent la tentative ; `HandymanProfile.kyc_status` porte le cycle de vie ; `suspended` n'existe qu'au niveau du profil.

### 2.2 Transitions autorisées

`KycService` (`handy/kyc/service.py`) applique ces transitions. Toute transition :
- s'exécute dans `transaction.atomic()`, avec `select_for_update()` sur le profil puis sur la soumission (toujours dans cet ordre) ;
- est validée contre `TRANSITIONS` (`handy/kyc/states.py`), sinon `InvalidTransition` → **409** `invalid_transition` ;
- écrit les champs réservés avec `_kyc_write=True` (§1.5) et un `KycAuditEvent` chaîné.

| # | De → vers | Acteur | Déclencheur | Préconditions | Effets spécifiques |
|---|---|---|---|---|---|
| T1 | ∅ → `draft` | utilisateur | `PUT /users/me/handyman/` (création) | Compte actif | Création du profil ; audit `application_created`. |
| T2 | `draft` → `pending` | utilisateur | `POST …/kyc/submit/`, prestataire configuré | Téléphone vérifié ; candidature complète (§3.1, conditions 1 à 3 et 6 à 11) ; consentement de la version courante ; pièces complètes pour le canal ; tentatives < `KYC_MAX_ATTEMPTS` (3) ; `KYC_SUBMISSIONS_ENABLED` | `mode=provider`, `submitted_at`, `application_submitted_at` (première fois). Canal maison : tâche `kyc_submit_to_provider` après le commit. Canal SDK : le job existe déjà chez le prestataire (§4.8), on attend le résultat. |
| T3 | `draft` → `review` | utilisateur | idem, **sans prestataire** | idem | `mode=manual`, drapeau `no_provider_check`. |
| T4 | `rejected` → `pending` ou `review` | utilisateur | resoumission (tentative n+1) | `resubmission_allowed` ; tentatives restantes ; non suspendu | Comme T2 ou T3. |
| T5 | `pending` → `approved` | système | résultat prestataire **authentifié** | **Cas A** (§2.3) | `verification_level=provider` (ou `sandbox` en dev/test). |
| T6 | `pending` → `review` | système ou admin | tout résultat qui n'est pas le cas A ni un rejet direct (tableau §2.5) ; délai de 48 h ; reprise manuelle | — | Audit `escalated_review` avec motif. |
| T7 | `pending` → `rejected` | système | rejet direct (tableau §2.5) ; doublon d'un profil écarté pour fraude | — | `resubmission_allowed` selon le motif ; notification `kyc_rejected`. |
| T8 | `review` → `approved` | reviewer(s) | `POST /admin/kyc/submissions/{id}/decision/ {"decision":"approve"}` | **Cas B, C ou D** (§2.3), conditions communes comprises | `verification_level` selon le cas. |
| T9 | `review` → `rejected` | reviewer ou système | `reject`, `request_resubmission`, `kyc_legacy_request_resubmission` | `kyc_decide` ; pas son propre dossier ; `reason_code` valide ; `user_message` obligatoire pour `other` | Annule toute approbation en attente du second approbateur. |
| T10 | `review` → `pending` | reviewer | `retry-provider` | `kyc_decide` ; prestataire configuré ; canal maison avec pièces complètes | Nouveau job ; `provider_attempts` + 1. |
| T11 | `approved` → `suspended` | admin ou système | `suspend` | `kyc_suspend` ; pas son propre dossier ; `reason_code` | `status_before_suspension='approved'`, `withdrawn_at=now` ; retrait (§2.4). |
| T12 | `draft`, `pending`, `review`, `rejected` → `suspended` | admin | `suspend` (fraude avant approbation) | idem | Soumission ouverte gelée (hors file) ; resoumission bloquée. |
| T13 | `suspended` → `approved` | admin | `reinstate` | `kyc_suspend` ; pas son propre dossier ; `status_before_suspension='approved'` ; dernière soumission approuvée ; pièce non expirée ; compte actif | `withdrawn_at=NULL` ; `refresh_publication` ; notification `kyc_reinstated`. `funds_frozen` reste tel quel (levée explicite). |
| T14 | `approved` ou `suspended` → `rejected` | admin ou système | `revoke` ; expiration de la pièce ; revérification négative ; doublon découvert après coup | `kyc_suspend`, ou système | Vérification **révoquée** : soumission ouverte annulée ; `withdrawn_at` (s'il était approuvé) ; `resubmission_allowed` (faux pour les codes de fraude) ; `funds_frozen=True` pour les codes de fraude ; retrait. |

Toute autre transition est interdite : notamment `draft → approved`, `rejected → approved` et `review → approved` hors des cas du §2.3. La ré-authentification (§2.7) ne change pas `kyc_status`.

### 2.3 Cas d'approbation (liste fermée, `handy/kyc/approval.py`)

`KycService.approve()` détermine le cas à partir de la soumission. Si aucun cas ne s'applique, l'action `approve` n'apparaît pas dans `allowed_actions` et l'API renvoie 409 avec le code du premier critère manquant.

| Cas | Situation | Qui approuve | `verification_level` | Badge « Identité vérifiée » |
|---|---|---|---|---|
| **A** (automatique, T5) | `mode=provider`, canal `sdk_web`, résultat **authentifié** `clear`, **toutes** les vérifications (`actions`) réussies (liveness, comparaison selfie et pièce, authenticité, validité), signaux appareil relus et sains, `user_id` et `partner_params` concordants, aucun drapeau interne, `KYC_AUTO_APPROVE_ON_CLEAR=true` et capacité « résultat authentifié complet » confirmée en L0 | système | `provider` | Oui |
| **B** (un reviewer, T8) | Résultat authentifié dont la **liveness et la comparaison faciale ont réussi** et l'authenticité n'a pas échoué, avec statut `clear` (capture maison) ou `attention` hors motifs de fraude et d'âge ; aucun signal de fraude ni doublon | un reviewer `kyc_decide` | `provider_reviewed` | Oui |
| **C** (dérogation, quatre yeux, T8) | Dossier en revue avec signal de fraude, doublon (`duplicate_identity`), discordance d'identité prestataire, ou échec de liveness ou de visage remonté en revue | 1ᵉʳ : Superviseur `kyc_override` ; 2ᵉ : une autre personne `kyc_decide` | `provider_reviewed` si liveness **et** visage ont réussi selon le résultat authentifié, sinon `manual` | Seulement si `provider_reviewed` |
| **D** (sans prestataire, quatre yeux, T8) | Aucun résultat prestataire exploitable (mode manuel, prestataire indisponible) | Uniquement si `KYC_MANUAL_APPROVAL_ALLOWED` (C2) : 1ᵉʳ `kyc_approve_manual`, 2ᵉ une autre personne `kyc_approve_manual` ou `kyc_override` | `manual` | **Non** (mention « Pièce contrôlée par Tratra ») |

Une soumission `mode=legacy` n'est **jamais** approuvable. Un `block` du prestataire mène directement à `rejected` (T7), sauf les signaux de fraude, qui passent en revue où seuls `reject` et `request_resubmission` sont permis hors cas C.

**Conditions communes à toute approbation** :
1. Compte actif et téléphone vérifié.
2. Jeu de preuves complet **dans cette soumission** : recto, verso (si `has_back`), selfie, et 6 à 8 images de liveness pour une capture maison ; pour le canal SDK, recto, verso et selfie copiés depuis le résultat authentifié (L10).
3. `document_expires_on` renseigné et postérieur à aujourd'hui ; `document_number_hmac` renseigné (résultat authentifié, sinon saisi par le reviewer). Sans endpoint authentifié renvoyant `id_fields`, le numéro et l'expiration sont **toujours** saisis par le reviewer, et le cas A est désactivé.
4. Contrôle de doublon à jour (§2.5) : un doublon impose le cas C (409 `duplicate_identity` sinon).
5. Approbation humaine (B, C, D) : chaque approbateur a ouvert le recto, le verso et le selfie de cette soumission (événements `evidence_viewed` à son nom), sinon 409 `evidence_not_reviewed` ; liste de contrôle complète (`face_matches_document`, `document_authentic`, `names_match_account`, `document_not_expired`) ; dossier pris en charge par le premier approbateur ; aucun approbateur n'est le titulaire.
6. Environnement : résultat `production`, ou `DJANGO_ENV` dans `{dev, test}` ; dans ce second cas `verification_level='sandbox'`, jamais badgé. Un résultat `sandbox` en production n'est jamais approuvable.

**Protocole à quatre yeux** (C et D) :
1. Le premier approbateur envoie `{"decision":"approve", …}` → **202** `{"status":"awaiting_second_approval"}` ; la soumission reste en `review` avec `pending_approval_by`, `pending_approval_at` et `pending_approval_payload` ; audit `approval_first`.
2. Une **autre** personne habilitée envoie `{"decision":"approve","confirm":true}` après avoir ouvert les preuves → transition T8 ; `decided_by` = premier, `second_approver` = second.
3. Le même utilisateur qui confirme → 409 `second_approver_required`. Un `reject` ou un `request_resubmission` annule l'approbation en attente (`approval_cancelled`). Sans confirmation sous 72 h, la tâche `kyc_expire_pending_approvals` l'annule.

Chaque cas a son test (`test_kyc_approval_cases.py`).

### 2.4 Effets de bord communs

**Approbation** (T5, T8, T13), dans la même transaction :
1. Soumission : `status=approved`, `decision`, `approval_case`, `decided_at`, `decided_by`, `second_approver`.
2. Profil : `kyc_status=approved`, `identity_verified_at`, `verification_level`, motifs vidés, `current_submission`.
3. `refresh_publication(profile)` ; s'il manque quelque chose, `capabilities.handyman.missing` le liste.
4. `refresh_quality_score()`.
5. Après le commit : invalidation des caches publics (§3.6), notification `kyc_approved`, audit `approved` (instantané complet).

**Retrait** (T11, T12, T14, ré-authentification exigée, désactivation du compte), dans la même transaction :
1. `is_published=False`, `online=False` (garanti par `save()` et les CHECK).
2. Le profil sort immédiatement de toutes les requêtes du §3.3.
3. Réservations existantes **inchangées**. Pour les réservations `pending` ou `confirmed` dont le profil est l'artisan : notification `booking_handyman_unavailable` au client. `Booking.compute_cancellation_fee()` renvoie 0 **seulement si** `handyman_profile.withdrawn_at` est renseigné, postérieur à `booking.created_at`, et que le profil n'est pas revenu à `approved`. Les artisans legacy dépubliés par la reprise (R3) n'ont pas de `withdrawn_at` : leurs réservations gardent la politique d'annulation normale (`test_sprint4.py:129` reste vert).
4. Paiements et versements, via une fonction unique `payout_block_reason(user)` et `payment_block_reason(booking)` :
   - `payment_initiate` → 409 `handyman_unavailable` si l'artisan est `suspended`, `funds_frozen`, ou retiré (`withdrawn_at` renseigné et non `approved`) ;
   - `PayoutViewSet.create` → 409 `payouts_on_hold` si `user.payout_hold_until > now`, si le profil est `suspended` ou si `funds_frozen` ;
   - les soldes sont conservés ; `funds_frozen` n'est levé que par `POST /admin/kyc/profiles/{id}/release-funds/` (`kyc_override`, audité).
5. Les sessions ne sont pas révoquées : le compte reste client. La désactivation du compte, elle, incrémente `session_version`.
6. Après le commit : invalidation des caches, revalidation du front, notification `kyc_suspended`, `kyc_revoked` ou `kyc_reauth_required`, audit.
7. `BookingSerializer` expose `handyman_available` (artisan publiable) et `cancellation_fee_waived` (règle du point 3) ; React et Flutter affichent un bandeau sur la réservation (§7.3, §8.2).

**Rejet** (T7, T9) : message utilisateur, `resubmission_allowed`, notification `kyc_rejected` ou `kyc_resubmission_requested`.

**Notifications** : in-app toujours (`Notification`, annexe C) ; SMS seulement pour `approved`, `rejected`, `suspended`, `revoked` et `reauth_required`, et seulement si `preferences.notifications.sms` est vrai. Aucun push n'est promis (aucun client ne le reçoit aujourd'hui).

### 2.5 Résultats prestataire et drapeaux internes

Toutes les données viennent de la **relecture authentifiée** (§5.8). Le corps du webhook n'est jamais lu.

| Résultat (Smile) | Motif | Suite |
|---|---|---|
| `clear` | — | Canal `sdk_web` et cas A rempli : T5. Sinon (capture maison, drapeau, contrôle manquant) : T6, cas B possible. |
| `attention` | `document_expired` | T7, `document_expired`, resoumission permise. |
| `attention` | `document_copy_detected`, `medium_risk` | T6 ; cas B si liveness et visage ont réussi, sinon cas C. |
| `attention` ou `block` | `age_requirement_not_met` | T7, `underage`, sans resoumission. |
| `block` | `face_verification_failed` | T7, `face_mismatch`, resoumission si tentatives restantes. |
| `block` | `spoof_detected` | T7, `liveness_failed`. Deux occurrences sur un profil : `resubmission_allowed=false` et alerte Superviseur. |
| `block` | `document_check_failed`, `unsupported_document` | T7, `document_not_accepted`. |
| `block` | `high_risk`, `account_locked_fraud` | T6, drapeau `provider_fraud_signal` (rejet seulement, sauf cas C). |
| `error` | `image_unavailable_or_invalid`, `document_unclassifiable` | T7, `document_unreadable` (ne consomme pas de tentative). |
| `error` | `internal_error` | Un nouvel essai, puis T6 (`provider_error`, cas D possible si C2). |
| `error` | `content_policy_violated` | T6 (`provider_content_policy`). |
| `processing` | — | Reste `pending` (relecture 2 min plus tard). |
| `user_id` ≠ `kyc_subject_id` ou `partner_params.submission_id` ≠ soumission | — | T6, drapeau `provider_identity_mismatch` (rejet seulement, sauf cas C). |
| Aucun résultat après 48 h | — | T6, `provider_timeout`. |
| Statut inconnu | — | T6, `provider_unknown_status`. |

**Drapeaux internes** (calculés sur le résultat authentifié ; tous excluent le cas A) :
- `duplicate_identity` : le HMAC du numéro existe sur une soumission **soumise** (`submitted_at` renseigné) d'un **autre** profil, **quel que soit son statut** (`rejected` et `cancelled` compris). Le HMAC est calculé sous **chaque** clé active du trousseau `IDENTITY_HMAC_KEYS` et comparé au couple (`document_number_hmac`, `identity_hmac_key_version`) (Arbitrages A1). Si l'autre profil a été rejeté, révoqué ou suspendu avec un motif de fraude (`suspected_fraud`, `duplicate_identity`, `fraud_investigation`) : T7 ou T9 automatique, `reason_code=duplicate_identity`, `resubmission_allowed=false`, alerte Superviseur. Sinon : revue, cas C obligatoire.
- `name_mismatch` : nom ou prénoms du compte différents de `id_fields` après normalisation (minuscules, accents retirés, ordre des prénoms ignoré).
- `document_expired` : expiration antérieure ou égale à aujourd'hui (rejet, voir le tableau).
- `account_inactive` : compte désactivé entre-temps.
- `sandbox_result` : environnement `sandbox` alors que `DJANGO_ENV=prod` (jamais approuvable).
- `inhouse_capture` : capture maison (information : revue humaine obligatoire).

Ne sont conservés que : `document_number_hmac`, sa version de clé, `document_number_last4`, `document_expires_on`, les booléens de concordance et le **verdict de chaque contrôle** (`actions`, sous forme `{"liveness":"passed","selfie_to_id":"passed","document_authenticity":"passed","expiry":"passed"}`) plus le niveau de risque. Jamais `id_fields` en clair, `image_links`, `kyc_receipt` ni `device_signals` bruts.

### 2.6 Mode manuel (aucun prestataire configuré)

- `KYC_PROVIDER=''`. Toute soumission suit T3 vers `review` (capture maison, drapeau `no_provider_check`). **Aucune approbation automatique n'existe dans ce mode.**
- Bandeau dans la fiche : « Aucun contrôle automatique : liveness et comparaison faciale non réalisées ».
- Approbation seulement par le cas D (C2 accepté, quatre yeux, sans badge). Sinon `allowed_actions` ne contient pas `approve` et l'API renvoie 409 `manual_approval_disabled`.
- Quand un prestataire est branché, `kyc_reverify_manual --apply` (L10) demande aux profils `verification_level=manual` une nouvelle capture SDK ; ils restent `approved` pendant 30 jours, puis passent en ré-authentification exigée s'ils n'ont pas refait la vérification. Un résultat négatif mène à T14.

### 2.7 Resoumission, tentatives, réhabilitation, ré-authentification

- `KYC_MAX_ATTEMPTS=3` tentatives comptées (§1.8). Au-delà : `can_resubmit=false`, `attempts_exhausted` ; un Superviseur peut rouvrir (`allow-resubmission`, `kyc_suspend`, audité).
- Après un rejet avec `resubmission_allowed`, le premier upload crée la tentative n+1 **sous verrou du profil** (deux uploads concurrents ne créent qu'une tentative). Les pièces précédentes ne sont pas recopiées. Le consentement de la même version est réutilisé.
- Réhabilitation (T13) : seulement pour un profil `approved` avant sa suspension.
- **Ré-authentification** (`reauth_required_at`) : posée par le système après une réinitialisation de mot de passe, un changement de numéro ou une revendication de compte (§4.1, §4.3, §4.5) sur un profil `approved`, ou par `kyc_reverify_manual`. Le profil est **dépublié** (condition 5 du §3.1) sans changer de `kyc_status`. L'artisan dépose une soumission `purpose=reauth` (selfie et liveness en capture maison) ; un reviewer la compare au selfie enrôlé et décide `approve` (efface `reauth_required_at`, republie) ou `reject` (reste exigée ; `revoke` possible). En L10, la comparaison est faite par SmartSelfie Authentication du prestataire, suivie de la même décision humaine si le score n'est pas net (Arbitrages A7).

### 2.8 Tâches planifiées (Celery beat)

| Tâche | Fréquence | Rôle | Lot |
|---|---|---|---|
| `handy.tasks.release_matured_escrows` | 15 min | Libère les séquestres dont `release_after` est atteint sans litige ouvert. | L1c |
| `handy.identity.tasks.purge_otp_challenges` | horaire | Vide `payload` des challenges et revendications expirés ; supprime les challenges expirés depuis 7 jours et les `OtpSendLog` de plus de 30 jours. | L3a |
| `handy.kyc.tasks.kyc_poll_pending` | 5 min | Relecture authentifiée des soumissions `pending` envoyées depuis plus de 10 min ; T6 au-delà de 48 h. | L10 |
| `handy.kyc.tasks.kyc_expire_pending_approvals` | horaire | Annule les approbations en attente du second approbateur depuis 72 h. | L5b |
| `handy.kyc.tasks.kyc_expire_documents` | quotidienne, 02:30 | T14 (`document_expired`) à l'échéance ; notifications à J-30 et J-7. | L5a |
| `handy.kyc.tasks.kyc_reconcile_publication` | quotidienne, 03:00 | Recalcule `is_published`, corrige et alerte toute dérive. | L5a |
| `handy.kyc.tasks.kyc_mark_purged_objects` | quotidienne | Marque `purged_at` sur les pièces de brouillon expirées par le cycle de vie du bucket (§5.9). | L6 |
| `handy.kyc.tasks.kyc_anchor_audit_heads` | quotidienne, 04:00 | Ancrage des têtes de chaîne (§1.10). | L5b |
| `handy.tasks.send_profile_completion_reminders` (existante) | hebdomadaire | Profils `approved` non publiables, avec les éléments `missing`. | L5a |

---

## 3. Prédicat unique « publiable »

### 3.1 Définition

Un profil Handyman est **publiable** si et seulement si **toutes** les conditions suivantes sont vraies. Les codes `missing` sont renvoyés dans cet ordre :

| # | Condition | Code `missing` |
|---|---|---|
| 1 | `user.is_active` | `account_inactive` |
| 2 | `user.first_name` et `user.last_name` non vides | `names` |
| 3 | `user.phone_verified_at` renseigné | `phone_verified` |
| 4 | `kyc_status == 'approved'` | `kyc_approved` |
| 5 | `reauth_required_at` vide | `reauth_required` |
| 6 | `len(bio.strip()) >= 30` | `bio` |
| 7 | au moins un métier actif (`skills` avec `parent IS NULL`) | `trades` |
| 8 | `commune` renseignée | `commune` |
| 9 | `hourly_rate > 0` ou `daily_rate > 0` | `rates` |
| 10 | au moins un `AvailabilitySlot` | `availability` |
| 11 | au moins un `Service` **actif** de l'utilisateur dont la catégorie est un métier choisi ou l'une de ses sous-catégories | `services` |
| 12 | hors `DJANGO_ENV=dev` : `verification_level != 'seed'` | `seed_profile` |

Les conditions 1 à 3 et 6 à 11 forment la « candidature complète » exigée à la soumission (T2) : le profil est publiable dès son approbation, sauf modification ultérieure.

`can_go_online` = publiable **et** `location` renseignée. Sinon `missing_for_online` contient `"location"` (le matching exige une position, `services/matching.py:13`).

### 3.2 Implémentation

```python
# handy/kyc/publication.py  (Python 3.9)
from typing import List, Tuple
BIO_MIN = 30

def evaluate_publication(profile) -> Tuple[bool, List[str]]:
    u = profile.user
    missing = []
    if not u.is_active: missing.append("account_inactive")
    if not (u.first_name or "").strip() or not (u.last_name or "").strip(): missing.append("names")
    if u.phone_verified_at is None: missing.append("phone_verified")
    if profile.kyc_status != "approved": missing.append("kyc_approved")
    if profile.reauth_required_at is not None: missing.append("reauth_required")
    if len((profile.bio or "").strip()) < BIO_MIN: missing.append("bio")
    trades = list(profile.skills.filter(parent__isnull=True, is_active=True).values_list("id", flat=True))
    if not trades: missing.append("trades")
    if not (profile.commune or "").strip(): missing.append("commune")
    if not ((profile.hourly_rate or 0) > 0 or (profile.daily_rate or 0) > 0): missing.append("rates")
    if not profile.availability_slots.exists(): missing.append("availability")
    if not Service.objects.filter(handyman_id=u.id, is_active=True)\
            .filter(Q(category_id__in=trades) | Q(category__parent_id__in=trades)).exists():
        missing.append("services")
    if settings.DJANGO_ENV != "dev" and profile.verification_level == "seed": missing.append("seed_profile")
    return (not missing, missing)

def publishable_q(prefix: str = "") -> Q:
    """Filtre défensif : drapeau dénormalisé + vérité KYC + compte actif + pas de ré-authentification."""
    q = Q(**{f"{prefix}is_published": True, f"{prefix}kyc_status": "approved",
             f"{prefix}user__is_active": True, f"{prefix}reauth_required_at__isnull": True})
    if settings.DJANGO_ENV != "dev":
        q &= ~Q(**{f"{prefix}verification_level": "seed"})
    return q

class HandymanProfileQuerySet(models.QuerySet):
    def publishable(self): return self.filter(publishable_q())

class ServiceQuerySet(models.QuerySet):
    def public(self):
        return self.filter(is_active=True).filter(publishable_q("handyman__handyman_profile__"))
```

`refresh_publication(profile, *, actor=None)` :
- relit le profil sous `select_for_update`, appelle `evaluate_publication`, écrit `is_published`, `published_at` (et `online=False` en cas de dépublication) avec `_kyc_write=True` ;
- écrit `published` ou `unpublished` dans l'audit chaîné ;
- après le commit : invalidation des caches et revalidation du front (§3.6).

Appels :
- chaque transition de `KycService`, la pose et la levée d'une ré-authentification ;
- `PUT` et `PATCH /users/me/handyman/` ;
- `m2m_changed` sur `skills` ; `post_save` et `post_delete` d'`AvailabilitySlot` et de `Service` ;
- `post_save` de `User` si `update_fields` est vide ou contient `is_active`, `first_name`, `last_name` ou `phone_verified_at`, et que la valeur diffère de l'instantané pris dans `from_db()` (§1.1) ;
- `HandymanProfileAdmin.save_model`.

Les `.update()` massifs de l'ORM sont rattrapés par la réconciliation de nuit ; le filtre défensif empêche de toute façon de publier un profil non approuvé.

### 3.3 Points d'application (liste exhaustive)

| Lieu (état 2026-10-08) | Avant | Après |
|---|---|---|
| `ServiceViewSet` list (`views.py:484-524`) | aucun filtre | `Service.objects.public()` par défaut. Exceptions : `?handyman=<id>` **strictement égal** à `request.user.id` (ses propres services, actifs ou non) ; `?all=1` avec `view_all_records`. `?verified=1` ignoré (implicite). `?online=1` filtre `online=True`. |
| `ServiceViewSet` retrieve | public | Public si `public()` ; le propriétaire et `view_all_records` voient toujours ; un tiers reçoit **404**. |
| `ServiceViewSet` destroy | suppression | Désactivation (`is_active=False`) si des réservations existent (M-S1). |
| `/services/nearby/` (`views.py:141-149`) | `is_active` seul | `public()` ; filtre, tri et distance calculés sur `public_location` ; rayon client arrondi au palier supérieur parmi 1, 2, 5, 10, 15, 25, 50 km ; `distance_km` arrondi à 0,5 km. |
| `BookingViewSet.alternatives` (`views.py:152-174`) | `is_active` | `public()` |
| `Booking.generate_replacement_suggestions` (`models.py:484-503`) | `is_approved` | `public()` ; `ReplacementSuggestion.accept()` revérifie (`409 service_unavailable`). |
| `ServiceCategoryViewSet.services_count` | services actifs | services `public()` |
| Slides de repli | services actifs | `public()` |
| `HandymanProfileViewSet.featured` | `is_approved` et compte actif | `publishable()` ; sous-filtre `has_service` sur `public()` |
| `compute_public_stats` | approuvés | `artisans_verified` = `publishable().filter(verification_level__in=["provider","provider_reviewed"]).count()` ; `artisans_online` = `publishable().filter(online=True)` ; `services` = `public().count()` |
| `/reviews/public/` (`views.py:925`) | avis des missions terminées | Uniquement les avis d'artisans publiables. |
| Favoris (`Favorite`, liste de l'utilisateur) | liste brute | Favoris d'un artisan non publiable renvoyés avec `available: false`, sans détail de profil. |
| `match_artisans` (`services/matching.py:13`) | `is_approved`, sans `user.is_active` | `publishable().filter(online=True, skills__id=…, location__isnull=False)` hors congés |
| `HandymanProfileViewSet.presence` | `is_approved` | `online=true` exige `can_go_online` (sinon **403** `not_publishable` avec `missing` et `missing_for_online`) ; écrit sous verrou (`set_presence`). `online=false` toujours accepté. |
| `GET /handymen/` et `/handymen/{pk}/` | tout compte connecté, payload complet | Propriétaire (ou `view_all_records`) ; un tiers reçoit **404** (L1a). |
| Profil public | inexistant | `GET /handy/public/handymen/{user_id}/` (§4.13) : publiable, sinon 404 |
| Liste publique (sitemap) | inexistante | `GET /handy/public/handymen/` (§4.13) |
| `BookingCreateSerializer` | aucun contrôle | §3.4 |
| `payment_initiate`, `PayoutViewSet.create` | — | §2.4, point 4 |
| `send_profile_completion_reminders` | approuvés | approuvés et non publiables |
| Admin Django | `is_approved` éditable | Tous les champs réservés en lecture seule |

### 3.4 Réservation

`BookingCreateSerializer.validate()`, dans l'ordre :
1. `capabilities.can_book` (§4.4), sinon **403** `phone_verification_required` ou `account_inactive`. Avec `BOOKING_REQUIRES_PHONE_VERIFIED=true` et `BOOKING_PHONE_GRACE_LEGACY_CLIENTS=true`, une requête **sans** en-tête `X-Tratra-Client` (ancienne app) est acceptée et journalisée (`booking_phone_grace` en métrique) ; la grâce est retirée en L11.
2. `service` fourni : il doit être `public()`, sinon 400 `service_unavailable` ; si `handyman` est aussi fourni, il doit valoir `service.handyman_id`, sinon 400 `handyman_mismatch`.
3. Sans `service` : `handyman` doit avoir un profil `publishable()`, sinon 400 `handyman_unavailable`.
4. `handyman == request.user` : 400 `self_booking_forbidden`.

Ces erreurs utilisent le format codé (§4.0). **Les réservations existantes ne sont jamais revalidées** : lecture, transitions, suivi, avis et litiges restent possibles quelle que soit la publication de l'artisan.

### 3.5 Badges et séparation des vérifications

| Payload | Champ | Source |
|---|---|---|
| `Me`, bloc `user` du login | `phone_verified` | `phone_verified_at is not None` |
| `Me.capabilities.handyman` | `identity_verified`, `verification_level` | voir ci-dessous |
| Payloads publics (`PublicArtisanMini`, `PublicHandyman`, featured, services) | `identity_verified` | `kyc_status == 'approved' and verification_level in ('provider', 'provider_reviewed')` |
| idem | `verification` | `"identity_verified"`, `"document_checked"` (cas D, mention « Pièce contrôlée par Tratra ») ou `null` |
| `UserMiniSerializer` (contrepartie d'une réservation) | `phone_verified` | remplace `is_verified` |

- **`is_verified` n'est plus émis nulle part** : retiré de `Me` et de `UserMini` en L3a (aucun client ne le lit : vérifié par `grep` dans React et Flutter), retiré des payloads publics dans le train R3 en même temps que la bascule de React sur `identity_verified` (L7d). Aucun alias.
- **`is_approved` n'est plus émis dans aucun payload public** à partir de R3 (X-4).
- Le badge « Identité vérifiée » lit **uniquement** `identity_verified === true` ; aucune chaîne de repli côté client.
- Test de contrat : aucune clé `is_verified` ni `is_approved` dans les payloads publics et dans `Me`.
- Avant R3, le payload public garde `is_verified = is_approved` (état legacy, aucune nouvelle approbation possible depuis R1).

### 3.6 Retrait immédiat : caches

- **API** : aucun cache sur les listes. `public_stats` (60 s) : `cache.delete` après le commit de toute publication ou dépublication.
- **Next.js** (dans le train R3) :
  - `/artisans/[id]` : `cache: "no-store"` (le retrait doit être immédiat sur la page de profil) ;
  - pages de listes (`/`, `/search`) : fetchs publics tagués (`public-services`, `public-artisans`, `public-stats`), `revalidate` ramené à 60 s comme borne ;
  - route `POST /api/revalidate` protégée par `X-Revalidate-Secret`, appelée par la tâche Celery `revalidate_public_frontend(tags)` après le commit, avec nouvel essai ;
  - `sitemap.ts` revalidé par le tag `public-artisans`.
- **Rendu serveur** : les appels SSR de Next partent d'une seule IP. Ils portent `X-Internal-Render: <horodatage>.<HMAC(INTERNAL_RENDER_SECRET)>` (fenêtre de 60 s), qui exempte du throttle anonyme **seulement** (jamais des quotas OTP ni des endpoints authentifiés). Le secret n'est jamais exposé au navigateur.
- **Service worker** : les réponses `/handy` ne sont jamais mises en cache (`NEVER_CACHE`).

---

## 4. Contrats API (communs à React et Flutter)

### 4.0 Conventions

- **Format d'erreur codé** (D13). Toute réponse qui porte un code de l'annexe D a la forme suivante, **quel que soit l'endpoint**, ancien ou nouveau :

```json
{ "code": "otp_invalid", "detail": "Code invalide ou expiré.", "attempts_left": 3 }
{ "code": "validation_error", "detail": "Certains champs sont invalides.",
  "fields": { "phone": [{"code": "invalid_phone", "message": "Numéro invalide."}] } }
```

  - Mécanisme : `handy/api/errors.CodedAPIException(code, detail, status, **extra)`, levée aussi par les vues existantes (`POST /bookings/`, `presence`, `payment_initiate`, `payouts`, `services`, `handyman-docs`) ; un gestionnaire global (`EXCEPTION_HANDLER`) la sérialise. Les erreurs de validation des **nouveaux** serializers deviennent `validation_error`, avec un `code` par message (`ErrorDetail.code`). Les autres erreurs DRF des endpoints existants gardent leur format.
  - Clés complémentaires documentées par endpoint : `attempts_left`, `resend_in`, `retry_after`, `missing`, `missing_for_online`, `challenge`.
  - 429 DRF → `{"code":"throttled","detail":"…","retry_after":42}` et en-tête `Retry-After` (exposé par CORS).
  - Un test par endpoint existant qui émet un code vérifie la forme (§9.1).
- **En-têtes clients** :
  - `X-Tratra-Client: web|android|ios` : `web` active le mode cookie (§5.6) ; sa présence active aussi les comportements « nouveaux clients » (401 au login, A14) ;
  - `X-Tratra-App-Version` (mobile), comparé à `min_app_version` (§4.13) ;
  - `X-Tratra-Device: <jeton>` (mobile) ou cookie `tratra_dev` (web, HttpOnly, `Path=/handy/auth/`) : jeton d'appareil connu (§5.3).
  - Ajoutés à `CORS_ALLOW_HEADERS`.
- **Jetons émis** par `login`, `register/verify`, `register/claim`, `password/change`, `phone/change/confirm`, `mfa/verify` et `refresh` : bearer `{"access","refresh"}` ; web `{"access"}` et `Set-Cookie: tratra_rt=…; HttpOnly; Secure; SameSite=Strict; Path=/handy/auth/`.
- **Cache** : toute réponse d'une requête authentifiée, et toute réponse sous `/handy/auth/` et `/handy/admin/`, porte `Cache-Control: no-store, private` et `Vary: Authorization, Cookie` (middleware L2).
- **Pagination** : `{count,next,previous,results}` (20 par page, `page_size` jusqu'à 100).
- **Défi anti-bot** (C11) : quand `OtpService` le demande (§5.1), la réponse est **428** `challenge_required` avec `"challenge": {"provider": "turnstile", "site_key": "…"}` ; le client renvoie la même requête avec `"challenge_token"`. Jeton invalide : 400 `challenge_failed`.
- **Throttles** DRF (clé IP = IPv4 ou préfixe /64, §5.3). Les seuils IP sont des **plafonds durs larges** à cause du CGNAT ; les limites fines sont par numéro, par préfixe et par identifiant (§5.1, §5.3).

| Scope | Taux | Endpoints |
|---|---|---|
| `login` | 60/min/IP | `auth/login/`, `auth/register/claim/` |
| `auth_register` | 30/h/IP | `auth/register/` |
| `otp_verify` | 60/h/IP | vérifications de code |
| `otp_send` | 300/h/IP | `otp/resend/`, `password/reset/`, demandes `phone/*`, `payout-account/` (étape 1) |
| `password_reset` | 60/h/IP | `password/reset/`, `password/reset/confirm/` |
| `sensitive_user` | 10/h/utilisateur | `password/change/`, `phone/change/`, `users/me/deactivate/`, changement d'email, `payout-account/` |
| `mfa_verify` | 5/min/utilisateur | `auth/mfa/verify/` |
| `kyc_upload` | 60/h/utilisateur | uploads KYC et justificatifs |
| `kyc_submit` | 10/jour/utilisateur | `kyc/submit/` |
| `webhook` | 120/min | webhook prestataire |
| `admin_kyc_evidence` | 60/h/utilisateur, alerte au-delà de 30 | fichiers de preuve |

### 4.1 Inscription, OTP et revendication de compte

**`POST /handy/auth/register/`** (anonyme) :

```json
{ "phone": "+2250707123456", "first_name": "Awa", "last_name": "Koné", "password": "…",
  "accept_terms": true, "terms_version": "2026-10", "privacy_version": "2026-10", "challenge_token": null }
```

- `phone` : E.164 recommandé ; sans « + », région `CI`. Numéro **mobile** d'un pays de `OTP_ALLOWED_COUNTRIES`.
- `password` : `validate_password()` avec un `User` temporaire construit **à partir des seules données saisies** (noms, numéro), ce qui ne révèle rien d'un compte existant.
- `terms_version` et `privacy_version` doivent égaler les versions servies par `/public/legal/` (§4.13).
- Réponse **202**, **identique** quelle que soit la situation du numéro :

```json
{ "challenge_id": "0d6f3c4e-…", "expires_in": 300, "resend_in": 60, "masked_phone": "+225 07 •• •• •• 56" }
```

| Situation du numéro | Traitement |
|---|---|
| Libre, ou porté par un compte legacy **non vérifié** ou **désactivé** | Challenge `signup` réel (payload : mot de passe haché, noms, versions). La situation legacy n'est examinée qu'**après** l'OTP. |
| Porté par un compte **vérifié et actif** | Challenge **leurre** (même hachage, même écriture) ; SMS d'information au titulaire, au plus un par jour : « Une inscription Tratra a été tentée avec votre numéro. Si c'est vous, utilisez “Mot de passe oublié”. » |

- Erreurs : 400 `validation_error` (`fields.phone` : `invalid_phone`, `not_mobile`, `unsupported_country` ; `fields.password`) ; 400 `terms_not_accepted`, `terms_version_mismatch` ; 428 `challenge_required` ; 429 `throttled`, `otp_send_limit` ; 503 `signup_unavailable` (drapeau `PHONE_SIGNUP_ENABLED` faux, textes légaux absents, ou téléphones pas encore normalisés), `sms_unavailable`, `sms_budget_exceeded`.

**`POST /handy/auth/register/verify/`** `{"challenge_id","code"}` :
- **201** `{"access","refresh"?, "user": Me}` si le numéro est libre : compte créé (`username` généré, `phone_verified_at`, versions acceptées, `user_type='client'`), événement `signup_completed`.
- **409** `legacy_account_found` si le numéro est porté par un compte legacy non vérifié ou désactivé. La possession étant prouvée, l'existence du compte peut être révélée :

```json
{ "code": "legacy_account_found", "detail": "Un compte Tratra existe déjà avec ce numéro.",
  "claim_token": "…", "expires_in": 600,
  "account": {"masked_identifier": "a•••a@g•••.com", "joined": "2024-03", "deactivated": false},
  "options": ["claim", "recover", "create_new"] }
```

  `options` contient `recover` seulement si la politique de récupération le permet pour ce compte (§4.3, comptes sans valeur).
- 400 `otp_invalid` (`attempts_left`), `otp_expired`, `otp_locked`. Un leurre renvoie toujours `otp_invalid`.
- 409 `signup_conflict` : numéro vérifié entre-temps par un autre compte (course rarissime).

**`POST /handy/auth/register/claim/`** (anonyme, throttle `login`) :

| Corps | Effet | Réponse |
|---|---|---|
| `{"claim_token","action":"claim","password"}` | Vérifie le mot de passe **du compte legacy** (garde par compte appliquée, 5 essais par revendication). Rattache le numéro vérifié, réactive le compte s'il était désactivé (`reactivated`), révoque ses anciennes sessions, `account_claimed`. Profil Handyman approuvé : ré-authentification exigée (§2.7). | 200 `{"access","refresh"?, "user": Me}` ; 400 `invalid_credentials` (`attempts_left`) |
| `{"claim_token","action":"recover","new_password"}` | Seulement si `recover` figurait dans `options`. Nouveau mot de passe, numéro vérifié, sessions révoquées, `account_recovered`, retenue des versements (§4.6). Pas de connexion automatique. | 200 `{"detail":"Compte récupéré. Connectez-vous."}` ; 409 `support_required` |
| `{"claim_token","action":"create_new"}` | Crée le nouveau compte à partir du payload ; le numéro est retiré du compte legacy (`phone_released`, notification in-app sur l'ancien compte). | 201 `{"access","refresh"?, "user": Me}` |

Erreurs communes : 400 `claim_invalid` (jeton expiré, déjà utilisé ou inconnu).

**`POST /handy/auth/otp/resend/`** `{"challenge_id","challenge_token"?}` (anonyme pour `signup` et `password_reset` ; authentifié par le même utilisateur pour `phone_*` et `payout_change`) :
- **202** (même forme) : nouveau code, ancien code invalidé, `attempts` remis à 0.
- 428 `challenge_required` ; 429 `otp_cooldown` (`resend_in`), `otp_send_limit` ; 400 `challenge_expired`.

### 4.2 Connexion, refresh, déconnexion, MFA

**`POST /handy/auth/login/`** (route `jwt-login` existante) :

```json
{ "phone": "+2250707123456", "password": "…" }               // nouveau
{ "username": "<username|email|téléphone>", "password": "…" } // legacy, conservé
```

- **200** `{"access","refresh"?, "user": Me, "device_token"?: "…"}`. `user` est exactement `Me` (§4.4) ; les champs fantômes `profile_image` et `phone_number` disparaissent. `device_token` est renvoyé aux clients mobiles (le web reçoit le cookie `tratra_dev`). Pour un compte staff avec MFA enrôlé, `Me.capabilities.staff.mfa.verified` vaut `false` jusqu'à `mfa/verify`.
- Échec : **401** `invalid_credentials` pour les clients qui envoient `X-Tratra-Client` ; pour les autres, **400** `{"code":"invalid_credentials","detail":"…","non_field_errors":["…"]}` jusqu'en L11 (A14). Message unique : compte inconnu, mot de passe faux ou compte inactif.
- **429** `too_many_attempts` (`retry_after`) : verrou axes ou garde par compte ; 429 `throttled`.

**`POST /handy/auth/refresh/`** :
- Bearer : `{"refresh"}` → 200 `{"access","refresh"}`.
- Web : corps `{}`, cookie `tratra_rt`, `X-Tratra-Client: web` **et** `Origin` présente dans `CORS_ALLOWED_ORIGINS` (jamais `null`) → 200 `{"access"}` et nouveau cookie.
- Migration d'une session web bearer : `{"refresh"}` **et** `X-Tratra-Client: web` → rotation, pose du cookie, réponse sans `refresh` (utilisé une fois par le bundle L4).
- Rotation atomique et détection de réutilisation (§5.6).
- Erreurs : 401 `token_not_valid`, `session_revoked`, `account_inactive` ; 403 `csrf_failed`.

**`POST /handy/auth/logout/`** : `{"refresh"}` ou cookie → 200 `{}` ; refresh en liste noire, cookie effacé, `jti` de l'access présenté (en-tête `Authorization`) mis en liste de refus jusqu'à son expiration.

**`POST /handy/auth/logout/all/`** (authentifié) → 200 `{}` : `session_version` + 1, refresh en liste noire, `sessions_revoked`.

**`POST /handy/auth/mfa/verify/`** (authentifié, compte staff avec un appareil TOTP) `{"code"}` → 200 jetons neufs portant `amr=["pwd","otp"]` ; 400 `mfa_invalid` ; 409 `mfa_not_enrolled`. Les routes `/handy/admin/*` répondent 403 `mfa_required` sans ce claim (§1.7).

### 4.3 Mot de passe

**`POST /handy/auth/password/reset/`** (anonyme) `{"phone","challenge_token"?}` → **202** identique (forme challenge) dans tous les cas. Le message affiché par les clients : « Si un compte correspond à ce numéro, vous recevrez un code par SMS. Sinon, contactez le support. »

| Compte trouvé | Traitement |
|---|---|
| Actif, numéro vérifié, **non staff** (ni `is_staff`, ni permission `kyc_*`, `resolve_dispute`, `manage_payouts`) | Challenge réel `password_reset` |
| Legacy, numéro normalisé non vérifié, `RESET_ALLOW_UNVERIFIED_LEGACY=true` et **sans valeur** (ni `HandymanProfile`, ni `PayoutAccount`, ni solde, ni réservation payée) | Challenge réel |
| Staff, compte « à valeur » non vérifié, inconnu | Leurre, aucun SMS (procédure support) |

**`POST /handy/auth/password/reset/confirm/`** `{"challenge_id","code","new_password"}`, dans cet ordre :
1. `new_password` validé par les seuls validateurs **indépendants de l'utilisateur** (longueur 8 à 128, mot de passe courant, entièrement numérique), avec un utilisateur neutre ; échec → 400 `validation_error`, aucun essai consommé. Réponse identique pour un leurre et un vrai challenge.
2. Vérification du code (un échec consomme un essai) → 400 `otp_invalid`, `otp_expired`, `otp_locked`. Un leurre échoue toujours ici.
3. Code juste : `code_verified_at` est posé, puis le validateur de similarité est appliqué avec le vrai compte. Échec → 400 `validation_error` (`password_too_similar`) **sans consommer le challenge** : le client renvoie un autre mot de passe avec le même code (pas de nouvel essai décompté tant que `code_verified_at` est posé). Seul le détenteur du code atteint cette étape : pas d'oracle.
4. Succès → **200** `{"detail":"Mot de passe modifié. Vous pouvez vous connecter."}`. Effets : nouveau mot de passe ; `phone_verified_at` s'il était vide ; révocation de toutes les sessions ; remise à zéro d'axes et de la garde ; SMS « Votre mot de passe Tratra a été modifié » ; `payout_hold_until = now + 72 h` ; ré-authentification exigée si profil Handyman approuvé ; `password_reset`. **Pas de connexion automatique.**

**`POST /handy/auth/password/change/`** (authentifié) `{"current_password","new_password"}` → **200** avec des jetons neufs (les autres sessions sont révoquées) ; 400 `invalid_current_password` (compté par la garde), 400 `validation_error`.

### 4.4 `/users/me/`, profil et email

**`GET /handy/users/me/`** → 200 `Me` (même forme pour `/users/{id}/` sur soi-même et pour le bloc `user` du login) :

```json
{
  "id": 8, "username": "u3fa91c0d2e",
  "first_name": "Awa", "last_name": "Koné", "display_name": "Awa K.",
  "phone": "+2250707123456", "phone_verified": true, "phone_verified_at": "2026-10-20T09:12:00+00:00",
  "email": null, "email_verified": false, "email_pending": null,
  "profile_picture": "https://api.tratra.net/media/profile_pics/9d2c….jpg",
  "address": "Rue des Jardins", "commune": "Cocody", "quartier": "Riviera 2",
  "city": "Abidjan", "postal_code": null, "country": "CI",
  "preferences": {"notifications": {"sms": true}},
  "date_joined": "2026-10-20T09:12:00+00:00",
  "user_type": "client",
  "capabilities": {
    "phone_verified": true, "can_book": true, "can_apply_handyman": true,
    "handyman": {
      "profile_id": 2, "status": "in_review", "kyc_status": "review",
      "identity_verified": false, "verification_level": "",
      "publishable": false, "published": false,
      "missing": ["kyc_approved"], "missing_for_online": ["location"],
      "online": false, "can_go_online": false, "can_resubmit": false,
      "reauth_required": false, "status_message": ""
    },
    "company": null,
    "staff": null
  }
}
```

- `user_type` : déprécié, lecture seule, retiré en L11. `is_verified` n'existe plus (§3.5).
- `can_book` = `is_active and (phone_verified or not BOOKING_REQUIRES_PHONE_VERIFIED)` ; `can_apply_handyman` = `is_active`.
- `handyman` vaut `null` sans profil. `status` : `draft` ; `in_review` (`pending` ou `review`) ; `active` (`approved` et publié) ; `incomplete` (`approved`, non publié) ; `rejected` ; `suspended`.
- **Avant L5a** (trains R1 et R2), la forme est la même, avec la correspondance : `status="legacy"`, `kyc_status=null`, `identity_verified=false`, `verification_level=""`, `publishable = published = is_approved and user.is_active`, `missing=[]`, `missing_for_online = []` si `location` est renseignée, sinon `["location"]`, `can_go_online = is_approved and user.is_active`, `can_resubmit=false`, `reauth_required=false`. Fixture de contrat « pré-L5 ».
- `company` : `{"profile_id": 3, "verified": false}` si un `CompanyProfile` existe.
- `staff` (si `is_staff`) : `{"is_staff": true, "is_superuser": false, "mfa": {"enrolled": true, "verified": false}, "permissions": ["kyc_view_queue", "kyc_decide", …]}` (codenames sans préfixe).

**`PATCH /handy/users/me/`** (et `PATCH /users/{id}/` sur soi-même ; sur autrui : 403) : `first_name`, `last_name`, `email`, `address`, `commune`, `quartier`, `city`, `postal_code`, `country`, `preferences` (objet complet validé), `latitude`/`longitude` (legacy).
- **200** `Me`.
- `phone` : accepté sans effet s'il est égal au numéro actuel une fois normalisé (anciennes apps qui renvoient tout le profil) ; sinon 400 `phone_change_requires_otp`. `password` → 400 `password_change_endpoint`.
- **409** `names_locked_by_kyc` : noms modifiés alors que `kyc_status` vaut `pending`, `review`, `approved` ou `suspended`.
- **Email** : une nouvelle valeur (ou une première valeur) est placée dans `email_pending` et un lien de vérification est envoyé ; la réponse est **identique** que l'adresse soit libre ou déjà prise. `email: null` efface l'email actuel (et `email_login_legacy`). Si `EMAIL_VERIFICATION_ENABLED` est faux, le champ email n'est pas modifiable (400 `email_change_unavailable`) et les clients l'affichent en lecture seule (indiqué par `/public/config/`).
- `username`, `user_type` : ignorés.

**`POST /handy/users/me/email/verify/`** (anonyme, le lien peut être ouvert sur un autre appareil) `{"token"}` : jeton `TimestampSigner` (48 h) portant `user_id`, l'email et `session_version`. → 200 `{"detail":"Adresse vérifiée."}` (l'email devient identifiant de connexion) ; 400 `email_link_invalid` ; 409 `email_unavailable` (adresse prise entre-temps : seul le détenteur de la boîte le voit).

**`POST /handy/users/me/deactivate/`** `{"current_password"}` → **204** : `is_active=False`, `deactivated_at`, sessions révoquées, profil Handyman dépublié. Aucune donnée supprimée ; réactivation par la revendication (§4.1) ou par le support (`reactivated`). 400 `invalid_current_password`. `DELETE /users/{id}/` reste en 405 (depuis L1a).

**`PUT /handy/users/me/photo/`** (multipart `photo`) : JPEG, PNG ou WebP, 5 Mo au plus, vérifiée par Pillow, **réencodée** en JPEG 512×512 max sans EXIF, stockée sous `profile_pics/<uuid>.jpg` → 200 `{"profile_picture": url}`. La photo est publique pour un Handyman (avertissement affiché par les clients). **`DELETE`** → 204.

### 4.5 Téléphone

**`POST /handy/users/me/phone/verify/`** `{}` : vérification du numéro **actuel** (comptes legacy) → 202 (forme challenge) ; 400 `no_phone`, `already_verified`. Si un autre compte a déjà vérifié ce numéro : leurre et SMS d'information au titulaire.

**`POST /handy/users/me/phone/verify/confirm/`** `{"challenge_id","code"}` → 200 `Me`.

**`POST /handy/users/me/phone/change/`** `{"new_phone","current_password"}` → 202 (code envoyé au **nouveau** numéro) ; 400 `invalid_current_password`, `same_phone`, `validation_error`. Numéro pris par un compte vérifié : leurre et SMS d'information.

**`POST /handy/users/me/phone/change/confirm/`** `{"challenge_id","code"}` → 200 `{"access","refresh"?, "user": Me}`. Effets : nouveau numéro vérifié (s'il était porté par un compte legacy non vérifié, il lui est retiré : `phone_released`) ; ancien numéro masqué dans l'événement `phone_changed` ; sessions révoquées (jetons neufs pour l'appareil courant) ; SMS à l'**ancien** numéro (« Votre numéro Tratra a été modifié. Si ce n'est pas vous, contactez le support. ») ; `payout_hold_until = now + 72 h` ; ré-authentification exigée si profil Handyman approuvé.

**Legacy** `POST /handy/auth/otp/request/` et `/auth/otp/verify/` : correspondent à `phone_verify` ; `request` → 201 `{"sent":true,"challenge_id",…}` **sans jamais de code**, DEBUG compris ; `verify` accepte `{"code"}` (dernier challenge ouvert) ou `{"challenge_id","code"}` → 200 `{"verified":true}`.

### 4.6 Compte de versement et retenue

**`GET /handy/payout-account/`** : inchangé.

**`POST /handy/payout-account/`** (création ou modification) : corps existant plus `current_password`.
- Nouveaux clients : → **202** (forme challenge, usage `payout_change`, code envoyé au numéro **vérifié**) ; le payload du challenge contient l'empreinte des données demandées. 400 `invalid_current_password` ; 403 `phone_verification_required`.
- **`POST /handy/payout-account/confirm/`** `{"challenge_id","code"}` : applique **exactement** les données dont l'empreinte a été confirmée (sinon 409 `step_up_mismatch`), `verified=False`, `payout_hold_until = now + 72 h`, `payout_account_changed`, SMS de notification → 200 `PayoutAccount`.
- Anciens clients (sans `X-Tratra-Client`) : 403 `step_up_required` avec le message « Mettez à jour l'application pour modifier votre compte de versement » (Arbitrages A21).

Retenue : `payout_hold_until` est posé par la réinitialisation, la revendication (`recover`), le changement de numéro et le changement de compte de versement. Pendant la retenue, `POST /payouts/` → 409 `payouts_on_hold` (`retry_after`) ; la date est exposée dans le payload du compte de versement.

### 4.7 Candidature Handyman et services

**`POST /handy/users/me/handyman/`** (L3b, corps vide) : crée un profil vide (T1) s'il n'existe pas → 201, sinon 200 ; 403 `account_inactive`. C'est le seul point de création avant L6 (« Devenir artisan » en R2) ; il reste ensuite disponible.

**`GET /handy/users/me/handyman/`** (L6) → 200 `Application`, ou 404 `no_handyman_profile` :

```json
{
  "id": 2, "user_id": 8, "kyc_status": "draft", "status": "draft",
  "identity_verified": false, "verification_level": "", "is_published": false, "publishable": false,
  "missing": ["kyc_approved", "services"], "missing_for_online": ["location"], "online": false,
  "bio": "Plombier depuis 2019, interventions rapides…",
  "trades": [{"id": 1, "name": "Plomberie", "slug": "plomberie"}],
  "specialties": [{"id": 51, "name": "Chauffe-eau", "slug": "chauffe-eau", "parent": 1}],
  "specialties_extra": ["Détection de fuites"],
  "experience_years": 5, "commune": "Cocody", "quartier": "Riviera 2",
  "service_area": {"lat": 5.35, "lng": -3.98, "radius_km": 10},
  "hourly_rate": "5000.00", "daily_rate": "30000.00", "travel_fee": "0.00",
  "availability_slots": [{"weekday": 0, "start": "08:00", "end": "18:00"}],
  "legacy_availability": null, "legacy_constraints_violations": [],
  "services_count": 0, "photo": null, "created_at": "…", "updated_at": "…"
}
```

**`PUT /handy/users/me/handyman/`** (création ou remplacement) et **`PATCH`** (partiel) :

```json
{ "bio": "…", "trade_ids": [1], "specialty_ids": [51], "specialties_extra": ["Détection de fuites"],
  "experience_years": 5, "commune": "Cocody", "quartier": "Riviera 2",
  "service_area": {"lat": 5.35, "lng": -3.98, "radius_km": 10},
  "hourly_rate": "5000", "daily_rate": "30000", "travel_fee": "0",
  "availability_slots": [{"weekday": 0, "start": "08:00", "end": "18:00"}],
  "create_only": false }
```

- `PUT` → **201** à la création (T1), 200 sinon. `PATCH` → 200, ou 404 sans profil.
- `create_only: true` (envoyé par le formulaire public, §7.3) : si un profil existe déjà → **409** `handyman_profile_exists` avec `{"status": "<handyman.status>"}` ; rien n'est écrit.
- Règles du §1.5 appliquées aux seuls champs présents. `legacy_constraints_violations` liste les écarts d'un profil legacy (par exemple `["too_many_trades", "bio_too_short"]`) ; l'interface demande un choix explicite avant d'envoyer le champ.
- `availability_slots`, s'il est fourni, **remplace** les créneaux ; `service_area: null` supprime la zone.
- Erreurs : 403 `account_inactive` ; **409** `profile_suspended` ; 400 `validation_error` (`trade_required`, `too_many_trades`, `specialty_without_trade`, `too_many_specialties`, `unknown_commune`, `invalid_slot`, `overlapping_slots`, `rate_required`, `bio_too_short`).
- Aucun champ réservé (§1.5), ni `user`, `rating` ou `online`, n'est accepté en écriture.
- Legacy `PATCH /handy/handymen/{id}/` (propriétaire) : même serializer. `POST` et `DELETE /handymen/` → 405.

**Mes services** (exigence 4 « Proposer un service », condition 11 du §3.1) : endpoints existants, sécurisés en L1a.
- `GET /handy/services/?handyman=<mon id>` : mes services, actifs ou non.
- `POST /handy/services/` : `handyman` forcé à `request.user` ; profil Handyman requis (403 `handyman_profile_required`) ; pour un nouveau service ou un changement de catégorie, la catégorie doit être un métier du profil ou une de ses sous-catégories (400 `category_not_in_trades`) ; `title`, `description`, `price_type`, `price` et `duration` obligatoires dans ce cas.
- `PATCH`, `DELETE /handy/services/{id}/` : propriétaire ; `DELETE` désactive si des réservations existent.
- `POST /handy/service-images/` (propriétaire du service ; `service` en lecture seule ensuite), images réencodées sans EXIF.
- `Service.image_url` : accepté seulement en `https` vers les hôtes de stockage du projet (`MEDIA_PUBLIC_HOSTS`), sinon 400 `invalid_image_url`.

**`POST /handy/handymen/presence/`** `{"online": bool}` : §3.3.

### 4.8 KYC côté candidat

Toutes les routes sont sous `/handy/users/me/handyman/kyc/` et exigent un profil (sinon 404 `no_handyman_profile`). En production, `KYC_SUBMISSIONS_ENABLED=false` → 503 `kyc_unavailable` sur les écritures ; les uploads de selfie et de liveness exigent en plus `KYC_LEGAL_APPROVAL_REF` (C6).

**`GET …/kyc/`** → 200 `KycOverview` :

```json
{
  "kyc_status": "draft", "mode": "provider", "submissions_enabled": true,
  "capture": {"channel": "sdk_web", "auto_approval_possible": true},
  "can_submit": false, "can_resubmit": false, "attempts_used": 0, "attempts_max": 3,
  "decision": null, "reauth": null,
  "consent": {"version": "2026-10-v1", "granted": false, "granted_at": null,
              "text": "…texte intégral servi depuis handy/legal/kyc_consent/…", "sha256": "…",
              "privacy_url": "/confidentialite"},
  "requirements": {
    "id_types": [{"code": "IDENTITY_CARD", "label": "Carte nationale d'identité", "has_back": true}],
    "liveness_frames": {"min": 6, "max": 8},
    "max_bytes": {"id_front": 4194304, "id_back": 4194304, "selfie": 1048576, "liveness_frame": 307200},
    "content_types": {"id_front": ["image/jpeg","image/png"], "id_back": ["image/jpeg","image/png"],
                      "selfie": ["image/jpeg"], "liveness_frame": ["image/jpeg"]},
    "min_long_side_px": {"id_front": 1000, "id_back": 1000, "selfie": 640, "liveness_frame": 480},
    "target_long_side_px": {"id_front": 2400, "id_back": 2400, "selfie": 1280, "liveness_frame": 640}
  },
  "submission": {"id": "a1b2…", "attempt": 1, "purpose": "verification", "status": "draft",
                 "id_type": "IDENTITY_CARD", "capture_channel": "inhouse_web",
                 "documents": [{"id": "c3d4…", "kind": "id_front", "sequence": null, "content_type": "image/jpeg",
                                "size": 812345, "uploaded_at": "…"}],
                 "missing": ["id_back", "selfie", "liveness_frames"], "submitted_at": null}
}
```

- `capture.channel` : `sdk_web` si l'en-tête vaut `web`, que le prestataire est configuré et que `KYC_WEB_CAPTURE=sdk` (après L0 et L10) ; sinon `inhouse_web`, `inhouse_android` ou `inhouse_ios`. `auto_approval_possible` n'est vrai que pour `sdk_web` (D8).
- Les valeurs de `requirements` sont celles validées en L0 (§10) ; les clients les lisent, aucune n'est codée en dur.
- `decision` après rejet ou révocation : `{"outcome","reason_code","message","decided_at","resubmission_allowed"}`. `reauth` si exigée : `{"reason","since","submission_status"}`.
- **Aucun** lien de stockage ni résultat prestataire n'est renvoyé.

**`POST …/kyc/consent/`** `{"version","accepted":true}` → 201 `{"version","granted_at"}`. Crée la tentative `draft` si nécessaire (sous verrou du profil) et y rattache le consentement. 400 `consent_version_mismatch`, `consent_not_accepted`.

**`POST …/kyc/documents/`** (multipart : `kind` = `id_front` ou `id_back`, `file`, `id_type` facultatif sur `id_front`) → 201 `KycDocument`.
- **409 `consent_required`** sans consentement de la version courante rattaché à la tentative. Si la version courante a changé depuis : 409 `consent_version_mismatch`, et les pièces non soumises de la tentative sont marquées remplacées (`documents_purged`).
- Un nouvel `id_front` ou `id_back` remplace l'ancien (`superseded_at`). Au plus **10 remplacements** par type et par tentative (409 `too_many_replacements`) ; quota de **200 Mo** par profil (409 `storage_quota_exceeded`).
- Erreurs : 400 `invalid_file` (type, taille, dimensions, signature binaire) ; 409 `kyc_not_editable`, `resubmission_not_allowed`, `attempts_exhausted`.

**`POST …/kyc/liveness/`** (multipart : `selfie`, `frames` répété 6 à 8 fois dans l'ordre, `capture_meta` JSON **non fiable**, affiché au reviewer seulement) → 201 `{"documents":[…]}` ; remplacement atomique de l'ensemble ; mêmes règles et erreurs, plus 400 `frames_count`.

**`DELETE …/kyc/documents/{id}/`** → 204 (brouillon seulement : `superseded_at`) ; 409 `kyc_not_editable`.

**`GET …/kyc/documents/{id}/file/`** → binaire déchiffré, propriétaire seulement, pièces de la tentative courante ou de la dernière ; en-têtes du §5.9.

**`POST …/kyc/provider-session/`** (L10, canal `sdk_web`) → 201 `{"token","partner_id","environment","product":"document_verification","job_id","partner_params":{"submission_id","attempt"}}`. Exige le consentement courant ; crée la tentative et fige `capture_channel=sdk_web`. Le jeton v3 est émis par le backend pour `user_id = kyc_subject_id` ; la clé API ne quitte jamais le serveur.

**`POST …/kyc/submit/`** `{"id_type":"IDENTITY_CARD"}` → **202** `KycOverview` (`pending` ou `review`).
- 409 `consent_required` ; 400 `kyc_incomplete` (`missing`), `application_incomplete` (`missing` selon §3.1) ; 409 `kyc_not_editable`, `resubmission_not_allowed`, `attempts_exhausted` ; 403 `phone_verification_required`.
- Canal SDK : le submit confirme la fin de la capture côté client (`job_id` attendu) ; le résultat arrive par relecture (§5.8).

**`POST …/kyc/reauth/`** (multipart `selfie`, `frames`) : seulement si `reauth_required` → 202 ; crée une soumission `purpose=reauth` en `review` (§2.7) ; mêmes contrôles de fichiers et de consentement.

### 4.9 Justificatifs (`HandymanProof`, L6)

- **`GET /handy/users/me/handyman/proofs/`** → 200 `[{"id","proof_type","title","content_type","size","status","review_note","uploaded_at"}]` (actifs).
- **`POST …/proofs/`** (multipart `proof_type`, `title`, `file` : PDF, JPEG ou PNG, 10 Mo) → 201 ; 400 `invalid_file`, `too_many_proofs` (5 actifs) ; 409 `profile_suspended`. Modifiable dans tous les états sauf `suspended`, indépendamment des tentatives KYC.
- **`DELETE …/proofs/{id}/`** → 204 (`superseded_at`, fichier conservé).
- **`GET …/proofs/{id}/file/`** → binaire (propriétaire) ; un PDF est servi en `Content-Disposition: attachment`.

### 4.10 Webhook prestataire

**`POST /handy/kyc/webhooks/smile-id/`** : `authentication_classes=[]`, `AllowAny`, exempté de CSRF, scope `webhook`, corps limité à 256 Ko et **non lu**.
1. Signature `Response-Signature` contre `Response-Timestamp` (§5.8). Invalide → **401**, **aucune écriture en base** ; compteur Redis `kyc:webhook:badsig:<heure>`, alerte Sentry au-delà de 20 par heure.
2. Fraîcheur ±300 s, sinon 400 `stale` (ligne `KycWebhookEvent`, signature valide).
3. `Job-ID` (en-tête) → soumission par `provider_job_id`. Inconnue → 200 (`unknown_job`). Même couple (job, horodatage) déjà reçu → 200 (`duplicate`, contrainte `kyc_webhook_once`).
4. Sinon : `KycWebhookEvent(outcome=queued)`, tâche `kyc_fetch_provider_result(submission_id)` après le commit, **200** `{"ok":true}`. La tâche relit le résultat par l'appel authentifié ; le webhook n'a déclenché qu'une relecture anticipée.

### 4.11 Admin KYC (`/handy/admin/kyc/…`)

Toutes les routes exigent la permission indiquée **et** la MFA (§1.7, règle 3). Règle « pas son propre dossier » partout (403 `self_review_forbidden`).

| Méthode et chemin | Permission | Corps et paramètres | Réponse |
|---|---|---|---|
| `GET stats/` | `kyc_view_queue` | — | `{"review":12,"pending":3,"approved":40,"rejected":7,"suspended":1,"legacy_review":5,"awaiting_second_approval":2,"reauth_required":1,"oldest_review_hours":30}` |
| `GET submissions/` | `kyc_view_queue` | `status`, `mode`, `purpose`, `capture_channel`, `legacy=1`, `flag`, `provider_status`, `awaiting_second=1`, `q` (nom, téléphone exact, `kyc_subject_id`), `claimed=me\|none`, `ordering`, `page` | Page de `{"id","profile_id","applicant":{"user_id","display_name","phone_masked"},"status","profile_status","mode","purpose","capture_channel","attempt","provider_status","flags","submitted_at","age_hours","claimed_by","pending_approval_by"}` ; tri par défaut : `submitted_at` croissant (valeur jamais nulle, §6.4) |
| `GET submissions/{id}/` | `kyc_view_queue` | — | Détail ci-dessous |
| `POST submissions/{id}/claim/`, `…/release/` | `kyc_decide` | — | 200 ; 409 `submission_claimed_by_other` |
| `POST submissions/{id}/decision/` | selon le cas (§2.3) | voir ci-dessous | 200 `{"submission","profile":{"id","kyc_status","is_published"}}` ; **202** `{"status":"awaiting_second_approval"}` |
| `POST submissions/{id}/retry-provider/` | `kyc_decide` | — | 202 ; 409 `provider_not_configured` |
| `POST submissions/{id}/break-glass/` | `kyc_override` | `{"reason"}` (20 caractères minimum) | 200 ; ouvre 30 min d'accès aux preuves de cette soumission, audit `evidence_break_glass`, alerte |
| `GET documents/{id}/file/` | `kyc_view_evidence` | — | binaire déchiffré (§5.9), audit `evidence_viewed` ; 403 `evidence_scope` hors périmètre |
| `GET profiles/` | `kyc_view_queue` | `kyc_status`, `legacy=1`, `published`, `reauth=1`, `funds_frozen=1`, `q`, `page` | Page de profils (point d'entrée de T11, T12, T14) |
| `GET profiles/{id}/` | `kyc_view_queue` | — | `{"profile","submissions","proofs","history"}` (historique si `kyc_view_audit`) |
| `POST profiles/{id}/suspend/` | `kyc_suspend` | `{"reason_code","user_message","internal_note"}` | 200 |
| `POST profiles/{id}/reinstate/` | `kyc_suspend` | `{"internal_note"}` | 200 ; 409 `invalid_transition` |
| `POST profiles/{id}/revoke/` | `kyc_suspend` | `{"reason_code","user_message","internal_note","resubmission_allowed"}` | 200 |
| `POST profiles/{id}/allow-resubmission/` | `kyc_suspend` | `{"internal_note"}` | 200 |
| `POST profiles/{id}/release-funds/` | `kyc_override` | `{"internal_note"}` | 200 (`funds_released`) |
| `POST proofs/{id}/review/` | `kyc_decide` | `{"status":"accepted\|rejected","note"}` | 200 |
| `GET reason-codes/` | `kyc_view_queue` | — | annexe B `{"code","label","default_user_message","resubmission_default","applies_to"}` |

Détail d'une soumission (`GET submissions/{id}/`) :

```json
{
  "id": "…", "attempt": 2, "purpose": "verification", "status": "review", "mode": "provider",
  "capture_channel": "inhouse_android", "id_type": "IDENTITY_CARD",
  "applicant": {"user_id": 8, "full_name": "Awa Koné", "phone_masked": "+225 07 •• •• •• 56",
                "account_created_at": "…", "phone_verified": true, "is_active": true},
  "application": { "…": "Application §4.7 sans données sensibles" },
  "documents": [{"id": "…", "kind": "id_front", "sequence": null, "source": "client", "content_type": "image/jpeg",
                 "size": 812345, "sha256": "…", "uploaded_at": "…", "viewed_by_me": false,
                 "download_url": "/handy/admin/kyc/documents/…/file/"}],
  "enrolled_selfie": null,
  "legacy_documents": [{"id": 14, "document_type": "id_card", "status": "approved",
                        "download_url": "/handy/handyman-docs/14/download/"}],
  "provider": {"status": "clear", "reason": null, "authenticated": true, "environment": "production",
               "checks": {"liveness": "passed", "selfie_to_id": "passed", "document_authenticity": "passed", "expiry": "passed"},
               "risk_level": "low", "completed_at": "…"},
  "flags": ["inhouse_capture"],
  "document": {"number_last4": "6789", "expires_on": "2030-05-01", "duplicates": []},
  "consent": {"version": "2026-10-v1", "granted_at": "…", "channel": "android"},
  "capture_metadata_untrusted": {"app_version": "2.0.0", "interval_ms_measured": [612, 590, 640]},
  "previous_attempts": [{"attempt": 1, "status": "rejected", "reason_code": "document_unreadable", "decided_at": "…"}],
  "claimed_by": null, "pending_approval": null,
  "approval_case": "B",
  "allowed_actions": ["claim", "approve", "reject", "request_resubmission"],
  "history": ["… KycAuditEvent si kyc_view_audit"]
}
```

- `download_url` est **relatif** ; `enrolled_selfie` est renseigné pour une soumission `purpose=reauth` (selfie de la dernière approbation).
- `allowed_actions` tient compte de l'état, des permissions, du cas d'approbation, des drapeaux, des preuves déjà consultées par l'utilisateur et de l'approbation en attente.

Corps des décisions :

```json
{"decision": "approve",
 "checklist": {"face_matches_document": true, "document_authentic": true, "names_match_account": true, "document_not_expired": true},
 "document_expires_on": "2030-05-01", "document_number": "C0123456789", "internal_note": "RAS"}

{"decision": "approve", "confirm": true, "checklist": {"…": true}, "internal_note": "Second contrôle conforme"}

{"decision": "reject", "reason_code": "suspected_fraud", "user_message": "…", "internal_note": "…", "resubmission_allowed": false}

{"decision": "request_resubmission", "reason_code": "document_unreadable", "user_message": "Photo du verso floue, merci de recommencer."}
```

- `document_number` est exigé si le résultat authentifié ne l'a pas fourni ; il n'est jamais stocké en clair (HMAC avec version de clé, quatre derniers caractères).
- Erreurs : 403 `permission_denied`, `self_review_forbidden`, `mfa_required` ; 409 `invalid_transition`, `manual_approval_disabled`, `submission_claimed_by_other`, `evidence_not_reviewed`, `duplicate_identity`, `second_approver_required`, `approval_case_not_met` ; 400 `checklist_incomplete`, `reason_required`, `document_expired`.

### 4.12 Endpoints existants : conservés, restreints ou dépréciés

| Endpoint | Sort | Détail | Lot |
|---|---|---|---|
| `POST /auth/login/` | Conservé | Accepte `phone` ; bloc `user` = `Me` ; 401 pour les nouveaux clients (A14) | L2, L3a |
| `POST /auth/refresh/`, `/auth/logout/` | Conservés | Mode cookie, claim `sv`, rotation atomique | L3a |
| `POST /users/` (inscription legacy) | Déprécié | L1a : `validate_password`, rôle `admin` interdit, `phone` **ignoré**, conflits d'email et de username sous `signup_unavailable` ; L11 : 410 avec « Mettez à jour l'application pour créer un compte. » | L1a, L11 |
| `GET /users/me/` | Conservé | Forme `Me` | L3b |
| `PATCH /users/{id}/` | Conservé (soi) | Règles de `PATCH /users/me/` ; autrui : 403 | L1b, L3b |
| `DELETE /users/{id}/` | 405 | Désactivation par `POST /users/me/deactivate/` | L1a, L3b |
| `POST /auth/otp/request/`, `/verify/` | Conservés | Jamais de code dans la réponse | L3a |
| `GET /handymen/`, `/handymen/{pk}/` | Restreints | Propriétaire ou `view_all_records` ; tiers : 404 | L1a |
| `PATCH /handymen/{id}/` | Restreint | Propriétaire, serializer de candidature | L1a, L6 |
| `POST /handymen/`, `DELETE /handymen/{id}/` | 405 | `PUT /users/me/handyman/` | L1a |
| `POST /handymen/presence/` | Conservé | `can_go_online` | L5a |
| `/handyman-docs/` | GET et download (propriétaire) | Tiers : superuser (L1b), puis `kyc_view_evidence` (L5b) ; écritures : `Deprecation` (L6), 410 (L11) | L1b, L5b, L6, L11 |
| `/service-images/` | Restreint au propriétaire | `service` en lecture seule après création | L1a |
| `POST /services/` | Restreint | `handyman` forcé ; profil requis | L1a |
| `POST /disputes/{id}/resolve/` | Restreint | `resolve_dispute` ; `self_dealing_forbidden` | L1b |
| `POST /payout-account/` | Durci | Mot de passe et OTP (§4.6) | L3b |
| `POST /bookings/{id}/confirm-completion/` | **Nouveau** | Le client confirme la fin : libération immédiate du séquestre | L1c |

### 4.13 Public, configuration et textes légaux

**`GET /handy/public/handymen/{user_id}/`** (`AllowAny`, `authentication_classes=[]`, **`user_id` = `User.id`**, cohérent avec `Service.handyman` et `featured.user_id`) → 200 si publiable, sinon **404** (non publié et inexistant indiscernables) :

```json
{
  "user_id": 8, "display_name": "Awa K.", "photo": "https://…",
  "identity_verified": true, "verification": "identity_verified",
  "bio": "…", "trades": [{"id":1,"name":"Plomberie","slug":"plomberie"}],
  "specialties": [{"id":51,"name":"Chauffe-eau","slug":"chauffe-eau","parent":1}], "specialties_extra": [],
  "experience_years": 5, "commune": "Cocody", "quartier": "Riviera 2", "service_radius_km": 10,
  "hourly_rate": "5000.00", "daily_rate": "30000.00", "travel_fee": "0.00",
  "availability_slots": [{"weekday": 0, "start": "08:00", "end": "18:00"}],
  "rating": 4.8, "reviews_count": 12, "completed_jobs": 31, "online": true,
  "member_since": "2026-10", "updated_at": "…",
  "services": ["… ServiceSerializer public, actifs, 20 au plus"],
  "recent_reviews": ["… PublicReviewSerializer, 5 au plus"]
}
```

`photo` = `User.profile_picture`, puis `HandymanProfile.photo` en repli. Jamais d'email, de téléphone, de position exacte, de numéro de pièce, de licence ou d'assurance, de statut KYC détaillé, ni `is_verified` ou `is_approved`.

**`GET /handy/public/handymen/`** (`AllowAny`) : profils `publishable()`, paginés (100 par page), `?fields=user_id,updated_at` pour le sitemap → `{"count","next","previous","results":[{"user_id","updated_at"}]}`.

**`GET /handy/public/config/`** (`AllowAny`, cache 5 min) :

```json
{
  "phone_signup": {"enabled": false, "allowed_countries": ["CI","SN","ML","BF","BJ","TG","NE","GN","GH","NG","FR","BE","CA","US"], "default_country": "CI"},
  "legal": {"terms": {"version": "2026-10", "url": "/cgu"}, "privacy": {"version": "2026-10", "url": "/confidentialite"}},
  "email_verification": {"enabled": true},
  "kyc": {"submissions_enabled": false, "mode": "manual", "consent_version": "2026-10-v1",
          "capture": {"web": "inhouse", "mobile": "inhouse"}},
  "antibot": {"provider": "turnstile", "site_key": "0x4AAA…"},
  "support": {"phone": null, "email": null, "whatsapp": null},
  "min_app_version": {"android": null, "ios": null}
}
```

Seules les valeurs réellement configurées sont renseignées (`support`, `min_app_version`, textes légaux) ; `null` sinon, et les clients masquent alors l'élément correspondant.

**`GET /handy/public/legal/{terms|privacy|kyc-consent}/`** → 200 `{"version","sha256","effective_at","content_markdown"}` servi depuis `handy/legal/<doc>/<version>.fr.md` (fichiers fournis ou validés par le juriste, C6) ; 404 si absent. `text_sha256` du consentement et les versions acceptées à l'inscription sont comparés à ces empreintes.

Endpoints existants inchangés en contrat mais filtrés par `public()` ou `publishable()` : `/handymen/featured/`, `/services/`, `/services/nearby/`, `/categories/`, `/public/stats/`, `/reviews/public/`, `/slides/`. Le payload public des artisans y remplace `is_verified` par `identity_verified` et `verification` à partir de R3, et `availability` y est nommé `availability_slots`.

### 4.14 Fixtures de contrat et textes partagés

- `handy/test_api_contract_fixtures.py` construit des payloads réels et les compare à `docs/api-contracts/*.json` (clés et types) ; `UPDATE_CONTRACT_FIXTURES=1` régénère. Calendrier : `Me` (client, pré-L5, staff), auth et erreurs codées en **L3a** ; `PublicConfig` en **L3b** ; `PublicHandyman` et admin en **L5b** ; `Application`, `KycOverview`, `HandymanProof` en **L6**.
- `docs/api-contracts/copy.fr.json` : pour chaque `handyman.status`, code `missing`, code d'erreur et état KYC, `{"title","description","cta"}` en français. React et Flutter le consomment (aucun libellé dupliqué).
- `scripts/sync_contracts.sh` copie les fixtures vers `flutter_tratra/test/fixtures/api/` et écrit `CONTRACTS_SHA256` ; la CI mobile échoue si l'empreinte ne correspond pas à celle du backend.

---

## 5. Sécurité

### 5.1 OTP (`handy/identity/otp.py`, `otp_quota.py`)

| Paramètre | Valeur | Réglage |
|---|---|---|
| Code | 6 chiffres, `secrets.randbelow(10**6)` | — |
| TTL d'un code | 300 s **à partir de l'envoi effectif** (posé par le worker) | `OTP_TTL_SECONDS` |
| Vie d'un challenge | 30 min | `OTP_CHALLENGE_TTL_SECONDS` |
| Essais par code | 5, puis `otp_locked` | `OTP_MAX_ATTEMPTS` |
| Envois par challenge | 3 | `OTP_MAX_SENDS_PER_CHALLENGE` |
| Délai entre envois | 60, 120, 240 s | `OTP_RESEND_BASE_COOLDOWN` |
| Par numéro **et par famille** (`signup`, `reset`, `phone`, `stepup`) | 5 SMS/h, 10/jour | `OTP_PHONE_HOURLY_LIMIT`, `OTP_PHONE_DAILY_LIMIT` |
| Par préfixe national (indicatif + 6 chiffres) | 30 SMS/h : défi ; 100/h : refus | `OTP_PREFIX_SOFT_HOURLY`, `OTP_PREFIX_HARD_HOURLY` |
| Par clé IP (IPv4 ou /64 ; /48 au jour) | 20/h : défi ; 300/h et 1 000/jour : refus | `OTP_IP_SOFT_HOURLY`, `OTP_IP_HARD_HOURLY`, `OTP_IP_HARD_DAILY` |
| Budget par pays et par jour | `{"CI":5000,"*":300}`, dont **20 %** réservés aux familles `reset`, `phone` et `stepup` des comptes existants | `OTP_COUNTRY_DAILY_BUDGET`, `OTP_EXISTING_ACCOUNT_RESERVE_PCT` |
| Taux de conversion d'un préfixe (vérifications / envois, sur 1 h, à partir de 20 envois) | < 30 % : défi pour ce préfixe et alerte | `OTP_CONVERSION_ALERT_RATIO` |
| Pays autorisés | C5 | `OTP_ALLOWED_COUNTRIES` |
| Type de numéro | mobile (`MOBILE` ou `FIXED_LINE_OR_MOBILE`) | — |

**Hachage** : `code_hash = HMAC-SHA256(OTP_PEPPER, f"{challenge_id}:{purpose}:{phone_e164}:{code}")`, comparé par `hmac.compare_digest`. `OTP_PEPPER` (32 octets au moins, distinct de `SECRET_KEY`) est obligatoire en production **dès qu'un backend SMS réel est configuré**.

**Réservation atomique d'un envoi** (corrige la course S-M10) :

```python
def reserve_send(phone, bucket, ip, *, existing_account, is_decoy, challenge=None) -> SendDecision:
    with transaction.atomic():
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["otp:" + phone])
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["otp-country:" + country(phone)])
        counts = OtpSendLog.objects.filter(status__in=["reserved", "sent"], created_at__gte=…)   # numéro+famille, préfixe, IP, pays
        decision = evaluate(counts, bucket, existing_account)   # ok | challenge | refuse(code) | budget_exceeded
        if decision.ok:
            OtpSendLog.objects.create(phone_e164=phone, bucket=bucket, status="reserved", is_decoy=is_decoy, …)
        return decision
```

- Le worker, juste avant l'appel au fournisseur, revérifie le budget du pays sous le même verrou ; puis passe la ligne à `sent` ou `failed` (une ligne `failed` ne compte plus).
- `evaluate` renvoie `challenge` (→ 428 `challenge_required`) quand un seuil souple est dépassé et qu'aucun `challenge_token` valide n'accompagne la requête ; le jeton Turnstile est vérifié côté serveur (`https://challenges.cloudflare.com/turnstile/v0/siteverify`, délai 3 s, échec → 400 `challenge_failed`).
- Budget pays : la part « ouverte » (80 %) sert à toutes les familles ; la réserve (20 %) n'est accessible qu'aux familles `reset`, `phone` et `stepup` d'un compte existant. Épuiser le budget des inscriptions ne bloque donc ni la réinitialisation ni la vérification des comptes existants. Au-delà : 503 `sms_budget_exceeded`, coupure du pays pour la famille concernée jusqu'à minuit, alerte Sentry.
- Les leurres et les SMS d'information consomment les compteurs de leur famille (`signup` pour l'inscription, `info` pour les avertissements) : un attaquant ne peut pas épuiser la famille `reset` d'un numéro en multipliant les inscriptions (S-M12).
- Test de concurrence (`transactional_db`, 20 threads sur le même numéro) : exactement 5 envois réservés.

**Consommation atomique** (corrige M-S14) :

```python
with transaction.atomic():
    otp = OTPCode.objects.select_for_update().get(challenge_id=cid, purpose=purpose)
    if otp.consumed_at or now > otp.expires_at or otp.attempts >= otp.max_attempts:
        return Result.locked_or_expired(otp)               # aucune écriture
    if otp.is_decoy or not otp.matches(code) or not expected_user_ok(otp):
        updated = OTPCode.objects.filter(pk=otp.pk, attempts__lt=F("max_attempts"))\
                                 .update(attempts=F("attempts") + 1)
        return Result.invalid(attempts_left=…)              # jamais d'exception dans le bloc
    otp.consumed_at = now; otp.used = True; otp.payload = {}
    otp.save(update_fields=["consumed_at", "used", "payload"])
```

**Envoi asynchrone, sans code en clair hors du worker** :
- la requête réserve l'envoi et lance `send_otp_sms.delay(otp_id)` via `transaction.on_commit`, sur la file Celery **`otp`** (dédiée, prioritaire, distincte de `notifications`) ;
- le worker génère le code, enregistre le hachage, pose `expires_at = now + TTL`, envoie, met à jour `OtpSendLog` ;
- un leurre suit le même chemin jusqu'au worker, qui n'envoie rien (ou le SMS d'information) ; côté requête, il écrit un challenge de même taille avec un hachage aléatoire ;
- `OTP_SEND_ASYNC=false` n'est permis qu'en dev et en test (`ImproperlyConfigured` en production) ; dans ce mode l'envoi est exécuté directement, sans `on_commit`, et les tests lisent le code dans `handy.identity.sms.outbox`.

Gabarit (alphabet GSM-7), avec la ligne d'auto-remplissage WebOTP :

```
Tratra : votre code est 123456. Valable 5 min. Ne le communiquez a personne.

@tratra.net #123456
```

Le domaine vient de `WEBOTP_DOMAIN` (domaine du front). Android utilise l'API SMS User Consent (aucun hachage d'application requis), iOS `AutofillHints.oneTimeCode`.

### 5.2 Anti-énumération

| Parcours | Mesure |
|---|---|
| Inscription | 202 identique ; leurre de même écriture et même hachage ; même chemin jusqu'au worker ; SMS d'information au titulaire réel ; existence d'un compte legacy révélée **après** l'OTP seulement. |
| Mot de passe oublié | 202 identique ; leurre sans SMS ; validation du mot de passe en deux temps (§4.3). |
| Connexion | Message unique ; liste de candidats avec un nombre constant de hachages (§5.3). |
| Vérification de code | Même `otp_invalid` pour un leurre, un mauvais code ou un challenge inconnu ; `attempts_left` décompté aussi sur les leurres. |
| Changement de numéro ou d'email | Réponse identique, que la valeur soit libre ou prise. |
| Inscription legacy | `phone` ignoré ; conflits d'email et de username sous `signup_unavailable` ; throttle `auth_register`. |
| Profil public | 404 identique pour un profil inexistant ou non publiable. |
| Webhook | 200 pour un job inconnu. |

Test de temps (`slow`) : écart des médianes inférieur à 50 ms sur 50 essais entre un numéro connu et un numéro libre (A19).

### 5.3 Anti-bruteforce, IP fiable, comptes staff

**IP client** (`handy/identity/client_ip.py`) :

```python
def get_client_ip(request) -> Optional[str]:
    meta = getattr(request, "META", {}) or {}
    remote = meta.get("REMOTE_ADDR")
    count = settings.TRUSTED_PROXY_COUNT                       # 0 en dev, 1 en prod
    xff = meta.get("HTTP_X_FORWARDED_FOR", "")
    if count <= 0 or not xff or remote not in settings.TRUSTED_PROXY_IPS:   # IP fixe de Traefik uniquement
        return remote
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    candidate = hops[-min(count, len(hops))] if hops else remote          # lecture DEPUIS LA DROITE
    return candidate if _is_valid_ip(candidate) else remote

def ip_key(ip: str, *, daily: bool = False) -> str:
    """IPv4 telle quelle ; IPv6 agrégée au /64 (au /48 pour les quotas journaliers)."""
```

- Traefik reçoit une IP fixe dans le réseau Docker (`ipv4_address` dans `docker-compose.yml`), seule valeur de `TRUSTED_PROXY_IPS`. Le port 8000 n'est pas publié.
- Utilisations : `AXES_CLIENT_IP_CALLABLE`, une classe de base de throttle `TratraThrottleMixin.get_ident()` (retourne `ip_key(get_client_ip(request))`, appliquée à tous les scopes anonymes et IP), `IPBlacklistMiddleware` (`middleware.py:16-22`, qui prenait le premier élément), les quotas OTP et les journaux. `daphne --proxy-headers` n'est **pas** utilisé.
- Les appels SSR de Next passent par Traefik et portent `X-Internal-Render` (§3.6).

**axes** (`base.py:440-446`, remplacé) :

```python
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=30)
AXES_RESET_ON_SUCCESS = True
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False
AXES_CLIENT_IP_CALLABLE = "handy.identity.client_ip.get_client_ip"
AXES_USERNAME_CALLABLE = "handy.identity.backends.axes_username"   # téléphone -> E.164, sinon minuscules
AUTHENTICATION_BACKENDS = ("axes.backends.AxesStandaloneBackend", "handy.identity.backends.PhoneEmailUsernameBackend")
```

**`PhoneEmailUsernameBackend`** (équivalent d'allauth, M-M14) :
1. Garde par compte (ci-dessous) : si l'identifiant est verrouillé pour cette source, échec immédiat après un hachage factice.
2. Candidats, dans l'ordre, au plus 3 comptes actifs distincts : `User.phone == normalize(saisie)` ; puis l'email (`EmailAddress.email__iexact`, puis `User.email__iexact`, à condition que l'email soit vérifié ou `email_login_legacy`) ; puis `User.username__iexact`.
3. **Exactement 3** appels à `check_password` (complétés par des hachages factices) : le temps ne dépend ni du nombre de candidats ni de leur existence. Le premier candidat dont le mot de passe correspond est retenu.
4. Le backend allauth est retiré de `AUTHENTICATION_BACKENDS` (allauth reste installé pour la table `EmailAddress`).
- `identity_report` compte les usernames en doublon de casse, les usernames qui ressemblent à un numéro et les `EmailAddress` qui diffèrent de `User.email`.

**Garde par compte** (`handy/identity/guards.py`, cache Redis), appliquée **dans le backend** : elle couvre donc l'API, la revendication de compte, l'admin Django et toute vue qui appelle `authenticate()` :
- clé `auth:fail:<sha256(identifiant normalisé)>` ; au-delà de 10 échecs par heure venant de sources **inconnues**, l'identifiant est verrouillé pour ces sources : 15 min, doublé à chaque récidive, **plafonné à 1 h** ;
- une tentative qui présente un **jeton d'appareil connu** (`handy/identity/devices.py` : `signing.dumps({"uid", "did"})` émis après un succès, cookie `tratra_dev` ou en-tête `X-Tratra-Device`) n'est pas bloquée par ce verrou (motif OWASP « device cookie ») ; seuls axes et le throttle IP s'appliquent ;
- la garde s'applique aussi aux identifiants inexistants (pas de fuite) ; remise à zéro sur succès ou réinitialisation ;
- au premier verrouillage de la journée, un SMS d'alerte est envoyé au titulaire si son numéro est vérifié (famille `info`, au plus un par jour) ; événement `account_locked`.

Le login renvoie 429 `too_many_attempts` si `request.axes_locked_out` ou si la garde est active (test dédié de l'attribut posé par `AxesStandaloneBackend`).

**Comptes staff et admin Django** : MFA, refresh de 12 h, pas de réinitialisation par SMS (§1.7). L'admin est monté sous `ADMIN_URL` (obligatoire et différent de `admin/` en production) via `OTPAdminSite`. Recommandé : allowlist IP de Traefik sur ce chemin (`ADMIN_ALLOWED_CIDRS`). Test : 20 essais depuis 20 IP différentes sur l'admin déclenchent la garde.

**Middlewares ajoutés** (L2) : `RequestContextMiddleware` (acteur et IP pour les événements, §1.4), `NoStoreAuthenticatedMiddleware` (`Cache-Control: no-store, private` et `Vary: Authorization, Cookie`, §4.0).

### 5.4 Cache Redis partagé

```python
CACHE_URL = config("CACHE_URL", default="") or derive_from(REDIS_URL, db=1)
CACHES = ({"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": CACHE_URL,
                       "KEY_PREFIX": "tratra", "TIMEOUT": 300}}
          if CACHE_URL else
          {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tratra-local"}})
```

- En production, un cache Redis est **obligatoire** ; il est dérivé de `REDIS_URL` (déjà configuré pour Celery) si `CACHE_URL` est vide, donc sans nouvelle variable à fournir.
- Tests et CI : LocMem (fixture autouse, §9.1).
- Usages : throttles, garde par compte, jetons d'appareil révoqués, liste de refus des `jti`, rotations de refresh (§5.6), jetons Smile ID (14 min) et Orange (55 min), fenêtres de bris de glace, `public_stats`, compteurs de signatures webhook invalides.

### 5.5 Mots de passe

- `validate_password(password, user)` dans toutes les écritures (inscription, inscription legacy, réinitialisation en deux temps, changement, récupération).
- Validateurs de `base.py:240-253`, maximum 128 caractères.
- Côté clients : règles d'aide (8 caractères, une lettre, un chiffre) ; les messages du serveur font foi.
- Tests utilisant `pass1234` via l'API (`test_security_sprint1.py:46,57`, `test_phase1.py:15`) migrés vers un mot de passe fort ; `create_user()` des fixtures non concerné.

### 5.6 JWT : révocation, rotation, cookie web, CSRF

**Révocation (D10)** :
- `TratraRefreshToken.for_user(user)` ajoute `sv = user.session_version`, `amr` (`["pwd"]` ou `["pwd","otp"]`), `aud = JWT_AUDIENCE`, `iss = JWT_ISSUER` ; la durée de l'access vaut 10 min en mode web (`X-Tratra-Client: web`), 30 min sinon ; le refresh vaut 7 jours, **12 h** pour un compte staff.
- `TratraJWTAuthentication.get_user()` lève `AuthenticationFailed(code="session_revoked")` si `sv` diffère, et refuse un `jti` présent dans la liste de refus (Redis). Toutes les déclarations explicites `JWTAuthentication` (dont `HandymanDocumentViewSet`, `views.py:994`) sont remplacées.
- Un jeton sans `sv` vaut 1. Le passage à `JWT_SIGNING_KEY`, `aud` et `iss` (train R2) invalide les jetons existants : **une reconnexion unique** de tous les utilisateurs, annoncée.

```python
def revoke_all_sessions(user, *, reason: str, actor=None) -> None:
    User.objects.filter(pk=user.pk).update(session_version=F("session_version") + 1)
    live = OutstandingToken.objects.filter(user=user, expires_at__gt=timezone.now())
    BlacklistedToken.objects.bulk_create([BlacklistedToken(token=t) for t in live], ignore_conflicts=True)
    record_account_event(user, "sessions_revoked", actor=actor, metadata={"reason": reason})
```

Appelée par la réinitialisation, la récupération, le changement de mot de passe ou de numéro, `logout/all`, la désactivation et la détection de réutilisation. **Pas** par une suspension KYC.

**Rotation atomique et détection de réutilisation** (`TratraTokenRefreshSerializer`, corrige S-M18) :

```python
outcome = None
with transaction.atomic():                                           # aucune exception levée dans le bloc
    outstanding = OutstandingToken.objects.select_for_update().get(jti=refresh["jti"])
    if BlacklistedToken.objects.filter(token=outstanding).exists():
        rotated = cache.get(f"rt:rotated:{outstanding.jti}")         # posé à chaque rotation, TTL = vie du refresh
        reuse = bool(rotated) and now - rotated["at"] > REFRESH_REUSE_GRACE_SECONDS   # 30 s (onglets concurrents)
        outcome = "reuse" if reuse else "stale"
    elif not sv_and_active_ok(user):
        outcome = "revoked"
    else:
        BlacklistedToken.objects.create(token=outstanding)           # contrainte d'unicité : un seul gagnant
        new = TratraRefreshToken.for_user(user)
        cache.set(f"rt:rotated:{outstanding.jti}", {"at": now, "child": new["jti"]}, timeout=refresh_lifetime)
if outcome == "reuse":
    revoke_all_sessions(user, reason="refresh_reuse")               # écrit aussi refresh_reuse_detected
if outcome:
    raise InvalidToken(code="session_revoked" if outcome == "revoked" else "token_not_valid")
```

Tests : deux threads présentent le même refresh, un seul succès ; réutilisation au-delà de 30 s, toutes les sessions révoquées ; un refresh mis en liste noire par la déconnexion (sans clé `rt:rotated`) ne déclenche pas de révocation.

**Cookie web (D11)** : `tratra_rt` en `HttpOnly`, `Secure` en production, `SameSite=Strict`, `Path=/handy/auth/`, sans `Domain`, `Max-Age` = vie du refresh.
- **CSRF** : `refresh` et `logout` en mode cookie exigent `X-Tratra-Client: web` (preflight CORS) **et** une `Origin` présente dans `CORS_ALLOWED_ORIGINS` ; `Origin: null` est refusée → 403 `csrf_failed`.
- **Onglets** : `navigator.locks.request("tratra-refresh", …)` sérialise les refresh ; sur 401, attente de 300 ms et un nouvel essai (dans la fenêtre de grâce) ; diffusion par `BroadcastChannel("tratra-auth")`.
- Démarrage en production : `CORS_ALLOWED_ORIGINS` ne contient ni joker, ni expression régulière, ni `localhost` ; sinon `ImproperlyConfigured`.
- Mobile : bearer, refresh dans `flutter_secure_storage`, refresh unique sérialisé (§8.1).

### 5.7 SMS (`handy/identity/sms/`)

- Interface : `SmsBackend.send(to_e164: str, text: str, *, category: str) -> SmsResult(provider, message_id)` ; catégories `otp`, `info`, `notification`.
- Backends : `console` (dev seulement, refusé si `DJANGO_ENV=prod`), `locmem` (tests, `outbox`), `orange_ci` (OAuth `client_credentials`, jeton en cache 55 min, `POST …/smsmessaging/v1/outbound/tel%3A%2B{sender}/requests`, +225 uniquement, 5 SMS/s), `twilio` (Messages API), `router` (`SMS_ROUTES={"CI":"orange_ci","*":"twilio"}`, bascule facultative `SMS_FAILOVER`).
- Files Celery : `otp` pour les codes et les SMS d'information liés, `notifications` pour le reste.
- **Aucun code OTP n'est passé au logging** : journaux avec `challenge_id[:8]`, numéro masqué, fournisseur, identifiant de message, issue.
- Production : si aucun backend réel n'est configuré, tous les parcours OTP répondent 503 `sms_unavailable` et les drapeaux qui en dépendent (`PHONE_SIGNUP_ENABLED`, `BOOKING_REQUIRES_PHONE_VERIFIED`) doivent être faux, sinon `ImproperlyConfigured`. Un backend réel incomplet (identifiants manquants) → `ImproperlyConfigured`.
- `handy/tasks._send_sms` (arrivée imminente) est rebranché sur ce service (catégorie `notification`) et respecte `preferences.notifications.sms` (L3b).

### 5.8 Intégration Smile ID (`handy/kyc/providers/smile_id.py`)

**Principe (D9)** : le webhook n'est qu'un signal. **Toutes** les données de décision (statut, motif, verdict de chaque contrôle, `id_fields`, antifraude, signaux appareil, `user_id`, `partner_params`, liens d'images) viennent d'un **appel serveur à serveur authentifié** par notre clé.

Client REST, avec une `requests.Session` injectable pour les tests :
- `get_token()` : `POST {base}/v3/token` (en-têtes `SmileID-Partner-ID`, `SmileID-API-Key`), mis en cache 14 min.
- `create_sdk_session(submission)` (canal `sdk_web`) : jeton v3 lié à `user_id = kyc_subject_id`, `job_id` généré par nous, `partner_params = {"submission_id", "attempt"}`, `callback_url`, produit `document_verification`. Le format exact (jeton porteur des données ou paramètres côté SDK) est **figé en L0**.
- `submit_inhouse(submission)` (canaux maison) : `POST {base}/v3/document_verification`, multipart lu en flux depuis le stockage privé (déchiffré en mémoire) :

| Champ multipart | Valeur |
|---|---|
| `selfie_image` | selfie |
| `liveness_images` | 6 à 8 images |
| `document`, `document_back` | recto, verso |
| `consent` | `{"granted":true,"granted_at":<KycConsent>,"notice_language":"FR","notice_privacy_policy_url":<URL de /confidentialite>}` |
| `country`, `id_type` | `CI`, `IDENTITY_CARD` |
| `user_details` | `{"given_names","last_name"}` (le numéro de téléphone n'est pas transmis) |
| `user_id` | `kyc_subject_id` |
| `callback_url` | `SMILE_ID_CALLBACK_URL` |
| `partner_params` | `{"submission_id","attempt"}` |

  Réponse 202 avec `job_id` → `provider_job_id`. Délais : connexion 5 s, lecture 60 s ; tâche `kyc_submit_to_provider` : 5 essais à délai exponentiel, puis T6 (`provider_unavailable`).
- `fetch_result(job_id)` : **relecture authentifiée complète**. L'endpoint exact est choisi en L0 parmi ceux qui renvoient le résultat complet signé ou authentifié par notre clé (résultat de job v3, ou `job_status` v1 signé avec `return_history=false`, `return_image_links` vrai seulement pour le canal SDK). `GET /v3/status/{job_id}`, qui ne renvoie que le statut, **ne suffit pas** à lui seul.
- Capacité au démarrage : `SMILE_ID_AUTHENTICATED_FULL_RESULT=true` n'est posé qu'après validation en L0. S'il est faux, `KYC_AUTO_APPROVE_ON_CLEAR` est forcé à faux (avertissement au démarrage), tout résultat passe en revue et le reviewer saisit numéro et expiration de la pièce.
- Garde-fous : en production avec `KYC_PROVIDER=smile_id`, `SMILE_ID_ENV=production` et base `https://api.smileidentity.com`, sinon `ImproperlyConfigured`.

**Traitement d'un résultat** (`kyc_fetch_provider_result`, déclenché par le webhook ou par `kyc_poll_pending`) :
1. `fetch_result(job_id)` ; `processing` → nouvel essai 2 min plus tard.
2. **Liaison d'identité** : `user_id == profile.kyc_subject_id` et `partner_params.submission_id == submission.id`, sinon T6 avec `provider_identity_mismatch`.
3. Assainissement : verdicts des contrôles (`actions`), niveau de risque, `fraud_detected`, signaux appareil réduits à un booléen `provider_device_signals_ok` (canal SDK), `expiration_date` → `document_expires_on`, `id_number` → HMAC (trousseau) et quatre derniers caractères, noms → `name_mismatch`. Rien d'autre n'est stocké ni journalisé.
4. Canal SDK : copie des images (recto, verso, selfie) depuis les liens présignés courts vers le stockage privé chiffré (`KycDocument.source="provider"`), pour la revue humaine. Les liens ne sont jamais stockés.
5. Drapeaux internes (§2.5), puis transition selon le tableau du §2.5 et les cas du §2.3.

**Ré-authentification** (L10) : SmartSelfie Authentication du prestataire contre le selfie enrôlé (`user_id = kyc_subject_id`) ; un score net et réussi est présenté au reviewer, qui confirme (§2.7).

**Cadrage L0 obligatoire** (avant L6) : voir §10, lot L0. Il valide notamment la résistance à l'injection (images synthétiques, vidéo rejouée, photo d'écran, appel direct à l'API sans client) et obtient par écrit la position du prestataire sur la détection d'injection hors SDK.

### 5.9 Preuves KYC : stockage et accès

**Stockage** :
- `KycPrivateStorage` (alias `private_kyc`) : bucket MinIO dédié en production (`prod.py:35-37`), système de fichiers non public en dev. Clés opaques `kyc/<profile_id>/<submission_hex>/<uuid>.bin`.
- **Compte de service MinIO dédié** au bucket KYC, avec une politique limitée à `s3:PutObject`, `s3:GetObject`, `s3:PutObjectRetention`, `s3:PutObjectTagging` sur ce seul bucket (ni `DeleteObject` ni `ListBucket`). Le compte root n'est jamais configuré dans l'application ; le bucket des médias publics a son propre compte. Politique de bucket refusant tout accès anonyme.
- `PrivateKycS3Storage.url()` lève `NotImplementedError` (test) ; si l'alias `private_kyc` manque hors tests, `ImproperlyConfigured` au lieu d'un repli silencieux sur `default_storage`.
- **Chiffrement applicatif** (`handy/kyc/crypto.py`, Arbitrages A9) : AES-256-GCM par objet, nonce aléatoire de 12 octets, données associées = `<document id>`, trousseau `KYC_ENCRYPTION_KEYS` (`{"1": "<base64 32 octets>"}`) et `KYC_ENCRYPTION_CURRENT_VERSION` ; `encryption` stocke l'algorithme, la version et le nonce. Le `sha256` porte sur le contenu en clair. Obligatoire en production dès que `KYC_SUBMISSIONS_ENABLED`.
- **Versioning et verrouillage d'objet** activés sur le bucket. À l'upload, l'objet reçoit le tag `state=draft` ; la règle de cycle de vie expire les objets `state=draft` au bout de 30 jours (`KYC_DRAFT_RETENTION_DAYS`). Au submit, le worker pose `state=submitted` et une rétention en mode gouvernance de 3 ans après la décision (`KYC_EVIDENCE_RETENTION_YEARS`, C6). La tâche `kyc_mark_purged_objects` reporte `purged_at` en base.
- Fichiers legacy : `migrate_kyc_documents_to_private_storage --apply` juste après le déploiement de 0027 ; `--delete-source` au plus tard 30 jours après, une fois la copie vérifiée (runbook).
- Infra (L2) : le routeur Traefik `minio-console` est **supprimé** (accès console par tunnel SSH ou VPN) ; l'API S3 reste publiée pour les médias publics, le bucket KYC n'étant accessible qu'avec le compte de service.

**Accès** : streaming gardé uniquement (généralisation de `HandymanDocumentViewSet.download`), **jamais** d'URL de stockage, présignée ou non. En-têtes :

```
Cache-Control: private, no-store, max-age=0
Pragma: no-cache
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Content-Security-Policy: default-src 'none'; sandbox
Cross-Origin-Resource-Policy: same-site
Content-Disposition: inline; filename="kyc-<uuid>.jpg"     # attachment pour un PDF (justificatifs)
```

Périmètre d'un reviewer (`kyc_view_evidence`) :
- soumissions en `review` **prises en charge par lui** ;
- un Superviseur (`kyc_override`) : toute soumission ;
- toute autre consultation (soumission approuvée, ancienne, non prise en charge) : **bris de glace** (`POST …/break-glass/` avec motif, fenêtre de 30 min, audit `evidence_break_glass`, alerte aux Superviseurs) ;
- jamais son propre dossier ;
- throttle `admin_kyc_evidence` 60/h, alerte au-delà de 30 ; chaque accès écrit `evidence_viewed` (acteur, document, IP).
- Les mêmes règles s'appliquent aux preuves legacy (`/handyman-docs/{id}/download/`) à partir de L5b. L'admin Django n'affiche **aucun** lien vers un fichier : il n'existe pas de chemin d'accès par session.

**Validation des uploads** (`handy/kyc/evidence.py`) : type déclaré, extension et signature binaire concordants (Pillow `verify()` puis réouverture pour les dimensions ; `%PDF-` pour les justificatifs) ; `Image.MAX_IMAGE_PIXELS` à 40 Mpx ; tailles et dimensions selon `requirements` ; SHA-256 ; **pas de réencodage** des pièces d'identité (preuve transmise au prestataire), chiffrement puis stockage.

Les serializers publics et le test `SENSITIVE_KEYS` (`handy/test_lot1_public.py:32`), étendu à `kyc_status`, `download_url`, `document`, `selfie`, `cni_number`, `provider_result`, `phone`, `is_approved` et `is_verified` (à partir de R3), vérifient l'absence de ces champs sur **tous** les endpoints anonymes. La clé publique s'appelle `availability_slots`, distincte de la clé sensible `availability`.

### 5.10 Sentry et journaux

`sentry_sdk.init` (`base.py`) :
- `include_local_variables=False` ;
- `send_default_pii=False`, **forcé** en production (`ImproperlyConfigured` si `SENTRY_SEND_PII` vaut vrai) ;
- `max_request_body_size="never"` ;
- `event_scrubber=EventScrubber(denylist=DEFAULT_DENYLIST + ["code","otp","new_password","current_password","password_hash","refresh","access","device_token","claim_token","reset_token","challenge_id","challenge_token","document_number","id_number","id_fields","image_links","selfie","frames","liveness_images","consent","user_details","payload","text","message","body","msisdn","to_e164","phone","phone_e164","response-signature","smileid-token","smileid-api-key","authorization","cookie"], recursive=True)` ;
- `before_send` : retire `request.data`, `request.cookies`, l'en-tête `Authorization`, `extra["celery-job"]`, et vide `frame.vars` de toute frame des modules `handy.identity`, `handy.kyc` et `handy.api.auth_*` (défense en profondeur) ;
- `before_breadcrumb` : ignore les breadcrumbs de logging des loggers `handy.identity.*` et `handy.kyc.*`.

`handy.identity.logging.RedactFilter` sur le handler racine : masque `\+\d{8,15}`, les numéros locaux ivoiriens `\b0[1257]\d{8}\b`, et les suites de 6 chiffres qui suivent `code` ou `otp`.

Test : une exception levée dans le backend SMS pendant un envoi produit un événement (transport factice) qui ne contient ni le code ni le numéro.

### 5.11 CSP et Permissions-Policy (`frontend/next.config.mjs`, middleware Next)

- **Permissions-Policy** par route : `camera=(self)` uniquement sur `/worker/verification` et `/worker/verification/:path*` ; `camera=()` ailleurs ; `geolocation=(self)` ; `microphone=()`.
- **CSP à nonce** (middleware Next) sur `/admin/:path*` et `/worker/verification/:path*` : `script-src 'self' 'nonce-…' 'strict-dynamic'` sans `unsafe-inline` ; `require-trusted-types-for 'script'` sur `/admin` ; `img-src 'self' blob: data:` ; `media-src 'self' blob: mediastream:` sur la capture. Les autres pages gardent la CSP actuelle.
- Origines tierces : `challenges.cloudflare.com` (`script-src`, `frame-src`) seulement sur les pages d'authentification et `/challenge` ; `cdn.usesmileid.com` seulement sur `/worker/verification` quand le canal SDK est actif (L10).
- Visionneuse admin : images affichées par `<img src="blob:…">` avec un type de Blob forcé depuis une allowlist (`image/jpeg`, `image/png`) ; PDF jamais rendus, proposés au téléchargement (A8) ; jamais `window.open(blobURL)`.
- `public/sw.js` `NEVER_CACHE` et `robots.ts` `disallow` : `/account`, `/forgot-password`, `/proposer-un-service/candidature`, `/worker`, `/admin`, `/challenge`.

### 5.12 Backlog sécurité

- Réduction de `UserMiniSerializer` dans les réservations (l'email de la contrepartie est exposé).
- Authentification JWT du WebSocket (`tratra/asgi.py`).
- Détection de malware sur les uploads.
- Purge RGPD outillée (preuves échues, comptes désactivés).
- Attestation d'application mobile (Play Integrity, App Attest) à la place du défi en webview.

---

## 6. Migrations, reprise sans perte, runbook

### 6.1 Ordre exact (application `handy`, après `0028_clean_business_plan_features` du lot public)

| Migration | Lot | Type | Contenu | Inverse |
|---|---|---|---|---|
| `0029_protect_relations` | L1a | état Python seul (aucun SQL : `on_delete` fait partie des attributs non-DB de Django 4.2) | `PROTECT` sur `Booking.client`, `Booking.handyman`, `Payment.booking`, `Payout.handyman`, `DepositTransaction.handyman`, `Invoice.booking`, `Subscription.user`, `Review.booking`, `Dispute.booking`, `PayoutAccount.handyman`, `HandymanDocument.handyman` | Oui |
| `0030_account_events_ops_roles` | L1b | schéma, `RunSQL`, données | `AccountEvent` ; `Meta.permissions` : `view_all_records` (`Booking`), `resolve_dispute` (`Dispute`), `manage_payouts` (`Payout`) ; fonction `handy_forbid_mutation` et trigger sur `handy_accountevent` ; groupes `Opérations` et `Support` | Refusé si `handy_accountevent` contient des lignes ; sinon supprime trigger, fonction, groupes, table |
| `0031_payment_release_after` | L1c | schéma | `Payment.release_after` (nullable), `Payment.completion_confirmed_at` (nullable) | Oui |
| `0032_identity_schema` | L3a | schéma, `RunSQL` | Champs `User` (§1.1) avec DEFAULT durables ; champs `OTPCode` (§1.2) : `challenge_id` **nullable et non unique**, `code` nullable sans index, `code_verified_at`, usages étendus ; `OtpSendLog` ; `SignupClaim` ; types d'`AccountEvent` et de `Notification` (état seul) | Oui |
| `0033_identity_backfill` | L3a | données | `email '' → NULL` ; `email_login_legacy = true` si email ; `phone '' → NULL` ; `phone_legacy_raw = phone` ; `OTPCode` : `challenge_id = uuid4()` ligne par ligne, `code = NULL`, `used = true`, `consumed_at = now` | Réel (§6.9) |
| `0034_identity_constraints` | L3a | schéma, `RunSQL` | `challenge_id` : `AlterField(default=uuid4, unique=True)` non nul **et** `SET DEFAULT gen_random_uuid()` ; CHECK `user_verified_phone_requires_phone`, `otp_attempts_le_max` | Oui |
| (applications tierces `otp_totp`, `otp_static`) | L3b | tiers | Tables django-otp | — |
| `0035_kyc_schema` | L5a | schéma, `RunSQL` | Champs `HandymanProfile` (§1.5) avec DEFAULT durables, `kyc_subject_id` **nullable et non unique** ; `KycConsent`, `KycSubmission` (avec permissions), `KycDocument`, `KycAuditEvent`, `KycWebhookEvent` ; `current_submission` | Oui |
| `0036_kyc_legacy_backfill` | L5a | données | `kyc_subject_id = uuid4()` ligne par ligne ; correction des données invalides (§6.4) ; correspondance legacy (§6.4) via `handy/kyc/legacy_mapping.map_legacy_v1` ; `public_location` ; `legacy_is_approved` ; soumissions `mode=legacy` ; audit `legacy_data_fixed` et `legacy_migrated` (chaînés) ; `is_approved = is_published = online = false` | Refusé dès qu'un `KycAuditEvent` autre que `legacy_migrated` ou `legacy_data_fixed` existe ; sinon, dans l'ordre : `current_submission = NULL`, suppression des événements legacy, des soumissions legacy, restauration des créneaux archivés et des rayons, `is_approved = coalesce(legacy_is_approved, false)`, `kyc_status = 'draft'` |
| `0037_kyc_constraints` | L5a | schéma, `RunSQL` | `kyc_subject_id` : `AlterField(default=uuid4, unique=True)` non nul **et** `SET DEFAULT gen_random_uuid()` ; CHECK `hm_*`, `slot_end_after_start`, `area_radius_bounds` en **`NOT VALID`** ; index `(is_published, kyc_status)` ; triggers append-only sur `handy_kycauditevent` et `handy_kycconsent` | `DROP TRIGGER IF EXISTS` et suppression des contraintes (jamais la fonction) |
| `0038_kyc_rbac_groups` | L5b | données | Groupes `KYC – Reviewer`, `KYC – Superviseur` ; ajout de `kyc_view_queue` et `kyc_view_audit` au groupe `Support` | Retrait de ces groupes et permissions |
| `0039_handyman_proofs` | L6 | schéma | `HandymanProof` | Oui |
| `0040_user_phone_e164_check` | L11 | schéma, `RunSQL` | CHECK `user_phone_e164` en `NOT VALID`, validée par `db_validate_constraints` | Oui |
| `0041_user_email_ci_unique` | L11 | schéma, `atomic = False` | `CREATE UNIQUE INDEX CONCURRENTLY user_email_ci_unique ON handy_user (lower(email)) WHERE email IS NOT NULL` | Oui |

**Règles de rédaction** :
- **Champ UUID unique sur une table existante** : `AddField(null=True)`, puis `RunPython` ligne par ligne, puis `AlterField(default=uuid4, unique=True, null=False)` et `RunSQL("ALTER TABLE … ALTER COLUMN … SET DEFAULT gen_random_uuid()")` (PostgreSQL 16, natif). Un `default=uuid4` dans l'`AddField` donnerait la même valeur à toutes les lignes.
- **DEFAULT durables** (M-M2) : Django 4.2 retire le DEFAULT après l'`AddField`. Pour chaque colonne NOT NULL ajoutée, un `SeparateDatabaseAndState(database_operations=[RunSQL("… SET DEFAULT …", reverse_sql="… DROP DEFAULT")])` le repose : `session_version` 1, `preferences` `'{"notifications":{"sms":true}}'`, chaînes `''`, booléens selon leur défaut, listes JSON `'[]'`, `kyc_status 'draft'`, UUID `gen_random_uuid()`. Ainsi l'ancienne image (workers non redémarrés, rollback d'image) insère sans erreur. `test_db_defaults.py` vérifie `information_schema.columns.column_default` pour la liste complète ; tout `AlterField` ultérieur sur ces colonnes doit reposer le DEFAULT (le test l'attrape).
- **Contraintes sur des données existantes** : correction des données dans la migration précédente, puis `SeparateDatabaseAndState(state_operations=[AddConstraint(…)], database_operations=[RunSQL("ALTER TABLE … ADD CONSTRAINT … CHECK (…) NOT VALID")])`. Une contrainte `NOT VALID` s'applique déjà aux nouvelles écritures. La validation (`VALIDATE CONSTRAINT`) passe par `db_validate_constraints --apply`, après contrôle des données (runbook). Aucune migration n'échoue volontairement.
- Chaque migration de schéma commence par `RunSQL("SET LOCAL lock_timeout = '5s'")`.
- **Permissions en migration** (M-M4) :

```python
def ensure_permissions(apps):
    from django.contrib.auth.management import create_permissions
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

def create_groups(apps, schema_editor):
    ensure_permissions(apps)
    Permission = apps.get_model("auth", "Permission"); Group = apps.get_model("auth", "Group")
    perm = lambda c: Permission.objects.get(content_type__app_label="handy", codename=c)
    …
```

- Les migrations de données n'importent pas de code applicatif évolutif, **sauf** `handy/kyc/legacy_mapping.py` : fonction pure, sans import de modèle, versionnée (`map_legacy_v1`), jamais modifiée (une évolution crée `map_legacy_v2`). La commande `kyc_legacy_report` utilise la même fonction : aperçu et migration ne peuvent pas diverger.
- **Synchronisation `Meta`** (M-S12) : chaque changement de `Meta` est rattaché à la migration indiquée ci-dessus (`otp_attempts_le_max` en 0034, `user_phone_e164` en 0040 seulement). `python manage.py makemigrations --check --dry-run` est ajouté à la CI et au « Done » de chaque lot.
- Les tests `transactional_db` (flush) recréent groupes et plans par fixture, avec la même fonction que la migration (`handy/conftest.py`).

### 6.2 Téléphones : commande `normalize_user_phones`

```
python manage.py normalize_user_phones [--apply] [--check] [--report /tmp/phones.json] [--default-region CI] [--rollback]
```

À blanc par défaut. `--check` sort avec un code non nul s'il reste un `phone` non E.164 (contrôle préalable du runbook). Pour chaque `User` dont la source (`phone_legacy_raw` ou `phone`) est renseignée, dans une transaction par lot de 500 avec `select_for_update` :
1. Nettoyage (espaces, points, tirets, parenthèses ; `00` → `+`), `phonenumbers.parse(raw, "CI")`, `is_valid_number`, format E.164.
2. Classement :

| Issue | Action |
|---|---|
| `already_e164` | aucune |
| `normalized` (`0575…` → `+2250575…`) | `phone = E.164` |
| `not_mobile` (fixe) | `phone = E.164`, signalé (l'OTP exigera un changement de numéro) |
| `ci_legacy_8_digits` (plan d'avant 2021) | `phone = NULL`, valeur brute conservée, aucune conversion (correspondance ambiguë) |
| `invalid` | `phone = NULL`, valeur brute conservée |
| `duplicate` (plusieurs comptes aboutissent au même E.164) | **Le compte dont le numéro est vérifié l'emporte** et le garde ; les autres comptes **non vérifiés** passent à `NULL` (valeur brute conservée). Si aucun n'est vérifié, tous passent à `NULL` ; le premier qui prouve la possession récupère le numéro (revendication, §4.1). |

3. Chaque modification écrit `AccountEvent(phone_normalized, metadata={from_masked, to_masked, outcome})`. Idempotente ; aucun compte supprimé ni désactivé ; rapport JSON avec les numéros **masqués**.
4. `--rollback` remet `phone = phone_legacy_raw` pour les comptes portant `phone_normalized`, **sauf** : compte avec `phone_verified_at`, compte portant `phone_released`, ou valeur restaurée qui entrerait en conflit d'unicité (listés dans le rapport, sans écriture).

**Aucune écriture E.164 avant `--apply`** : l'inscription legacy n'enregistre plus le numéro (L1a) ; les parcours OTP de L3a refusent l'inscription (503 `signup_unavailable`) tant que `normalize_user_phones --check` échoue (contrôle mis en cache 5 min) ; la vérification et le changement de numéro comparent `phone` et la forme normalisée de `phone_legacy_raw`.

En dev : l'utilisateur 8 (`057535XXXX`) devient `+225057535XXXX` ; l'utilisateur 1 (sans téléphone) n'est pas concerné.

### 6.3 Emails

- 0033 convertit `''` en NULL et pose `email_login_legacy` pour tous les comptes ayant un email.
- Dès L3a, les serializers contrôlent l'unicité `iexact` (en excluant le compte courant) et les nouveaux emails passent par `email_pending` (§4.4).
- `identity_report` liste les doublons qui ne diffèrent que par la casse. Pour ces comptes, la connexion par email essaie chaque candidat (§5.3) ; le support les résout au cas par cas.
- L11 : 0041 ajoute l'index unique insensible à la casse, **après** un rapport sans doublon.

### 6.4 Correspondance KYC legacy (0036, prévisualisable par `kyc_legacy_report`)

**Corrections préalables** (même migration, avant la correspondance) :
- créneaux `AvailabilitySlot` avec `end_time <= start_time` : copiés dans un événement `legacy_data_fixed` (append-only), supprimés, drapeau `legacy_slots_archived` ;
- `ServiceArea.radius_km` hors de 1 à 100 : ramené dans l'intervalle, valeur d'origine dans `legacy_data_fixed`.

**Table de décision** (`map_legacy_v1`, première ligne applicable ; `idc` = meilleur statut de pièce `id_card` : `approved` > `pending` > `rejected` > aucune) :

| # | Situation legacy | `kyc_status` | Soumission créée | `legacy_flags` |
|---|---|---|---|---|
| 1 | `is_approved=True`, `idc=approved` | `review` | `mode=legacy`, `status=review`, drapeaux `legacy_approved`, `no_liveness_check` | `legacy_approved`, `legacy_id_card_only` |
| 2 | `is_approved=True`, `idc≠approved` | `review` | idem | `legacy_approved`, `legacy_without_id_document` |
| 3 | `is_approved=False`, `idc=approved` | `review` | idem | `legacy_doc_approved_profile_not` |
| 4 | `is_approved=False`, `idc=pending` ou un autre document `pending` | `draft` | aucune | `legacy_documents_pending` |
| 5 | `is_approved=False`, documents uniquement `rejected` | `rejected` (`resubmission_allowed`, `status_message` = dernier `rejection_reason`) | aucune | `legacy_rejected` |
| 6 | `is_approved=False`, aucun document | `draft` | aucune | — |
| 7 | toute autre combinaison (branche par défaut) | `draft` | aucune | `legacy_unclassified` |

Pour **tous** les profils : `kyc_subject_id`, `legacy_is_approved` = valeur d'origine, `is_approved = is_published = online = false`, événement `legacy_migrated` (`seq=1`, `metadata = {legacy_is_approved, documents par type et statut, branche}`). Aucune branche ne mène à `approved`.

Soumissions legacy : `attempt_number = 1`, `mode = legacy` (exclues du décompte des tentatives, §1.8), `submitted_at = min(documents.uploaded_at)` ou l'horodatage de la migration à défaut (jamais NULL).

**Dans la même fenêtre de déploiement** (étape obligatoire du runbook R3) : `kyc_legacy_request_resubmission --apply` fait passer les profils legacy en `review` à `rejected` (T9 système, `reason_code=legacy_reverification`, resoumission permise) et envoie notifications et SMS (si numéro vérifié et préférence). Les profils des lignes 4, 6 et 7 reçoivent la même invitation, sans transition.

`kyc_legacy_report` affiche le nombre de profils par branche, les créneaux et rayons corrigés, les profils qui violent les règles du formulaire (`legacy_constraints_violations`), et les artisans legacy ayant des réservations ouvertes (elles ne sont pas modifiées : la dépublication legacy n'ouvre pas de gratuité d'annulation, §2.4).

Données dev : un profil (`is_approved=False`, aucun document) → `draft` (ligne 6) ; ses deux services ne sont plus publics, ce qui est voulu et annoncé.

### 6.5 Données conservées

- Comptes : aucune suppression ; désactivation à la place.
- Réservations, paiements, versements, dépôts, factures, abonnements, avis, litiges, comptes de versement : `PROTECT` ; aucune revalidation rétroactive ; politique d'annulation inchangée pour les artisans legacy dépubliés.
- Profils : tous conservés ; `availability` JSON conservé (`legacy_availability`) ; créneaux invalides archivés dans le journal.
- Documents KYC legacy : conservés, `PROTECT`, `@cleanup.ignore`, copiés vers le stockage privé.
- OTP legacy : lignes conservées, codes neutralisés.

### 6.6 `user_type`

Conservé, lecture seule, `'client'` pour les nouveaux comptes. Signaux `create_handyman_profile` et `create_company_profile` (`handy/signal.py:11-24`) conservés ; grâce aux défauts UUID (§6.1), la création d'un profil par ce signal reste valide après 0037 (test). React (L4) et Flutter (L9a) n'utilisent plus `user_type`. Retrait au backlog.

### 6.7 Commandes de reprise et d'exploitation (à blanc par défaut, avec rapport)

| Commande | Rôle | Lot |
|---|---|---|
| `identity_report` | Lecture seule : staff, groupes, `last_login`, MFA, comptes staff ayant un profil Handyman (L1b) ; formats de téléphone, doublons, emails vides ou en doublon de casse, usernames en doublon de casse ou en forme de numéro, `EmailAddress` divergents, `user_type` (L3a) | L1b, L3a |
| `grant_role` | Attribution ou retrait d'un rôle (superuser, audité, §1.7) | L1b |
| `create_fake_data` (existante, durcie) | Refus si `DJANGO_ENV != 'dev'` ou `DEBUG` faux ; pas de superuser à mot de passe fixe (mot de passe aléatoire affiché une fois) ; profils toujours `draft` ; `--dev-approve` (dev seulement) passe par `KycService` avec `verification_level='seed'`, audit `seed`, exclu du public hors dev | L1b, L5a |
| `normalize_user_phones` | §6.2 | L3a |
| `staff_mfa_enroll` | Enrôlement TOTP par un superuser (§1.7) | L3b |
| `purge_otp_challenges` | Purge (§2.8) | L3a |
| `kyc_legacy_report` | Aperçu exact du §6.4 sur la base courante | L5a |
| `kyc_legacy_request_resubmission` | §6.4 | L5a |
| `kyc_reconcile_publication` | Recalcule `is_published`, liste les écarts (`--apply` pour corriger) | L5a |
| `kyc_verify_audit_chain` | Vérifie les chaînes de hachage (§1.10) | L5b |
| `migrate_kyc_documents_to_private_storage` (existante) | Copie des fichiers legacy vers le stockage privé, juste après l'application de 0027 ; `--delete-source` au plus tard 30 jours après | — |
| `db_validate_constraints` | Liste les contraintes `NOT VALID`, contrôle les données, `--apply` les valide | L5a |
| `kyc_reverify_manual` | Revérification des approbations manuelles (§2.6) | L10 |

L'entrypoint (`entrypoint.sh`) refuse `CREATE_SUPERUSER=1` si `DJANGO_ENV=prod` et que `DJANGO_SUPERUSER_PASSWORD` est vide, vaut `admin` ou fait moins de 16 caractères (L1b).

### 6.8 Runbook de déploiement en production

**Pour tout train qui contient des migrations** :
1. `pg_dump` complet et instantané du bucket KYC ; `showmigrations handy` (vérifier notamment si `0027_private_kyc_document_storage` est déjà appliquée) ; `migrate --plan` ; `sqlmigrate` des migrations `RunSQL`.
2. **Répétition** complète sur un dump de production restauré, chronométrée ; toute migration de plus de 30 s est revue avant le passage réel.
3. Arrêt de `worker` et `beat`. `web` peut rester sur l'ancienne image pendant la migration (DEFAULT durables).
4. `docker compose run --rm migrate` : job unique, rôle `tratra_migrator`, `migrate --noinput` puis `deploy/sql/grants.sql`. En production, `RUN_MIGRATIONS=0` pour `web`, `worker` et `beat` : aucune migration au démarrage, donc ni course entre réplicas ni boucle de redémarrage.
5. Déploiement de la nouvelle image pour `web`, `worker` et `beat` ensemble.
6. `db_validate_constraints` (à blanc), puis `--apply` si les données sont conformes.
7. Vérifications de fumée ; consignation au journal (§0.4).

**Prérequis par train** (variables ajoutées aussi à `.env.example` et au job « Production settings check » de `ci.yml`, toujours avec les drapeaux désactivés par défaut) :

| Train | Prérequis et étapes spécifiques |
|---|---|
| **R1** (L1a, L1b, L1c, L2) | Rôles `tratra_migrator` et `tratra_app` (`roles.sql`) ; IP fixe de Traefik et `TRUSTED_PROXY_IPS` ; `ADMIN_URL` ; suppression du routeur `minio-console` ; comptes de service MinIO (médias, KYC) ; `REDIS_URL` (cache dérivé). Après déploiement : `identity_report`, retrait d'`is_staff` aux comptes non employés (C13), `grant_role` pour les opérateurs. Annonce du gel des approbations (C3) et de la libération différée du séquestre (C12). |
| **R2** (L3a, L3b, L4) | `JWT_SIGNING_KEY`, `JWT_AUDIENCE`, `JWT_ISSUER` (reconnexion unique annoncée) ; textes légaux (C6) ; identifiants SMS et `OTP_PEPPER` (C5) ; Turnstile (C11) ; SMTP pour la vérification d'email. Étapes : migrations 0032 à 0034 ; `staff_mfa_enroll` pour chaque compte staff **avant** d'activer `STAFF_MFA_REQUIRED` ; `identity_report` ; `normalize_user_phones --report`, revue, `--apply`, `--check` ; puis seulement `PHONE_SIGNUP_ENABLED=true` (SMS actif, textes présents). `BOOKING_REQUIRES_PHONE_VERIFIED` reste faux. Front L4 déployé après le backend. |
| **R3** (L5a, L5b, L6, L7a à L7d, et L10 s'il est prêt) | **Go/no-go écrit** : chemin d'approbation opérationnel (L10 en production avec C1 et C6, **ou** C2 accepté) ; C3 ; `KYC_LEGAL_APPROVAL_REF` (C6) ; reviewers désignés (ni Handyman, ni l'artisan staff id 8), enrôlés en MFA, `grant_role` ; `KYC_ENCRYPTION_KEYS`, `IDENTITY_HMAC_KEYS` ; bucket d'ancrage WORM ; cycle de vie et verrouillage d'objet du bucket KYC ; répétition de 0036 avec `kyc_legacy_report`. Étapes : migrations 0035 à 0039 ; **`kyc_legacy_request_resubmission --apply` dans la même fenêtre** ; `kyc_reconcile_publication` (à blanc) ; `db_validate_constraints --apply` ; `KYC_SUBMISSIONS_ENABLED=true` ; fronts L7 ; revalidation. Sans go : R3 reste en préproduction. |
| **R4a** (L8, L9a) et **R4b** (L9b) | Publication sur les stores après R2 (R4a) et R3 (R4b) ; `MIN_APP_VERSION_*` relevé quand la mise à jour doit être forcée. |
| Activation de `BOOKING_REQUIRES_PHONE_VERIFIED` | Après R4a et l'adoption de la version minimale, SMS actif (C4) ; grâce pour les clients sans `X-Tratra-Client` jusqu'à R6. |
| **R5** (L10, s'il n'était pas dans R3) | C1 et C6 ; `KYC_PROVIDER=smile_id`, clés de production, `SMILE_ID_AUTHENTICATED_FULL_RESULT` selon L0, `KYC_WEB_CAPTURE=sdk` ; `kyc_reverify_manual --apply` si C2 a servi. |
| **R6** (L11) | Adoption des nouvelles apps mesurée (requêtes sans `X-Tratra-Client`) ; `LEGACY_SIGNUP_ENABLED=false`, `LEGACY_KYC_DOCS_WRITE_ENABLED=false`, `BOOKING_PHONE_GRACE_LEGACY_CLIENTS=false` ; `normalize_user_phones --check` et rapport d'emails sans doublon, puis 0040 et 0041, `db_validate_constraints --apply`. |

### 6.9 Rollback

- **Politique** : corriger en avant et utiliser les drapeaux (`PHONE_SIGNUP_ENABLED`, `KYC_SUBMISSIONS_ENABLED`, `AUTH_WEB_REFRESH_COOKIE`, `STAFF_MFA_REQUIRED`). Le rollback de schéma est réservé à la fenêtre qui suit immédiatement un déploiement raté.
- **Rollback d'image seul** : sûr grâce aux DEFAULT durables (l'ancienne image insère sans les nouvelles colonnes). Les fronts reviennent à l'image précédente ; les endpoints legacy restent actifs jusqu'à R6.
- **R1** : 0029 et 0031 sont réversibles sans perte ; l'inverse de 0030 refuse s'il existe des `AccountEvent` (journal à conserver).
- **R2**, dans cet ordre : (1) `normalize_user_phones --rollback` sur la nouvelle image ; (2) `migrate handy 0031` (inverses de 0034, 0033, 0032) ; (3) image précédente. Inverse réel de 0033 : suppression des `OTPCode` sans utilisateur (challenges `signup`), `code = '000000'` et `used = true` là où `code` est NULL, emails NULL remplacés par `rollback-<id>@invalid.tratra` avec un `AccountEvent rollback_placeholder_email` (ce qui permet le `SET NOT NULL`). **Destructif** après la première inscription par téléphone (Arbitrages A13). Test aller-retour avec des lignes NULL réelles (`test_migrations_identity.py`).
- **R3** : `migrate handy 0034` enchaîne les inverses de 0039 à 0035 ; l'inverse de 0036 **refuse** dès qu'un événement KYC réel existe : au-delà, `KYC_SUBMISSIONS_ENABLED=false` et correction en avant. Les preuves déjà stockées restent dans le bucket (verrouillage d'objet).

---

## 7. Frontend React (Next.js 14, `frontend/`)

Base de travail : l'arbre **après** le commit du lot public. Vérification : `npm run verify` (typecheck et build) en CI, plus deux garde-fous ajoutés au script `verify` : `grep -rn "user_type" src | grep -v "lib/types.ts"` doit être vide (à partir de L4), et aucune clé `is_verified` lue dans `src` (à partir de L7d). Smoke Playwright local (`npm run e2e`, A12) et recette du §9.3.

### 7.1 Socle (L4)

| Fichier | Action |
|---|---|
| `package.json` | `libphonenumber-js` (métadonnées `/max`, chargées sur les pages d'authentification), `@playwright/test` en dépendance de développement (smoke local). |
| `src/lib/api.ts` | Access token **en mémoire**. `NEXT_PUBLIC_AUTH_MODE=cookie\|bearer` (défaut `cookie`). En-tête `X-Tratra-Client: web` sur **toutes** les requêtes API ; `credentials: "include"` seulement sur `/auth/*`. `refreshAccess` sous `navigator.locks` avec `BroadcastChannel`. **Aucune boucle 401 → refresh → rejeu sur `/auth/*`** ; la connexion est appelée avec `retry=false`. Sur `session_revoked` ou `account_inactive` : purge immédiate et redirection vers `/login` avec un message dédié. `ApiError` expose `code`, `fields` (liste de `{code,message}`), `retryAfter`, `challenge`. `apiErrorMessage` lit `detail`, puis `fields[].message`. `upload(path, form, {method})`. Migration : `tokens.migrateLegacy()` (dernier refresh bearer avec l'en-tête web, puis purge du `sessionStorage`). |
| `src/lib/types.ts` | `Me`, `Capabilities`, `HandymanCapability`, `PublicConfig`, `ApiErrorBody`, puis (L7) `Application`, `KycOverview`, `KycDocument`, `HandymanProof`, `PublicHandyman`, `AdminKyc*`. `UserType` marqué `@deprecated`. |
| `src/lib/config.ts` | `usePublicConfig()` sur `GET /public/config/` (pays, textes légaux, anti-bot, support, vérification d'email) ; plus de liste de pays en variable d'environnement. Suppression de `HOME_BY_ROLE`. |
| `src/lib/phone.ts` (nouveau) | `parsePhone(raw, country)`, `toE164`, `formatNational`, `isValidMobile`. |
| `src/lib/capabilities.ts` (nouveau) | `canBook(me)`, `hasHandyman(me)`, `isStaff(me)`, `hasPerm(me, p)` (codenames sans préfixe), `defaultSpace(me)` (dernier espace mémorisé dans `localStorage` `tratra.space`, sous `try/catch`). |
| `src/lib/copy.ts` | Lecture de `docs/api-contracts/copy.fr.json` (copié au build) : libellés des statuts, des codes `missing` et des erreurs. |
| `src/lib/links.ts` | Suppression de `AREA_ROLES` et `HOME_BY_ROLE` ; prédicats par espace (`/client` : connecté ; `/worker` : `hasHandyman` ; `/admin` : `isStaff` ; `/company` : connecté). `safeNext(next, me)`. `bookingHref(id, me)` : visiteur → `loginHref(target)` ; téléphone non vérifié et `can_book` faux → `/account/verify-phone?next=` ; sinon la cible (**un Handyman peut réserver**). `registerHref("handyman")` **reste inchangé en L4** (`/register?type=handyman`) ; la bascule vers `/proposer-un-service` a lieu en L7a. |
| `src/lib/auth.tsx` | `user: Me \| null` ; `login({phone}\|{identifier}, password, next)` ; `startSignup(payload)` ; `verifySignup(challenge, code)` (gère `legacy_account_found`) ; `claim(token, action, …)` ; `resend` ; `refreshMe` ; `logout` ; `logoutAll` ; `verifyMfa(code)`. |
| `src/components/RequireAuth.tsx` (nouveau, remplace `RoleGuard`) | Props `check?: (me) => boolean`, `fallback?: string` ; mécanisme `hadUser` et `loginHref` conservé. `RoleGuard.tsx` supprimé. |
| `src/components/auth/*` | `PhoneInput`, `OtpInput` (`autocomplete="one-time-code"`), `PasswordField`, `ResendTimer`, `Challenge` (Turnstile chargé à la demande sur 428), `MfaPrompt` (sur 403 `mfa_required`). |
| Layouts | `client` : `RequireAuth`. `worker` : `RequireAuth check={hasHandyman}`, sinon page « Devenir artisan » (bouton branché sur `POST /users/me/handyman/`, L3b). `admin` : `RequireAuth check={isStaff}` et `MfaPrompt`. `company` : `RequireAuth` (création du profil entreprise via `POST /companies/me/` existant). |
| `src/components/DashboardShell.tsx` | Badge `user_type` supprimé ; **sélecteur d'espace** (Client ; Handyman si `hasHandyman` ; Entreprise si `company` ; Admin si `isStaff`) ; navigation mobile. |
| `client/page.tsx`, `worker/page.tsx` | `GET /bookings/?client=<me.id>` et `?handyman=<me.id>` (un compte à double rôle ne mélange plus ses listes). `worker/page.tsx` affiche l'état réel (`capabilities.handyman`, libellés de `copy.fr.json`) et, avant R3, le lien vers `/worker/kyc` (upload legacy, encore actif). |
| `components/landing/FinalCta.tsx`, `LatestServices.tsx`, `BusinessSection.tsx` (lot public) | Remplacement de `user_type` par `hasHandyman(me)` et `me.capabilities.company`. |
| `components/site/SiteHeader.tsx`, `SiteFooter.tsx`, `market/ServiceCard.tsx`, `search/SearchClient.tsx` | `ServiceCard` utilise le nouveau `bookingHref` ; le texte « Réservation ouverte aux comptes client et entreprise » disparaît. Le pied de page affiche les liens `/cgu` et `/confidentialite` seulement s'ils existent dans la configuration. |
| `app/challenge/page.tsx` | Page minimale du défi Turnstile, utilisée par la webview Flutter (A11) : renvoie le jeton via `window.TratraChallenge.postMessage`. |
| `next.config.mjs`, `public/sw.js`, `robots.ts` | §5.11 (hors CSP à nonce, livrée en L7b et L7c). |

### 7.2 Pages d'authentification et de compte (L4)

| Route | Contenu |
|---|---|
| `/login` | `PhoneInput` (pays par défaut de la configuration) et mot de passe ; lien « Se connecter avec un identifiant » (username ou email, comptes legacy) ; « Mot de passe oublié ». `?next=` respecté. Messages distincts : identifiants invalides, trop de tentatives (délai), session révoquée, erreur réseau. |
| `/register` | Étape 1 : prénom, nom, téléphone, mot de passe, confirmation, acceptation des CGU et de la politique de confidentialité (liens vers les textes). Étape 2 (même route, état local ; le `challenge_id` n'est **jamais** dans l'URL) : `OtpInput`, minuterie de renvoi, « Modifier le numéro ». Si `legacy_account_found` : écran « Un compte existe déjà avec ce numéro » avec les options reçues (« C'est mon compte » → mot de passe legacy ; « J'ai oublié son mot de passe » si `recover` ; « Créer un nouveau compte »). Défi Turnstile si 428. Puis `next` ou `/client`. `?type=handyman` : après création, `POST /users/me/handyman/` puis `/worker` (jusqu'à L7a) ; `?type=entreprise` → `next=/company`. Inscription indisponible (configuration) : message explicite, aucun formulaire actif. |
| `/forgot-password` | Téléphone, puis code et nouveau mot de passe (gestion de `password_too_similar` sans renvoyer de SMS), puis succès et lien vers `/login`. |
| `/cgu`, `/confidentialite` | Rendu Markdown de `/public/legal/terms/` et `/privacy/` (version et date affichées) ; 404 réel si le texte n'existe pas. |
| `/account` | Photo (aperçu, suppression, mention « visible publiquement si vous êtes Handyman »), noms (verrouillés pendant le KYC, avec explication), email (en attente de vérification affiché ; lecture seule si la vérification d'email est indisponible), adresse, commune (liste), quartier, ville, préférence SMS. |
| `/account/email/verify` | Lit `?token=`, appelle `POST /users/me/email/verify/`, affiche le résultat. |
| `/account/security` | Changer le mot de passe ; « Déconnecter tous les appareils » ; désactiver le compte (`POST /users/me/deactivate/`, mot de passe). |
| `/account/phone` | Changement de numéro : nouveau numéro et mot de passe, puis OTP. |
| `/account/verify-phone` | Comptes legacy : OTP sur le numéro actuel, ou bascule vers le changement de numéro. |
| `/account/notifications` | Liste paginée de `/notifications/` (existant), lecture et marquage ; aucune mention de notifications push. |
| `/worker/versements` (nouveau ; React n'a aujourd'hui que le solde disponible sur `/worker`) | Compte de versement avec mot de passe puis OTP (`/payout-account/` puis `confirm/`) ; date de fin de retenue affichée. Flutter l'implémente en L9a (`handyman_service.dart:68` appelle aujourd'hui `POST /payout-account/` directement). |

### 7.3 Candidature, services, KYC, admin, profil public (L7a à L7d, train R3)

**L7a, candidature et services** :

| Route | Contenu |
|---|---|
| `/proposer-un-service` (public) | Présentation, étapes, conditions (vérification d'identité, documents à préparer, au moins un service) ; CTA « Commencer ma candidature ». Le CTA global du site (`SiteHeader`, landing, `registerHref("handyman")`, repli de `worker/layout`) bascule **dans ce lot** vers cette page. |
| `/proposer-un-service/candidature` (public) | Formulaire en étapes, **sans compte** : métiers, spécialités (étape sautée si aucune sous-catégorie ; spécialités libres), expérience, zone (commune dans le référentiel, quartier, rayon, position facultative), description, tarifs, disponibilités, **mes services** (au moins un : catégorie parmi les métiers, titre, description, type de prix, prix, durée), justificatifs facultatifs (fichiers gardés en mémoire seulement, mention « non conservés si vous quittez la page »). Brouillon des champs non sensibles dans `localStorage` (`tratra.handyman-draft.v1`, sous `try/catch`). Dernière étape **« Continuer vers la vérification d'identité »** : connexion ou inscription en ligne avec OTP si besoin, puis : si `capabilities.handyman` existe déjà, **aucun envoi automatique** : écran « Vous avez déjà un profil Handyman (statut …) » avec « Mettre à jour avec ces informations » (comparaison champ par champ, puis `PATCH`) ou « Aller à mon espace » ; sinon `PUT /users/me/handyman/` avec `create_only: true` (409 traité de la même façon), puis création des services (`POST /services/`), puis justificatifs, puis suppression du brouillon et redirection vers `/worker/verification`. |
| `/worker` | Bandeau d'état (`status`, `status_message`, `missing` et `missing_for_online` avec liens) ; interrupteur de présence initialisé avec l'état **réel**, désactivé avec explication si `!can_go_online`. |
| `/worker/profil` | Candidature en mode connecté (`PATCH`), écarts legacy à résoudre (`legacy_constraints_violations`), grille préremplie depuis `legacy_availability`. |
| `/worker/services` | Liste, création, modification, désactivation des services ; images (`/service-images/`). |
| `/worker/justificatifs` | `HandymanProof` : liste, ajout, retrait, statut de revue. |
| `/worker/kyc` (legacy) | **Supprimée** ; redirection vers `/worker/verification`. |

**L7b, KYC web** (`/worker/verification`, CSP à nonce, caméra autorisée sur cette route seulement) : assistant piloté par `GET …/kyc/` :
1. Consentement (texte intégral servi par l'API, case à cocher) — **avant** toute capture.
2. Canal `inhouse_web` : CNI recto et verso (`<input type="file" accept="image/jpeg,image/png" capture="environment">`, aperçu, contrôle local de netteté et des dimensions de `requirements`, réencodage canvas aux tailles cibles) ; selfie et liveness (`LivenessCapture` : `getUserMedia({video:{facingMode:"user"}})`, consignes « Regardez l'objectif », « Tournez lentement la tête à gauche », « à droite », « Souriez », 6 à 8 images JPEG redimensionnées à 640 px, un selfie de face à 1 280 px, intervalle **mesuré** envoyé dans `capture_meta`). Canal `sdk_web` (L10) : composant `SmileWebCapture` qui obtient la session (`provider-session`) et charge le SDK hébergé.
3. Récapitulatif et soumission. Message clair : « Votre dossier sera vérifié par notre équipe » (capture maison) ou « Vérification automatique en cours » (SDK).
- Caméra indisponible ou refusée : message explicite ; lien vers l'application **seulement** si `NEXT_PUBLIC_ANDROID_URL` ou `NEXT_PUBLIC_IOS_URL` est configuré, sinon **QR code** (paquet `qrcode`) vers `/worker/verification` à ouvrir sur le téléphone. Aucun selfie depuis la galerie.
- Ré-authentification (`reauth`) : même composant de capture, envoi sur `…/kyc/reauth/`.

**L7c, administration KYC** (CSP à nonce et Trusted Types sur `/admin`, `MfaPrompt`) :

| Route | Contenu |
|---|---|
| `/admin/kyc` (remplace la page legacy) | File : onglets par statut avec compteurs (`stats/`), filtres (mode, canal, legacy, drapeau, « à moi », attente du second approbateur), pagination, ancienneté. |
| `/admin/kyc/[id]` | Visionneuse : `<img src="blob:">` (type forcé), `revokeObjectURL` au démontage, **filigrane** « Confidentiel, nom du reviewer, date » ; PDF en téléchargement seulement ; indicateur « vu » par pièce (condition de décision) ; selfie enrôlé côte à côte pour une ré-authentification ; identité, candidature, verdicts prestataire, drapeaux, doublons, consentement, métadonnées de capture marquées « non fiables », tentatives précédentes ; liste de contrôle ; décision (codes de motif, message prérempli, note interne) ; quatre yeux (« En attente du second approbateur : X », bouton de confirmation pour une autre personne) ; prise en charge ; bris de glace motivé ; historique. Actions limitées à `allowed_actions`. |
| `/admin/kyc/handymen` | Liste des profils (`GET profiles/`) avec filtres ; fiche profil : suspendre, réhabiliter, révoquer, autoriser une resoumission, lever le gel des fonds, revue des justificatifs, historique. |
| Navigation admin | Entrées masquées sans la permission correspondante (`hasPerm`). |

**L7d, profil public, référencement, bascule des badges** :

| Élément | Contenu |
|---|---|
| `/artisans/[userId]` (public, SSR, `cache: "no-store"`) | `GET /public/handymen/{user_id}/` ; `notFound()` sur 404 (jamais de soft-404) ; `generateMetadata` (« Prénom N. – Métier à Commune ») ; JSON-LD `LocalBusiness` sans donnée personnelle (nom d'affichage, métier, commune, note) ; badge `VerifiedBadge` si `identity_verified`, mention « Pièce contrôlée par Tratra » si `verification == "document_checked"` ; services, avis, réservation. `ArtisanCard` y pointe. |
| `sitemap.ts` | Dynamique : pages statiques et `/artisans/{user_id}` depuis `GET /public/handymen/?fields=user_id,updated_at`, tag `public-artisans`. |
| `lib/public.ts`, `app/api/revalidate/route.ts` | Tags, revalidation à la demande, `revalidate` 60 s sur les listes (§3.6), en-tête `X-Internal-Render` pour les appels SSR. |
| `search/FiltersPanel.tsx`, `SearchClient.tsx`, `useSearchState.tsx` | **Suppression** du filtre « Vérifiés », de sa puce, du compteur et de l'état `verified` (le paramètre d'URL est ignoré). |
| `market/ServiceCard.tsx`, `ArtisanCard.tsx`, types | Badge sur `identity_verified === true` uniquement ; suppression de toute lecture de `is_verified`. |
| `client/bookings/[id]`, `worker/missions/[id]` | Bandeau si `handyman_available` est faux ; mention « Annulation sans frais » si `cancellation_fee_waived` ; bouton « Confirmer la fin de la mission » (`confirm-completion`, L1c) côté client. |

Règle « aucun bouton inactif » : toute action affichée est branchée ; une action indisponible est masquée, ou désactivée avec une explication visible.

---

## 8. Application Flutter (`/Users/ogahserge/Documents/handy_tratra/flutter_tratra`)

Contraintes : Flutter 3.38.5 et Dart 3.10, **sans SDK prestataire** (A2, C14). CI : `flutter analyze` puis `flutter test` (`.github/workflows/mobile-ci.yml`), plus le contrôle d'empreinte des fixtures (§4.14).

**Préalable bloquant (C9)** : le dépôt parent contient environ 56 fichiers non commités. **Aucun commit n'est fait dans ce dépôt sans l'accord explicite de l'utilisateur dans la conversation.** Avec cet accord : commit « baseline » du travail existant tel quel sur `baseline/2026-10`, puis nos lots sur `feat/compte-unique-kyc`. Sans accord, L8 et L9 ne démarrent pas.

### 8.1 Corrections préalables (L8)

| Problème | Correctif |
|---|---|
| Une instance `BaseApi` par service : fuite du jeton du compte précédent | `lib/core/api_client.dart` : **une seule** instance `ApiClient` fournie par `Provider<ApiClient>.value` ; services par composition (`HandymanService`, `BookingService`, `PaymentService`, `ReviewService`, `MessagingService`, `NotificationService`, `MatchService`, `CategoryService`) ; `clearTokens()` vide mémoire et stockage sécurisé. |
| Refresh concurrent | `auth_http_client.dart` : `Completer<String?> _refreshing` partagé ; une seule rejouée par requête ; **aucun refresh sur `/auth/*`**. |
| Échec du refresh sans déconnexion | `onSessionExpired` → `Session.expire()` → `/login` avec `returnTo` ; pas de rejeu sans authentification ; `session_revoked` et `account_inactive` purgent immédiatement. |
| Upload multipart en `application/octet-stream` | `lib/core/multipart.dart` : `fileWithContentType(field, path)` (`mime`, `http_parser`), refus local des types non autorisés. |
| Erreurs non typées | `lib/core/api_error.dart` : `ApiException{status, code, detail, fields, retryAfter, challenge}`, repli sur le format DRF. |
| `isAuthenticated` sur le cache | `Session` reconstruite depuis `GET /users/me/` au démarrage. |
| En-têtes | `X-Tratra-Client: android\|ios`, `X-Tratra-App-Version`, `X-Tratra-Device` (jeton stocké dans `flutter_secure_storage`). |

Dépendances : `http_parser`, `mime`, `phone_form_field ^12.0.1`, `camera` 0.11.x, `flutter_image_compress`, `webview_flutter` (défi), `screen_protector` (`FLAG_SECURE`, masquage iOS). Vérifier les contraintes Dart au `pub get`.

### 8.2 Parcours compte (L9a, après R2)

| Élément | Fichiers et règles |
|---|---|
| Modèles | `lib/models/me.dart` (`Me`, `Capabilities`, `HandymanCapability`, `email` nullable), `public_config.dart`. `models/user.dart` : `toProfileUpdateJson()` **sans `phone`** (test `test/models_contract_test.dart:89-95` mis à jour). |
| Services | `auth_service.dart` (connexion par téléphone ou identifiant, inscription, revendication, renvoi, réinitialisation, changement de mot de passe, déconnexions), `account_service.dart` (me, patch, photo, email, téléphone, désactivation, compte de versement avec OTP), `config_service.dart` (`/public/config/`, `/public/legal/`). Chemins `loginWithUsername` et `registerWithDetails` retirés du code appelé. |
| Routage | `initialRoute: '/'` (catalogue public) ; `lib/core/route_guard.dart` : `requireAuth(context, routeName, {args})` vers `/login` avec `returnTo`. Écran de **mise à jour forcée** si `X-Tratra-App-Version` < `min_app_version`. Dernier espace (client ou Handyman) mémorisé dans `SharedPreferences`. |
| Authentification | `login_screen.dart`, `register_screen.dart` (prénom, nom, téléphone, mot de passe, CGU et confidentialité), `otp_screen.dart` (inscription, réinitialisation, vérification, changement de numéro, versement ; `AutofillHints.oneTimeCode`, SMS User Consent sur Android), `claim_account_screen.dart` (options de `legacy_account_found`), `forgot_password_screen.dart`, `challenge_screen.dart` (webview vers `/challenge`). `FLAG_SECURE` sur OTP et mot de passe. |
| Compte | `profile_screen.dart` (photo via `image_picker` puis multipart typé), `change_phone_screen.dart`, `change_password_screen.dart`, `verify_phone_screen.dart`, `security_screen.dart`, `notifications_screen.dart` (`/notifications/`), `legal_screen.dart` (CGU, confidentialité). |
| Accueil | Barre du bas : « Profil », « Réservations », « Messages » **branchés** sur les écrans existants, ou masqués s'ils ne le sont pas (`home_screen.dart:944-947`, `2593-2597`). Mentions codées en dur « Pros vérifiés » (`home_screen.dart:1466,1795`) remplacées par les chiffres de `/public/stats/` ou supprimées. |
| Réservations | Bandeau `handyman_available` et `cancellation_fee_waived` ; « Confirmer la fin de la mission » (client). |

### 8.3 Parcours Handyman et KYC (L9b, après R3)

| Élément | Fichiers et règles |
|---|---|
| Modèles | `application.dart`, `kyc.dart`, `handyman_proof.dart`, `public_handyman.dart`. `Artisan.fromJson` et `artisan_profile_screen.dart` **réécrits** sur la fixture `PublicHandyman` : badge sur `identity_verified == true` uniquement (suppression de `is_approved`, `is_certified`, `isCertified`), services embarqués. |
| Profil public | `artisan_profile_screen.dart` appelle `/public/handymen/{user_id}/` avec `Service.handyman` (id utilisateur) : fin de la confusion entre id de profil et id utilisateur (`service_detail_screen.dart:265`). |
| Proposer un service | Bouton sur l'accueil et le profil ; `propose_service_screen.dart` (public) ; `application_form_screen.dart` (Stepper, brouillon `SharedPreferences` `handyman_draft_v1` sans données sensibles, `requireAuth` à la fin, règle « profil existant » identique au web, `create_only`) ; `worker_services_screen.dart` (CRUD des services et images) ; `proofs_screen.dart`. |
| KYC | `kyc_flow_screen.dart` : consentement **d'abord** ; CNI via `image_picker` (`imageQuality: 85`, `maxWidth: 2400`, JPEG forcé, HEIC converti par le plugin), galerie permise pour la CNI ; `liveness_capture_screen.dart` : `CameraController(ResolutionPreset.medium, enableAudio: false, imageFormatGroup: ImageFormatGroup.jpeg)`, caméra frontale, consignes à l'écran, 6 à 8 `takePicture()` avec horodatage réel, redimensionnement et compression **dans un isolate** (`flutter_image_compress` : 640 px et 300 Ko maximum par image, 1 280 px pour le selfie), prévalidation locale contre `requirements`, recommencer ; envoi multipart typé. Fichiers temporaires **supprimés** après envoi ou abandon (test unitaire). `FLAG_SECURE` et masquage de l'aperçu iOS sur tous les écrans KYC. `kyc_status_screen.dart` : six états, message, `missing`, actions, ré-authentification. |
| Espace Handyman | `worker_home_screen.dart` : bandeau d'état, présence initialisée par `GET /users/me/handyman/` (`online`, `can_go_online`, `missing_for_online`), bascule vers l'espace client. `kyc_screen.dart` (legacy) remplacé. Android : `android.permission.CAMERA` dans le manifeste fusionné ; iOS : `NSCameraUsageDescription` adapté. |

---

## 9. Stratégie de tests

### 9.1 Backend (pytest, `DJANGO_ENV=dev venv/bin/pytest`)

**Socle** : `handy/conftest.py` (créé en L1a, enrichi à chaque lot).
- Fixture **autouse** `_test_settings(settings)` : `SMS_BACKEND="locmem"`, `OTP_SEND_ASYNC=False`, `KYC_TASKS_ASYNC=False`, `CELERY_TASK_ALWAYS_EAGER=True`, `BOOKING_REQUIRES_PHONE_VERIFIED=False`, `STAFF_MFA_REQUIRED=False`, `PHONE_SIGNUP_ENABLED=True`, `KYC_SUBMISSIONS_ENABLED=True`, `ANTIBOT_PROVIDER=""`, `CACHES` LocMem (vidé), clés de test (`OTP_PEPPER`, `IDENTITY_HMAC_KEYS`, `KYC_ENCRYPTION_KEYS`, `JWT_SIGNING_KEY`). Aucune valeur par défaut n'est dérivée de `DEBUG` dans `base.py` (la CI exporte `DEBUG=False`) ; les `ImproperlyConfigured` vivent dans `prod.py`. Les tests qui vérifient un comportement activé (MFA, défi, drapeau de réservation) le posent eux-mêmes.
- `run_on_commit` : `django_capture_on_commit_callbacks(execute=True)` pour les tests qui dépendent d'un `on_commit` (envoi, invalidation, notifications).
- Fabriques : `api_client`, `sms_outbox`, `kyc_storage` (stockage privé en mémoire), `make_user(phone=…, phone_verified=True, **kw)`, `make_staff(perms=[…], mfa=True)` (jetons avec `amr`), `make_handyman(kyc_status=…)` (via `KycService.force_state_for_tests`, réservé aux tests), `make_publishable_handyman(**kw)` (profil complet **avec un service**), `jpeg_bytes(w, h)`, `pdf_bytes()`, `smile_mock`, `freeze_now`, `ensure_groups_and_plans` (mêmes fonctions que les migrations, après un flush).

**Fichiers par lot** :

| Lot | Fichier | Cas principaux |
|---|---|---|
| L1a | `test_l1_security_fixes.py` | `PATCH /handymen/{id}/` avec `is_approved`, `user`, `rating` ignorés ; création et suppression en 405 ; liste et détail d'un tiers en 404 ; `POST /services/` au nom d'autrui forcé sur soi, client sans profil en 403 ; IDOR `ServiceImage` (404) et `PATCH service` vers le service d'un tiers refusé ; `?handyman=<autre id>` ne montre que les services publics ; `image_url` hors hôtes refusée ; EXIF retirés d'une image de service ; PATCH du mot de passe en 400 (hachage inchangé) ; `DELETE /users/{id}/` en 405 ; inscription legacy : `phone` ignoré, conflits sous `signup_unavailable`, `validate_password` ; réservation incohérente en 400, réservation de soi-même en 400 ; `PublicUserMini` = `{id, first_name, display_name}`. |
| L1a | `test_lot1_public.py` (mis à jour) | Ensemble de clés `PublicUserMini` ; `SENSITIVE_KEYS` inchangé. |
| L1b | `test_l1b_staff_rbac.py` | Formulaire admin : champs de privilège désactivés pour un non-superuser et pour soi-même ; `GroupAdmin` réservé ; événements `privilege_*` et `staff_flag_changed` avec acteur ; un staff `change_user` ne peut pas s'ajouter à un groupe ; lecture globale avec `view_all_records` seulement ; aucune écriture staff sur l'objet d'autrui ; `resolve` sur son propre litige en 403 `self_dealing_forbidden`, sans `resolve_dispute` en 403 ; documents legacy : tiers non superuser en 403, superuser journalisé ; `approve_profiles` absente ; **aucun chemin** (API, admin, action) ne fait passer `is_approved` de faux à vrai (paramétré) ; `create_fake_data` refusée avec les réglages de production ; `PATCH /users/{id}/` d'autrui en 403. |
| L1b | `test_db_roles.py` | Rôle temporaire aux droits de `tratra_app` : UPDATE, DELETE et TRUNCATE refusés sur `handy_accountevent` (puis, en L5a, sur les tables KYC) ; trigger actif. |
| L1c | `test_l1c_booking_actors.py` | Table des transitions par rôle ; fin déclarée par l'artisan : `completed` sans libération, `release_after = +48 h` ; `confirm-completion` par le client libère ; tâche de libération à échéance ; litige ouvert bloquant ; `test_sprint4.py` toujours vert. |
| L2 | `test_infra_security.py` | `get_client_ip` (XFF falsifié, proxy non approuvé, 1 et 2 sauts) ; clé IPv6 /64 (rotation dans un même /64 bloquée) ; `get_ident` DRF ; axes par couple ; garde dans le backend, y compris l'admin (20 essais, 20 IP) ; jeton d'appareil connu non bloqué ; plafond d'1 h ; connexion « Serge » pour « serge » ; email présent seulement dans `EmailAddress` ; exactement 3 `check_password` (espion) ; Sentry : exception dans le backend SMS sans code ni numéro (transport factice) ; `RedactFilter` ; backends SMS ; middleware `no-store` ; `PrivateKycS3Storage.url()` lève une erreur ; pas de repli sur `default_storage` ; contrôles de démarrage de `prod.py` (CORS, `ADMIN_URL`, `SENTRY_SEND_PII`). |
| L3a | `test_auth_signup_otp.py` | Code dans `outbox`, compte créé et vérifié, jetons ; `attempts_left` ; 5 échecs → `otp_locked` ; 6ᵉ essai sans IntegrityError ; expiration posée à l'envoi ; renvoi (429 `resend_in`, ancien code invalidé, 4ᵉ envoi refusé) ; pays non autorisé ; numéro fixe ; consommation atomique ; aucun code en clair (base, `caplog`, réponse, DEBUG compris) ; 503 tant que `normalize_user_phones --check` échoue. |
| L3a | `test_otp_quota.py` (`transactional_db`) | 20 threads sur un numéro → exactement 5 envois ; familles séparées (saturation `signup` sans effet sur `reset`) ; réserve de budget ; plafond par préfixe ; seuil IP → 428 puis jeton accepté ; budget épuisé → 503 et coupure du pays pour la famille. |
| L3a | `test_auth_enumeration.py` | Inscription numéro vérifié contre libre : mêmes statut et clés, SMS d'information, leurre toujours `otp_invalid` ; réinitialisation connu contre inconnu ; mot de passe égal au nom : réponses identiques leurre et réel avant le code ; test de temps (`slow`). |
| L3a | `test_auth_claim.py` | `legacy_account_found` après OTP ; `claim` (mot de passe legacy, 5 essais, réactivation d'un compte désactivé) ; `recover` seulement sans valeur ; `create_new` (numéro libéré, notification de l'ancien compte) ; jeton expiré. |
| L3a | `test_auth_login_refresh.py` | Connexion par E.164 et par `07…` ; 401 avec `X-Tratra-Client`, 400 sans ; mode cookie ; `Origin: null` refusée ; deux refresh concurrents → un seul succès ; réutilisation après 30 s → sessions révoquées ; refresh déconnecté sans révocation ; jeton sans `sv` accepté ; `jti` refusé après déconnexion. |
| L3a | `test_auth_password_reset.py` | Validation en deux temps ; similarité après le code sans consommer le challenge ; staff et compte à valeur non vérifié → leurre ; sessions révoquées, axes remis à zéro, SMS, retenue de 72 h. |
| L3a | `test_migrations_identity.py`, `test_db_defaults.py` | `MigrationExecutor` 0031 → 0034 avec téléphones `0575…`, `''`, doublons, 8 chiffres, email `''`, OTP en clair ; inverse jusqu'à 0031 avec des emails NULL et des OTP sans utilisateur ; DEFAULT en base présents ; insertion « ancienne image » (SQL sans les nouvelles colonnes) réussie. |
| L3b | `test_auth_me_account.py` | Forme `Me` (sans `is_verified`), correspondance pré-L5 ; PATCH (préférences fermées, `phone` identique accepté, différent refusé, noms verrouillés) ; email en attente, réponse identique libre ou pris, lien de vérification ; désactivation ; photo sans EXIF. |
| L3b | `test_auth_phone.py`, `test_payout_stepup.py`, `test_staff_mfa.py`, `test_public_config_legal.py` | Changement de numéro (leurre, éviction, SMS à l'ancien numéro, retenue) ; compte de versement en deux étapes, empreinte, ancien client en 403 `step_up_required` ; routes staff en 403 `mfa_required` sans `amr` ; `/public/config/` et textes légaux (404 si absents, empreinte). |
| L5a | `test_kyc_state_machine.py` | Chaque transition autorisée et un échantillon d'interdites ; CHECK (`IntegrityError` si `is_approved=True` avec `draft`) ; journal append-only ; `PROTECT` ; plafond de tentatives ; tentative créée une seule fois sous concurrence. |
| L5a | `test_kyc_reserved_fields.py` | `save()` complet sans champ réservé ; `update_fields` réservé → erreur ; instance périmée (`refresh_quality_score`) après suspension : ni republication ni erreur de CHECK. |
| L5a | `test_publication.py` | Pour chacune des 12 conditions (paramétré) : présence puis **absence immédiate** sur `/services/`, détail, `nearby`, `featured`, `services_count`, `public/stats`, `match`, `alternatives`, `replacements`, `slides`, `/reviews/public/`, favoris, `/public/handymen/` et profil public. Présence refusée sans position. Suspension pendant une réservation `confirmed` : réservation intacte, client notifié, gratuité ; artisan legacy dépublié : pas de gratuité ; paiement et versement en 409 ; `funds_frozen`. `public_location` et paliers de rayon (deux origines voisines ne trahissent pas plus que la cellule). Invalidation et revalidation. Réconciliation. |
| L5a | `test_kyc_legacy_mapping.py`, `test_migrations_kyc.py`, `test_audit_chain.py` | Les 7 branches de `map_legacy_v1` ; migration 0034 → 0037 avec créneaux invalides et rayons hors bornes, puis inverse (refusé dès un événement réel) ; signal `user_type='handyman'` après 0037 ; chaîne vérifiée, rupture détectée. |
| L5b | `test_kyc_approval_cases.py` | Cas A, B, C, D, chacun avec son jeu de conditions ; `evidence_not_reviewed` ; `duplicate_identity` (409 hors cas C) ; même CNI sur un profil révoqué pour fraude → rejet définitif ; quatre yeux (même personne → 409, rejet annule, expiration à 72 h) ; legacy jamais approuvable ; `sandbox` jamais badgé ; mode manuel refusé sans C2. |
| L5b | `test_kyc_admin_api.py` | RBAC (non staff, staff sans permission, Support sans pièces), MFA, son propre dossier (superuser compris), prise en charge, périmètre des preuves et bris de glace, throttle et alerte, `evidence_viewed` à chaque téléchargement, liste des profils, suspension, réhabilitation, révocation, levée du gel, filtres et pagination, `allowed_actions`. |
| L6 | `test_handyman_application.py`, `test_kyc_candidate_api.py`, `test_handyman_proofs.py`, `test_kyc_reauth.py` | `create_only` ; règles sur les seuls champs modifiés ; services et `category_not_in_trades` ; consentement **avant** tout upload ; changement de version → purge ; 10 remplacements ; quota ; fichiers chiffrés au repos (octets stockés ≠ contenu) ; fichier du propriétaire, tiers en 404 ; soumission manuelle → `review` ; justificatifs indépendants des tentatives ; ré-authentification. |
| L10 | `test_kyc_provider_smile.py` | Session SDK ; soumission maison (champs, `user_id` opaque, consentement, verso) ; webhook à signature invalide → 401 **sans ligne en base** ; **corps forgé avec une signature valide rejouée : aucune influence** sur drapeaux ou transition ; discordance `user_id` → revue ; capacité « résultat authentifié » absente → aucune approbation automatique ; toutes les lignes du §2.5 ; copie des preuves SDK ; relecture à 48 h ; aucun `image_links` ni `id_number` en base. |
| transverse | `test_coded_errors.py` | Chaque endpoint existant qui émet un code (§4.0) renvoie `{code, detail}`. |
| transverse | `test_api_contract_fixtures.py` | §4.14 (fixtures ajoutées au fil des lots). |
| transverse | **`test_journeys.py`** | Un test par parcours du point 10 du brief, en appels HTTP comme les clients (mode cookie web et mode bearer mobile, SMS locmem) : `test_inscription`, `test_otp`, `test_connexion`, `test_recuperation` (L3a) ; `test_conversion_client_handyman`, `test_kyc_rejete_puis_resoumis_puis_approuve` (cas D avec C2 activé en test et quatre yeux), `test_publication`, `test_suspension`, `test_controle_des_permissions` (L6) ; `test_kyc_prestataire` (L10, cas A et B). |

**Tests existants à migrer** : `test_sprint6.py` (OTP : `outbox` au lieu de `otp.code`), `test_security_sprint1.py:46,57` et `test_phase1.py:15` (mot de passe fort), `test_sprint4bis.py:156-166`, `test_sprint2.py:117-142`, `test_sprint5.py:40`, `test_sprint6.py:39,49`, `tests.py:61,103-160`, `test_sprint7.py:35` (via `make_publishable_handyman`), `test_lot1_public.py` (`_artisan(approved=True)` → `make_publishable_handyman` ; `test_services_filters` : plus de services inactifs ni d'artisans non publiables dans la liste publique, à partir de L5a). `test_sprint4.py:129` reste **inchangé et vert**.

**Objectif** : les ~70 tests existants verts (migrés), environ 220 nouveaux. Aucun test supprimé sans remplacement équivalent.

### 9.2 Flutter

- `flutter analyze` sans nouvel avertissement, puis `flutter test` ; contrôle d'empreinte des fixtures.
- L8 : `test/core/api_client_refresh_test.dart` (`MockClient`) : trois 401 simultanés → un seul refresh ; aucun refresh sur `/auth/*` ; échec → `onSessionExpired` une fois ; changement de compte → nouveau jeton partout. `test/core/multipart_test.dart` (JPEG, PNG, PDF ; refus de `.heic` non converti). `test/core/phone_test.dart`.
- L9a : `test/contracts/*_test.dart` (`Me` client, pré-L5 et staff, `PublicConfig`, erreurs codées, `toProfileUpdateJson` sans `phone`) ; **tests de widgets** avec `MockClient` : inscription → OTP → accueil ; `legacy_account_found` → revendication ; mot de passe oublié ; mise à jour forcée.
- L9b : contrats (`Application`, `KycOverview`, `HandymanProof`, `PublicHandyman`) ; widgets : formulaire public → `requireAuth` → reprise du brouillon → `PUT` (et cas « profil existant ») ; `kyc_status_screen` sur les six états ; nettoyage des fichiers temporaires (test unitaire) ; compression d'images dans les limites de `requirements`.

### 9.3 React : vérification, smoke local, recette

- `npm run verify` vert (typecheck, build, garde-fous `grep`).
- **Smoke Playwright local** (`npm run e2e`, A12) contre le backend dev avec `SMS_BACKEND=locmem` ; le code est lu par `GET /handy/dev/sms-outbox/?phone=…`, route montée **uniquement** si `DJANGO_ENV=dev` et `SMS_BACKEND=locmem` (`tratra/urls_dev.py`), dont l'absence en production est testée. Trois parcours : inscription et OTP (L4) ; candidature, services, KYC maison et soumission (L7b) ; décision admin à quatre yeux (L7c).
- **Recette manuelle** (captures d'écran jointes à la description du commit de lot) :
  1. Inscription par téléphone, OTP, arrivée sur `/client` ; numéro d'un compte legacy → revendication.
  2. Nouvel onglet : session conservée (cookie).
  3. Déconnexion, connexion par téléphone, connexion legacy par username en casse différente.
  4. Mot de passe oublié de bout en bout, ancienne session expirée dans l'autre onglet.
  5. Profil, photo, préférence SMS, email (lien), changement de numéro, compte de versement (OTP).
  6. « Proposer un service » en visiteur, formulaire complet avec services, inscription en ligne, KYC (caméra, liveness), statut « en revue ».
  7. Reviewer (autre compte, MFA) : file, preuves (filigrane, indicateur « vu »), demande de resoumission, resoumission ; approbation à quatre yeux (C2 activé en dev), apparition dans `/search` et sur `/artisans/{user_id}`, présence en ligne.
  8. Suspension : disparition immédiate de `/search` et 404 sur `/artisans/{user_id}` ; réservation existante visible des deux côtés avec le bandeau.
  9. Bascule d'espace ; un Handyman réserve chez un autre artisan.
  10. Console sans erreur CSP ; caméra autorisée seulement sur `/worker/verification`.
  11. Rendu à 375 px pour l'OTP, la candidature et la capture KYC.

---

## 10. Trains de release et lots

### 10.0 Trains de release (go/no-go)

Les lots sont commités dans l'ordre sur la branche **`feat/compte-unique-kyc`**, créée à partir de `sprint1-critical-fixes` **après** le commit du lot public, avec **un commit par sous-lot** (convention de message du dépôt). Les lots sont regroupés en trains ; un train n'est déployé en production qu'après un go/no-go écrit, consigné au journal (§0.4), qui cite les décisions client dont il dépend.

| Train | Lots | Condition de go en production | Effet visible |
|---|---|---|---|
| **R1** | L1a, L1b, L1c, L2 | Recette backend ; prérequis du §6.8 ; C3 (gel) et C12 consignés | Failles fermées ; plus aucune nouvelle approbation ; anti-bruteforce opérant ; staff restreint |
| **R2** | L3a, L3b, L4 | SMS de production (C5) et textes légaux (C6) **pour activer** l'inscription par téléphone ; MFA du staff enrôlée ; sinon déploiement avec les drapeaux éteints | Compte unique par téléphone, OTP, revendication, profil, nouvelle interface web |
| **R3** | L0 (prérequis), L5a, L5b, L6, L7a, L7b, L7c, L7d, et L10 s'il est prêt | **Un chemin d'approbation existe** : L10 en production (C1, C6) **ou** C2 accepté par écrit. Plus C3, `KYC_LEGAL_APPROVAL_REF`, reviewers enrôlés, ancrage WORM | KYC, publication par prédicat, « Proposer un service », administration KYC, profils publics référencés. **Sans go, R3 reste en préproduction** (sinon le catalogue se viderait). |
| **R4a** | L8, L9a | Après R2 ; C9 (accord de l'utilisateur) | App mobile : compte unique |
| **R4b** | L9b | Après R3 | App mobile : candidature et KYC |
| **R5** | L10 (s'il n'était pas dans R3) | C1 et C6 | Vérification par le prestataire, badge « Identité vérifiée » |
| **R6** | L11 | Adoption mesurée des nouvelles apps | Retrait des chemins legacy |

**Critères « terminé » communs à tout lot** :
- `DJANGO_ENV=dev venv/bin/pytest` **entièrement** vert ;
- `python manage.py makemigrations --check --dry-run` sans changement en attente ;
- `npm run verify` vert si le front est touché ; `flutter analyze` et `flutter test` verts si l'app est touchée ;
- `ci.yml` (job « Production settings check ») et `.env.example` mis à jour pour toute nouvelle variable, les drapeaux restant désactivés par défaut ;
- aucun parcours existant cassé : endpoints legacy couverts par les tests ;
- recette du lot faite.

Estimations pour un développeur assisté, tests compris.

### L0 : cadrage Smile ID en sandbox [S, 1 jour] (train R3, avant L6)

- **Préalable** : clés sandbox (C1). Sans clés, L0 est bloqué : L6 et L7b avancent en mode manuel avec des `requirements` provisoires, revalidés en L10.
- **Contenu** (scripts jetables hors dépôt, rapport commité) :
  - envoi en sandbox v3 de **vraies** captures web (prototype `getUserMedia`) et Flutter (prototype `camera`) : selfie, 6 à 8 images, recto, verso ; noms de champs, acceptation des images hors SDK, tailles et résolutions minimales, latence ;
  - identification de l'appel **authentifié** qui renvoie le résultat complet (verdicts par contrôle, `id_fields`, antifraude, signaux appareil, `user_id`, `partner_params`, liens d'images) ;
  - SDK web hébergé v12 avec un jeton v3 émis par un script serveur : format du jeton, liaison `user_id`, `job_id`, `partner_params`, CSP nécessaire, rappel ;
  - webhook : en-têtes, rejeu d'une signature valide avec un corps modifié ;
  - **tests d'injection** : images synthétiques, vidéo rejouée, photo d'écran, appel direct à l'API sans client ; demande écrite au prestataire sur la détection d'injection hors SDK.
- **Livrable** : `docs/kyc/l0-smile-sandbox.md` (résultats, valeurs de `requirements`, valeurs de `SMILE_ID_AUTHENTICATED_FULL_RESULT` et `KYC_WEB_CAPTURE`) et entrée au journal.
- **Terminé** : rapport relu ; valeurs reportées dans les réglages par défaut de L6.

### L1a : failles de l'API (backend) [M, 1,5 jour] (R1)

- **Migration** : 0029.
- **Fichiers** : `handy/api/serializers.py`, `handy/api/views.py` (accroches), `handy/media/sanitize.py`, `handy/models.py` (`on_delete`), `handy/conftest.py` (création), `handy/test_l1_security_fixes.py`, `handy/test_lot1_public.py`, `test_security_sprint1.py`, `test_phase1.py`.
- **Contenu** :
  - `HandymanProfileSerializer` : `user`, `is_approved`, `rating`, `completed_jobs`, `quality_score`, `online`, `cni_number`, `license_number` en lecture seule ; `HandymanProfileViewSet` : propriétaire seulement, tiers en 404, création et suppression en 405 ;
  - `ServiceViewSet.perform_create` et `perform_update` (`handyman = request.user`, profil requis), `?handyman` à égalité stricte, `image_url` restreinte ; `ServiceImageViewSet` du propriétaire, `service` en lecture seule après création ; réencodage sans EXIF des images de service, bannières et médias d'avis ;
  - `UserSerializer` : `validate_password` à la création, `password` refusé en mise à jour, `user_type` en lecture seule hors création, `phone` ignoré à l'inscription legacy, conflits d'email et de username sous `signup_unavailable` ; `DELETE /users/{id}/` en 405 ;
  - `PublicUserMiniSerializer` réduit à `{id, first_name, display_name}` ;
  - cohérence de `BookingCreateSerializer` (service, artisan, soi-même) en format codé ;
  - gestionnaire d'erreurs codé `handy/api/errors.py` (base de D13).
- **Terminé** : critères communs ; cas de `test_l1_security_fixes.py` verts ; seul changement de contrat visible : clés retirées de `handyman_detail` (non lues par les clients).

### L1b : staff, administration, RBAC opérationnel [M, 1,5 jour] (R1)

- **Migration** : 0030.
- **Fichiers** : `handy/admin.py`, `handy/api/views.py` (permissions), `handy/identity/{events,context}.py`, `handy/middleware.py` (`RequestContextMiddleware`), signaux de privilèges, `handy/models.py` (`AccountEvent`, `Meta.permissions`, `@cleanup.ignore` sur `HandymanDocument`), commandes `identity_report` (partie staff), `grant_role`, `create_fake_data` (durcie), `entrypoint.sh`, `handy/test_l1b_staff_rbac.py`, `handy/test_db_roles.py`.
- **Contenu** : suppression d'`approve_profiles` et `is_approved` en lecture seule partout (gel des approbations, C3) ; formulaires admin (§1.7, règle 6) sans aucun lien vers un fichier ; `HasStaffPerm` et `view_all_records` à la place d'`is_staff` ; `resolve_dispute`, `manage_payouts`, `self_dealing_forbidden` ; staff sans écriture sur les autres comptes par l'API ; documents legacy réservés aux superusers et journalisés ; `AccountEvent` append-only et événements de privilèges ; garde de `create_fake_data` et de `CREATE_SUPERUSER`.
- **Terminé** : critères communs ; la page React `/admin` (comptes) fonctionne pour un compte du groupe `Opérations`, et la page legacy `/admin/kyc` pour un superuser (jusqu'à son remplacement en L7c) ; aucun chemin ne fait passer `is_approved` à vrai.

### L1c : réservations et séquestre [S, 1 jour] (R1)

- **Migration** : 0031.
- **Fichiers** : `handy/models.py` (`Booking.transition_to` avec table des acteurs, `Payment.release_after`), `handy/api/views.py` (`confirm-completion`), `handy/tasks.py` (`release_matured_escrows`), `CELERY_BEAT_SCHEDULE`, `handy/test_l1c_booking_actors.py`.
- **Contenu** : l'artisan confirme, démarre et déclare la fin ; le client confirme la fin ou annule ; fin déclarée par l'artisan : statut `completed`, libération à `release_after` (48 h, `ESCROW_AUTO_RELEASE_HOURS`) sauf litige ouvert ; confirmation du client : libération immédiate (C12, A6).
- **Terminé** : critères communs ; `test_sprint4.py` inchangé et vert.

### L2 : socle de sécurité transverse [M, 2 jours] (R1)

- **Migration** : aucune dans `handy`.
- **Fichiers** : `tratra/settings/{base,dev,prod}.py` (cache, proxies, axes, Sentry, journaux, SMS, CORS, `ADMIN_URL`, contrôles de démarrage), `handy/identity/{client_ip,guards,devices,backends,phones,logging}.py`, `handy/identity/sms/*`, `handy/middleware.py` (IP, `no-store`), `handy/storage.py` (`url()` interdit, pas de repli), throttles (`TratraThrottleMixin`), `requirements.txt` (`phonenumbers` 9.0.x épinglé), `docker-compose.yml` (IP fixe de Traefik, suppression de `minio-console`, `RUN_MIGRATIONS=0`, service `migrate`, file Celery `otp`), `deploy/sql/{roles,grants}.sql`, `.env.example`, `.github/workflows/ci.yml` (`makemigrations --check`, variables du job de production), `handy/test_infra_security.py`.
- **Contenu** : §5.3, §5.4, §5.7, §5.9 (stockage et infra MinIO), §5.10 ; `PhoneEmailUsernameBackend` (téléphone comparé sous sa forme brute et sous sa forme normalisée tant que la normalisation n'est pas faite) ; garde par compte dans le backend ; jetons d'appareil ; 429 `too_many_attempts` sur le login existant.
- **Terminé** : critères communs ; connexion legacy inchangée (casse comprise) ; démarrage en production refusé seulement pour une fonctionnalité activée mal configurée.

### L3a : identité, OTP, inscription, revendication, jetons, réinitialisation [L, 3 jours] (R2)

- **Migrations** : 0032, 0033, 0034.
- **Fichiers** : `handy/models.py` (`User`, `OTPCode`, `OtpSendLog`, `SignupClaim`), `handy/identity/{otp,otp_quota,antibot,tokens,authentication,sessions,capabilities,accounts,claims,legal}.py`, `handy/api/{auth_serializers,auth_views,auth_urls}.py`, `handy/api/urls.py` (routes avant le router ; `jwt-login`, `jwt-refresh`, `jwt-logout` vers les nouvelles vues), `views.py` (`otp_request`, `otp_verify` redirigés), commandes `normalize_user_phones`, `purge_otp_challenges`, `identity_report` (partie identité), `CELERY_BEAT_SCHEDULE`, `docs/api-contracts/` (Me, auth, erreurs), tests du §9.1 (L3a), `test_journeys.py` (parcours 1 à 4).
- **Endpoints** : §4.1, §4.2 (hors MFA), §4.3, legacy OTP du §4.5.
- **Terminé** : critères communs ; anti-énumération vérifiée ; concurrence OTP vérifiée ; normalisation à blanc puis appliquée sur la base dev ; React et Flutter actuels fonctionnent toujours (login legacy, `/users/me/` compatible).

### L3b : compte, profil, email, téléphone, versements, MFA, configuration [L, 2,5 jours] (R2)

- **Migration** : aucune dans `handy` (tables `django-otp`).
- **Fichiers** : `handy/api/{me_serializers,me_views,public_views}.py`, `handy/identity/mfa.py`, `views.py` (`UserViewSet` : `me` en GET et PATCH, `deactivate`, photo, `payout_account` en deux étapes), `handy/legal/` (fichiers fournis par le client ; dossier vide et drapeaux éteints sinon), `handy/tasks.py` (`_send_sms` et préférence), commande `staff_mfa_enroll`, `OTPAdminSite`, tests du §9.1 (L3b).
- **Endpoints** : §4.4, §4.5, §4.6, §4.2 (MFA), §4.13 (configuration et textes légaux), et **`POST /handy/users/me/handyman/`** (création d'un profil vide, idempotente : 201 ou 200), qui permet de « Devenir artisan » jusqu'à L6.
- **Terminé** : critères communs ; fixture `Me` pré-L5 ; un compte staff sans `amr` reçoit 403 `mfa_required` quand `STAFF_MFA_REQUIRED` est vrai.

### L4 : React, compte unique et interface de compte [L, 3,5 jours] (R2)

- **Commits** : L4a (socle §7.1, connexion, inscription, revendication, mot de passe oublié, layouts, sélecteur d'espace, composants du lot public), L4b (pages de compte §7.2, notifications, versements, textes légaux, page de défi, smoke Playwright n° 1).
- **Terminé** : critères communs ; recette §9.3 étapes 1 à 5, 9 (partie client), 10 et 11 ; un compte legacy `employeur` accède à `/client` ; un staff (MFA) accède à `/admin` ; « Devenir artisan » mène à `/worker` avec un profil créé ; `RoleGuard`, `HOME_BY_ROLE` et `AREA_ROLES` supprimés ; garde-fou `user_type` actif.

### L5a : cœur KYC, publication, reprise legacy [L, 3 jours] (R3)

- **Migrations** : 0035, 0036, 0037.
- **Fichiers** : `handy/models.py` (§1.5, §1.8), `handy/kyc/{states,service,approval,publication,audit,reasons,duplicates,legacy_mapping,crypto,tasks}.py`, `providers/{base,manual}.py`, accroches (`views.py`, `matching.py`, `models.py` : remplacements, frais d'annulation, `ReplacementSuggestion.accept`, `tasks.py`), signaux de publication, tâche de revalidation, `handy/api/public_views.py` (§4.13 : profil public et liste), admin en lecture seule, commandes `kyc_legacy_report`, `kyc_legacy_request_resubmission`, `kyc_reconcile_publication`, `db_validate_constraints`, `create_fake_data` (option `--dev-approve`), tests du §9.1 (L5a).
- **Contenu** : machine d'états, champs réservés, prédicat publiable et ses 12 conditions, filtrage du §3.3 partout, réservation §3.4, effets de retrait (§2.4), `public_location`, audit chaîné, chiffrement des preuves, reprise legacy. Dans les payloads publics, `is_verified` vaut provisoirement `identity_verified` (retiré en L7d).
- **Terminé** : critères communs ; aucune approbation automatique ; retrait immédiat vérifié sur tous les points du §3.3 ; `kyc_legacy_report` conforme aux données dev.

### L5b : API admin KYC, RBAC KYC, accès aux preuves [L, 2,5 jours] (R3)

- **Migration** : 0038.
- **Fichiers** : `handy/api/{kyc_admin_views,kyc_urls}.py`, `handy/kyc/permissions.py`, quatre yeux et cas d'approbation (`approval.py`), bris de glace, throttles, commande `kyc_verify_audit_chain`, tâches `kyc_expire_pending_approvals` et `kyc_anchor_audit_heads`, `HandymanDocumentViewSet` (règles du §5.9), fixtures admin et `PublicHandyman`, tests du §9.1 (L5b).
- **Terminé** : critères communs ; les quatre cas d'approbation testés ; périmètre des preuves et MFA appliqués.

### L6 : candidature, services, capture KYC maison, justificatifs, ré-authentification (API) [L, 3 jours] (R3)

- **Migration** : 0039.
- **Fichiers** : `handy/kyc/{evidence,consent}.py`, `handy/api/{kyc_serializers,kyc_views}.py` (§4.7, §4.8, §4.9), `HandymanProfileViewSet` (`PATCH` avec le serializer de candidature), `ServiceSerializer` (`category_not_in_trades`), en-tête `Deprecation` sur les écritures `/handyman-docs/`, types de `Notification`, tâche `kyc_mark_purged_objects`, fixtures `Application`, `KycOverview` et `HandymanProof`, `copy.fr.json`, tests du §9.1 (L6), `test_journeys.py` (parcours 5 à 9).
- **Terminé** : critères communs ; conversion client → Handyman, rejet, resoumission, approbation (cas D, C2 activé en test, quatre yeux), publication, suspension et permissions couverts de bout en bout par l'API ; valeurs de `requirements` issues de L0.

### L7a : React, « Proposer un service », candidature, services [M, 2,5 jours] (R3)

- **Fichiers** : §7.3 (L7a) ; `components/handyman/*` ; bascule du CTA global ; suppression de `/worker/kyc`.
- **Terminé** : critères communs ; recette §9.3 étape 6 (jusqu'à la redirection vers la vérification) ; cas « profil existant » vérifié.

### L7b : React, KYC web [M, 2 jours] (R3)

- **Fichiers** : §7.3 (L7b) ; `components/kyc/*` ; CSP à nonce et caméra sur `/worker/verification` ; paquet `qrcode` ; smoke Playwright n° 2.
- **Terminé** : critères communs ; recette étape 6 complète ; aucune URL de stockage dans l'onglet réseau ; consentement avant toute capture.

### L7c : React, administration KYC [M, 2,5 jours] (R3)

- **Fichiers** : §7.3 (L7c) ; `components/admin/kyc/*` ; CSP à nonce et Trusted Types sur `/admin` ; smoke Playwright n° 3.
- **Terminé** : critères communs ; recette étapes 7 et 8 ; preuves affichées uniquement en `blob:` ; indicateur « vu » requis avant la décision.

### L7d : React, profil public, référencement, badges, bandeaux [M, 1,5 jour] (R3)

- **Fichiers** : §7.3 (L7d) ; côté backend, retrait de `is_verified` et `is_approved` des payloads publics et test de contrat associé (même commit).
- **Terminé** : critères communs ; sitemap dynamique ; 404 réels ; filtre « Vérifiés » retiré ; garde-fou `is_verified` actif.

### L8 : Flutter, prérequis [M, 2 jours] (R4a)

- **Préalable bloquant** : accord explicite de l'utilisateur pour le commit baseline (C9).
- **Fichiers** : §8.1 et ses tests.
- **Terminé** : `flutter analyze` et `flutter test` verts ; fuite de jeton et refresh concurrent couverts ; upload de photo de profil (`PUT /users/me/photo/`) accepté avec le bon content-type.

### L9a : Flutter, compte unique [L, 3 jours] (R4a)

- **Fichiers** : §8.2 ; contrats et tests de widgets (§9.2).
- **Terminé** : critères communs ; recette sur simulateur iOS et émulateur Android : catalogue sans compte, inscription par OTP, revendication, connexion, mot de passe oublié, profil et photo, changement de numéro, compte de versement, mise à jour forcée ; comptes legacy connectés par identifiant.

### L9b : Flutter, Handyman et KYC [L, 3,5 jours] (R4b)

- **Fichiers** : §8.3 ; contrats et tests de widgets (§9.2).
- **Terminé** : critères communs ; recette : Proposer un service, services, KYC maison (caméra, compression, nettoyage), statut, présence, profil public avec badge exact.

### L10 : intégration Smile ID [L, 3 jours] (R3 ou R5)

- **Préalables** : L0, C1, C6.
- **Fichiers** : `handy/kyc/providers/smile_id.py` ; tâches `kyc_submit_to_provider`, `kyc_fetch_provider_result`, `kyc_poll_pending` ; vue de webhook (§4.10) ; `provider-session` (§4.8) ; copie des preuves SDK ; SmartSelfie pour la ré-authentification ; garde-fous de démarrage ; commande `kyc_reverify_manual` ; côté React, `SmileWebCapture` (si L0 l'a validé) ; `test_kyc_provider_smile.py`, `test_journeys.py::test_kyc_prestataire`.
- **Terminé** : critères communs ; parcours sandbox de bout en bout contrôlé (cas A sur le SDK web, cas B sur une capture mobile) ; corps de webhook forgé sans effet ; aucune donnée sensible en base ni dans les journaux.

### L11 : clôture [S, 1,5 jour] (R6)

- **Migrations** : 0040, 0041.
- **Contenu** : `LEGACY_SIGNUP_ENABLED=false` (410 lisible) ; `LEGACY_KYC_DOCS_WRITE_ENABLED=false` (410) ; fin de la grâce de réservation et du 400 au login pour les clients sans en-tête ; retrait de `user_type` de `Me` ; contraintes E.164 et index email insensible à la casse ; schéma OpenAPI complet (`extend_schema`) ; runbook mis à jour avec les résultats réels ; revue de sécurité du diff global ; recette croisée React et Flutter sur la même instance.
- **Terminé** : critères communs ; build web ; CI mobile ; checklist de production (annexe A) validée.

**Total estimé** : 42 à 48 jours-développeur. **Chemin critique externe** : contrat Smile ID, clés sandbox (L0) et avis ARTCI (C6) pour R3 en mode prestataire ; textes légaux et sender ID Orange pour l'inscription par téléphone (R2) ; accord sur le dépôt Flutter (C9) ; publication sur les stores (R4a, R4b) avant R6.

---

## Annexe A : variables d'environnement (nouvelles)

Règle (D20) : en production, une fonctionnalité est **désactivée par défaut** ; le démarrage n'est refusé que si une fonctionnalité **activée** manque de configuration. Chaque variable est ajoutée à `.env.example` et au job « Production settings check » de `ci.yml` par le lot qui l'introduit.

| Variable | Lot | Défaut (dev / test) | Production |
|---|---|---|---|
| `CACHE_URL` | L2 | vide (LocMem) | dérivée de `REDIS_URL` (base 1) si vide ; un cache Redis est obligatoire |
| `TRUSTED_PROXY_COUNT`, `TRUSTED_PROXY_IPS` | L2 | `0`, vide | `1`, IP fixe de Traefik |
| `ADMIN_URL`, `ADMIN_ALLOWED_CIDRS` | L2 | `admin/`, vide | chemin non devinable obligatoire ; allowlist recommandée |
| `SENTRY_SEND_PII` | L2 | `false` | doit rester `false` |
| `SMS_BACKEND`, `SMS_ROUTES`, `SMS_FAILOVER` | L2 | `console` (`locmem` en test), `{"CI":"orange_ci","*":"twilio"}`, `false` | vide (OTP en 503) ou `router`, `orange_ci`, `twilio` complets |
| `ORANGE_SMS_CLIENT_ID`, `ORANGE_SMS_CLIENT_SECRET`, `ORANGE_SMS_SENDER_MSISDN`, `ORANGE_SMS_SENDER_NAME` | L2 | vide | requis si Orange est routé |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_MESSAGING_SERVICE_SID` ou `TWILIO_FROM` | L2 | vide | requis si Twilio est routé |
| `ESCROW_AUTO_RELEASE_HOURS` | L1c | 48 | C12 |
| `OTP_PEPPER` | L3a | valeur de test | obligatoire (32 octets, distinct de `SECRET_KEY`) dès qu'un SMS réel est configuré |
| `OTP_TTL_SECONDS`, `OTP_CHALLENGE_TTL_SECONDS`, `OTP_MAX_ATTEMPTS`, `OTP_MAX_SENDS_PER_CHALLENGE`, `OTP_RESEND_BASE_COOLDOWN` | L3a | 300, 1800, 5, 3, 60 | idem |
| `OTP_PHONE_HOURLY_LIMIT`, `OTP_PHONE_DAILY_LIMIT`, `OTP_PREFIX_SOFT_HOURLY`, `OTP_PREFIX_HARD_HOURLY`, `OTP_IP_SOFT_HOURLY`, `OTP_IP_HARD_HOURLY`, `OTP_IP_HARD_DAILY` | L3a | 5, 10, 30, 100, 20, 300, 1000 | idem |
| `OTP_ALLOWED_COUNTRIES`, `OTP_COUNTRY_DAILY_BUDGET`, `OTP_EXISTING_ACCOUNT_RESERVE_PCT`, `OTP_CONVERSION_ALERT_RATIO` | L3a | liste C5, `{"CI":5000,"*":300}`, 20, 0.3 | C5 |
| `OTP_SEND_ASYNC` | L3a | `false` (dev.py, tests) | `true` obligatoire |
| `WEBOTP_DOMAIN` | L3a | `localhost` | domaine du front |
| `ANTIBOT_PROVIDER`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | L3a | vide | `turnstile` et clés (C11) |
| `PHONE_SIGNUP_ENABLED` | L3a | `true` | `false` ; `true` seulement avec SMS réel, textes légaux et normalisation faite |
| `LEGACY_SIGNUP_ENABLED` | L3a | `true` | `false` en R6 |
| `RESET_ALLOW_UNVERIFIED_LEGACY` | L3a | `true` | `true` (jamais pour un compte à valeur ni staff) |
| `PAYOUT_HOLD_HOURS` | L3b | 72 | 72 |
| `JWT_SIGNING_KEY`, `JWT_AUDIENCE`, `JWT_ISSUER` | L3a | valeur de test, `tratra-api`, `tratra` | obligatoires (clé de 32 octets au moins) |
| `JWT_ACCESS_MINUTES`, `JWT_ACCESS_MINUTES_WEB`, `JWT_REFRESH_DAYS`, `JWT_REFRESH_HOURS_STAFF`, `REFRESH_REUSE_GRACE_SECONDS` | L3a | 30, 10, 7, 12, 30 | idem |
| `AUTH_WEB_REFRESH_COOKIE`, `AUTH_REFRESH_COOKIE_NAME`, `AUTH_REFRESH_COOKIE_SECURE`, `AUTH_REFRESH_COOKIE_SAMESITE` | L3a | `true`, `tratra_rt`, `false`, `Strict` | `true`, `tratra_rt`, **`true`**, `Strict` |
| `STAFF_MFA_REQUIRED` | L3b | `false` | `true` (après enrôlement, R2) |
| `EMAIL_VERIFICATION_ENABLED` | L3b | `true` (backend email locmem en test) | `true` si SMTP configuré, sinon email en lecture seule |
| `TERMS_VERSION`, `PRIVACY_VERSION`, `KYC_CONSENT_VERSION` | L3a, L6 | versions des fichiers de test | versions des fichiers fournis (C6) |
| `SUPPORT_PHONE`, `SUPPORT_EMAIL`, `SUPPORT_WHATSAPP` | L3b | vide | valeurs réelles ou vide |
| `MIN_APP_VERSION_ANDROID`, `MIN_APP_VERSION_IOS` | L3b | vide | relevées par le runbook |
| `BOOKING_REQUIRES_PHONE_VERIFIED`, `BOOKING_PHONE_GRACE_LEGACY_CLIENTS` | L3b | `false`, `true` | `false` jusqu'au runbook (C4) ; grâce retirée en R6 |
| `PUBLIC_LOCATION_GRID_DEG` | L5a | 0.01 | 0.01 |
| `IDENTITY_HMAC_KEYS`, `IDENTITY_HMAC_CURRENT_VERSION` | L5a | trousseau de test, 1 | obligatoires si `KYC_SUBMISSIONS_ENABLED` |
| `KYC_ENCRYPTION_KEYS`, `KYC_ENCRYPTION_CURRENT_VERSION` | L5a | trousseau de test, 1 | obligatoires si `KYC_SUBMISSIONS_ENABLED` |
| `KYC_AUDIT_ANCHOR_BUCKET` | L5b | vide (ancrage désactivé) | obligatoire pour le go de R3 |
| `KYC_PROVIDER` | L5a | vide (manuel) | `smile_id` après C1 et C6 |
| `KYC_SUBMISSIONS_ENABLED` | L5a | `true` | `false` jusqu'au go de R3 |
| `KYC_LEGAL_APPROVAL_REF` | L6 | `test` | obligatoire pour accepter selfie et liveness (C6) |
| `KYC_AUTO_APPROVE_ON_CLEAR` | L5a | `false` | `true` seulement si `SMILE_ID_AUTHENTICATED_FULL_RESULT` (sinon forcé à `false`) |
| `KYC_MANUAL_APPROVAL_ALLOWED` | L5a | `true` en dev, posé par test | `false` sauf C2 écrit |
| `KYC_MAX_ATTEMPTS`, `KYC_ALLOWED_ID_TYPES`, `KYC_PROVIDER_TIMEOUT_HOURS` | L5a | 3, `IDENTITY_CARD`, 48 | C7 |
| `KYC_MAX_REPLACEMENTS_PER_KIND`, `KYC_PROFILE_BYTES_QUOTA`, `KYC_DRAFT_RETENTION_DAYS`, `KYC_EVIDENCE_RETENTION_YEARS` | L6 | 10, 200 Mo, 30, 3 | C6 |
| `KYC_WEB_CAPTURE` | L6 | `inhouse` | `sdk` après L0 et L10 |
| `KYC_TASKS_ASYNC` | L5a | `false` (dev.py, tests) | `true` |
| `SMILE_ID_ENV`, `SMILE_ID_PARTNER_ID`, `SMILE_ID_API_KEY`, `SMILE_ID_CALLBACK_URL`, `SMILE_ID_WEBHOOK_MAX_SKEW`, `SMILE_ID_AUTHENTICATED_FULL_RESULT` | L10 | `sandbox`, vide, vide, vide, 300, `false` | `production` obligatoire si `KYC_PROVIDER=smile_id` ; capacité selon L0 |
| `LEGACY_KYC_DOCS_WRITE_ENABLED` | L6 | `true` | `false` en R6 |
| `MEDIA_PUBLIC_HOSTS` | L1a | hôte des médias de dev | hôtes du stockage public |
| `FRONTEND_REVALIDATE_URL`, `FRONTEND_REVALIDATE_SECRET`, `INTERNAL_RENDER_SECRET` | L5a, L7d | vide (pas d'appel) | recommandés |
| Front : `NEXT_PUBLIC_AUTH_MODE`, `REVALIDATE_SECRET`, `INTERNAL_RENDER_SECRET`, `NEXT_PUBLIC_ANDROID_URL`, `NEXT_PUBLIC_IOS_URL` | L4, L7 | `cookie`, valeur de dev, valeur de dev, vide, vide | idem ; liens d'apps seulement s'ils existent |

## Annexe B : codes de motif

| Code | Usage | Message utilisateur par défaut | Resoumission par défaut |
|---|---|---|---|
| `document_unreadable` | rejet ou resoumission | Les photos de votre pièce sont floues ou illisibles. Reprenez-les dans un endroit bien éclairé. | oui (sans consommer de tentative) |
| `document_incomplete` | rejet ou resoumission | Le recto et le verso de votre CNI sont nécessaires. | oui |
| `document_expired` | rejet ou révocation | Votre pièce d'identité est expirée. Soumettez une pièce en cours de validité. | oui |
| `document_not_accepted` | rejet | Ce type de pièce n'est pas accepté. Utilisez votre CNI ivoirienne. | oui |
| `document_mismatch_name` | rejet | Le nom de la pièce ne correspond pas à celui de votre compte. | oui |
| `selfie_unusable` | rejet ou resoumission | Votre selfie n'est pas exploitable. Recommencez face à la caméra. | oui |
| `face_mismatch` | rejet | Votre visage ne correspond pas à la photo de la pièce. | oui |
| `liveness_failed` | rejet | La vérification de présence a échoué. Recommencez en suivant les consignes. | oui (non après deux échecs) |
| `reauth_failed` | rejet d'une ré-authentification | La nouvelle photo ne permet pas de confirmer votre identité. Recommencez. | oui |
| `legacy_reverification` | resoumission | Pour rester visible sur Tratra, merci de compléter la nouvelle vérification d'identité. | oui |
| `duplicate_identity` | rejet ou révocation | Cette pièce est déjà associée à un autre compte. Contactez le support. | non |
| `suspected_fraud` | rejet, suspension ou révocation | Votre dossier ne peut pas être validé. Contactez le support. | non |
| `underage` | rejet | Vous devez être majeur pour proposer des services. | non |
| `complaints` | suspension | Votre profil est suspendu suite à des signalements. | — |
| `fraud_investigation` | suspension | Votre profil est suspendu le temps d'une vérification. | — |
| `terms_violation` | suspension ou révocation | Votre profil est suspendu pour non-respect des conditions d'utilisation. | — |
| `quality_issues` | suspension | Votre profil est suspendu suite à des problèmes de qualité. | — |
| `user_request` | suspension | Profil suspendu à votre demande. | — |
| `other` | tous | (message obligatoire) | au choix |

Codes de fraude (resoumission interdite, gel des fonds à la révocation) : `duplicate_identity`, `suspected_fraud`, `fraud_investigation`. Les mentions « Contactez le support » ne sont affichées qu'avec un contact réel (`/public/config/`), sinon reformulées (« Répondez au message reçu dans l'application »).

## Annexe C : nouveaux types de `Notification`

`kyc_submitted`, `kyc_approved`, `kyc_rejected`, `kyc_resubmission_requested`, `kyc_suspended`, `kyc_reinstated`, `kyc_revoked`, `kyc_document_expiring`, `kyc_reauth_required`, `kyc_supervisor_alert` (doublon frauduleux, bris de glace, accès massif), `handyman_published`, `handyman_unpublished`, `booking_handyman_unavailable`, `account_phone_released`, `security_password_changed`, `security_phone_changed`, `security_payout_changed`. Ajoutés aux `choices` (état seul) ; le type legacy `booking_response`, présent en base mais hors des choix, y est ajouté.

## Annexe D : catalogue des codes d'erreur (format codé, tous endpoints)

- **Validation et compte** : `validation_error`, `terms_not_accepted`, `terms_version_mismatch`, `invalid_credentials`, `too_many_attempts`, `throttled`, `account_inactive`, `phone_verification_required`, `signup_unavailable`, `challenge_required`, `challenge_failed`.
- **OTP et SMS** : `otp_invalid`, `otp_expired`, `otp_locked`, `otp_cooldown`, `otp_send_limit`, `challenge_expired`, `sms_unavailable`, `sms_budget_exceeded`, `signup_conflict`.
- **Revendication** : `legacy_account_found`, `claim_invalid`, `support_required`.
- **Jetons, CSRF, MFA** : `session_revoked`, `token_not_valid`, `csrf_failed`, `mfa_required`, `mfa_invalid`, `mfa_not_enrolled`.
- **Profil, téléphone, email, mot de passe** : `invalid_current_password`, `password_too_similar`, `same_phone`, `no_phone`, `already_verified`, `phone_change_requires_otp`, `password_change_endpoint`, `names_locked_by_kyc`, `email_change_unavailable`, `email_link_invalid`, `email_unavailable`.
- **Versements** : `step_up_required`, `step_up_mismatch`, `payouts_on_hold`.
- **Candidature, services, publication** : `no_handyman_profile`, `handyman_profile_required`, `handyman_profile_exists`, `profile_suspended`, `not_publishable`, `trade_required`, `too_many_trades`, `specialty_without_trade`, `too_many_specialties`, `unknown_commune`, `invalid_slot`, `overlapping_slots`, `rate_required`, `bio_too_short`, `category_not_in_trades`, `invalid_image_url`.
- **KYC candidat** : `kyc_unavailable`, `consent_required`, `consent_version_mismatch`, `consent_not_accepted`, `kyc_incomplete`, `application_incomplete`, `kyc_not_editable`, `resubmission_not_allowed`, `attempts_exhausted`, `invalid_file`, `frames_count`, `too_many_replacements`, `storage_quota_exceeded`, `too_many_proofs`.
- **Admin et staff** : `invalid_transition`, `permission_denied`, `self_review_forbidden`, `self_dealing_forbidden`, `manual_approval_disabled`, `submission_claimed_by_other`, `checklist_incomplete`, `reason_required`, `document_expired`, `provider_not_configured`, `evidence_not_reviewed`, `evidence_scope`, `duplicate_identity`, `second_approver_required`, `approval_case_not_met`.
- **Réservation et paiement** : `service_unavailable`, `handyman_unavailable`, `handyman_mismatch`, `self_booking_forbidden`.
- **Webhook et legacy** : `bad_signature`, `stale`, `endpoint_deprecated`.

## Annexe E : risques résiduels et backlog

| # | Risque ou sujet | Mitigation |
|---|---|---|
| E1 | Le prestataire refuse ou note mal les captures maison | L0 avant toute capture ; captures maison toujours en revue humaine ; SDK web nominal ; montée Flutter (C14) en option. |
| E2 | R3 bloqué tant qu'aucun chemin d'approbation n'existe (contrat, ARTCI) | Barrière explicite (§10.0) ; option C2 (sans badge, quatre yeux) ; communication aux artisans ; gel des approbations annoncé dès R1. |
| E3 | Reprise d'un compte legacy par le titulaire d'un numéro recyclé | Récupération limitée aux comptes sans valeur ; revendication par mot de passe legacy ; retenue de 72 h ; ré-authentification des artisans. |
| E4 | CGNAT : faux positifs sur les seuils IP | Seuils IP souples (défi) et plafonds durs larges ; suivi des 428 et 429 dans Sentry. |
| E5 | Anciennes apps : `email` nul, payout en 403 explicite, profil artisan en 404 au lieu d'un mauvais profil | Mise à jour forcée par `min_app_version` ; messages explicites. |
| E6 | Cookie web exigeant le même site pour le front et l'API | Documenté ; repli `NEXT_PUBLIC_AUTH_MODE=bearer`. |
| E7 | Coût et pumping de SMS | Budgets par usage, réserve, préfixes, défi, coupure par pays, taux de conversion surveillé. |
| E8 | Reconnexion forcée de tous les utilisateurs au passage à `JWT_SIGNING_KEY` (R2) | Annonce ; une seule fois. |
| E9 | Infra supplémentaire (rôles PostgreSQL, IP fixe de Traefik, MinIO durci, bucket WORM) | Prérequis listés par train (§6.8) ; scripts fournis. |
| Backlog | Suppression des colonnes `user_type` et `is_verified` ; purge de `cni_number`, `license_number`, `insurance_info` ; réduction de `UserMiniSerializer` ; WebSocket authentifié ; détection de malware ; purge RGPD outillée ; attestation d'application mobile ; SDK Flutter (C14). | — |
