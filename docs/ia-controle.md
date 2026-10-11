# Contrôle intelligent : KYC, fraude, recommandations

**Principe : l'IA et les règles proposent, l'administrateur décide.** Aucune suspension, exclusion, validation KYC, badge ou accusation de fraude n'est jamais déclenché automatiquement. Un OCR n'est pas une preuve d'authenticité.

## Fournisseurs d'IA (facultatifs)
- `AI_PROVIDERS=deepseek,anthropic` : DeepSeek en priorité (texte), Anthropic en repli (texte et images). Sans clé, tout fonctionne avec les règles déterministes.
- Les documents KYC **ne quittent jamais le serveur** tant que `AI_KYC_EXTERNAL_ENABLED=true` **et** `AI_KYC_LEGAL_BASIS` (base légale, garanties) ne sont pas renseignés. Chaque analyse conserve si un fournisseur externe a reçu le document.
- Les appels sont journalisés (`AIRun` : fournisseur, tâche, durée, code d'erreur) sans contenu ni clé.

## Analyse d'un document (Back-Office > KYC)
OCR local Tesseract (images ; paquets installés dans l'image Docker) puis, si autorisé, lecture par Anthropic. Contrôles explicables : fichier lisible, type déclaré/lu, expiration, nom du document vs compte, date de naissance entre documents, complétude, **fichier identique** et **numéro de document identique** sur un autre compte. Le texte intégral n'est pas conservé ; le numéro n'est jamais stocké (empreinte HMAC + 3 derniers caractères masqués).

## Dossiers de risque
Types : doublon potentiel, document incohérent, identité incomplète, KYC expiré, activité anormale, réservations artificielles possibles. Un doublon exige un identifiant fort (fichier, numéro de document, téléphone E.164) : un nom, une adresse ou un appareil partagé ne suffit jamais. Décisions humaines motivées (enquête, confirmer, écarter, rouvrir), historisées et journalisées ; confirmer n'a aucun effet automatique. Les évaluations suspectes ont leur propre surveillance (Avis > Surveillance).

## Recommandations de services (`POST /handy/recommendations/`)
Moteur **déterministe** (aucune IA externe) : pertinence (catégorie/besoin) 35, distance 20, réputation vérifiable 20 (moyenne retenue dès 3 avis), disponibilité réelle (horaires déclarés, absences) 10, historique 10, prix 5. Seuls les services actifs de profils **publiables** (KYC approuvé, profil complet) sont candidats ; chaque résultat liste ses raisons ; un critère sans donnée reste « inconnu » (score neutre, jamais inventé). Le transport estimé est calculé avec les tarifs et la distance routière réels pour les meilleurs résultats. Aucune coordonnée de prestataire n'est exposée ; l'adresse utilisée est celle du compte courant.
