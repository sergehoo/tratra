# Tratra — scalabilité vers 30 millions de comptes

Objet : capacité réelle de l'architecture actuelle, goulots d'étranglement, plan par palier, tests de charge reproductibles.
Règles suivies : aucun test sur la production, aucun SMS ni push réel, aucun chiffre de capacité inventé. Les hypothèses sont nommées
(H1…H9) et isolées des mesures. Mesures du 24 octobre 2026.

## 1. Architecture mesurée (production, d'après `docker-compose.yml`)

Un seul serveur porte toute la pile :

| Composant | Configuration réelle | Conséquence |
|---|---|---|
| HTTP **et** WebSocket | **1 processus Daphne** (ASGI) | Toute l'API tient sur un cœur (verrou global de Python). |
| PostgreSQL 16 + PostGIS | Image par défaut, sans réglage, sans pooler, sans réplica | `CONN_MAX_AGE=0` : une connexion par requête. Daphne en ouvre une par requête en cours, sans plafond. |
| Redis 7 | **1 instance, sans persistance** | Porte à la fois le broker Celery, le cache, les quotas anti-fraude, Channels et les résultats Celery. |
| Celery | 1 worker (files `default,notifications`) et 1 beat | Avant correctif : une seule file pour tous les push. |
| MinIO | 1 nœud, volume local | Médias publics et pièces KYC. |
| Traefik | Limite de débit 150 req/s en moyenne (rafale 250) | Sans `sourceCriterion` : la limite s'applique **par adresse du pair**. Derrière Cloudflare, c'est l'adresse du nœud Cloudflare, pas celle du visiteur (à vérifier). |
| Géocodage | Nominatim public, `GEO_MAX_CALLS_PER_MINUTE=30` | 30 recherches d'adresse par minute pour **tous** les utilisateurs réunis (hors cache). |

## 2. Capacités mesurées et inconnues

**Banc de mesure** (les valeurs sont **relatives**, ce ne sont pas des capacités de production) :

- Apple M3, 8 cœurs, 8 Go.
- PostgreSQL 16 en version x86 sous Rosetta, ce qui est pessimiste pour la base.
- Générateur de charge sur la même machine.
- Données synthétiques (`loadtest_seed`) :
  - 200 000 comptes, dont 20 000 professionnels ;
  - 50 728 offres, 180 000 réservations ;
  - 1 000 000 de notifications, 300 000 messages ;
  - 80 000 propositions Flash ;
  - 70 % des comptes à Abidjan, popularité des métiers selon une loi de Zipf.

### 2.1 Coût par écran (dans le processus, médiane de 5 appels)

| Écran | 20 000 comptes | 200 000 comptes, avant | 200 000 comptes, après correctifs |
|---|---|---|---|
| Catalogue | 1 ms | 1 ms (1 requête) | 1 ms |
| Notifications, non-lus, conversations, messages | 3–6 ms | 3–7 ms (3–7 requêtes) | identique |
| Services proches 10 km (anonyme) | 40 ms | **187 ms** | 236 ms (voir E1) |
| Liste des services d'un métier | 56 ms | **236 ms** | 235 ms (voir C4) |
| Tableau de bord professionnel | 46 ms (89 requêtes) | 44 ms (102 requêtes) | identique |
| Passeport Trust | 29 ms (42 requêtes) | 25 ms (55 requêtes) | identique |
| **Flash : choisir son pro** | 380 ms (657 requêtes) | **4 831 ms (6 841 requêtes)** | **771 ms (19 requêtes)** |
| **Flash : mode conseillé** | 442 ms (661 requêtes) | **4 654 ms (6 845 requêtes)** | **813 ms (23 requêtes)** |

### 2.2 Une vague de Smart Dispatch (`candidates`)

| Métier / lieu (200 000 comptes) | Professionnels du métier | Retenus | Avant | Après |
|---|---|---|---|---|
| Plomberie, position à Abidjan | 5 425 | 1 674 | **14 391 ms, 16 435 requêtes** | **1 112 ms, 11 requêtes** |
| Plomberie, commune seule | 5 425 | 184 | 1 911 ms, 1 784 requêtes | 197 ms, 11 requêtes |
| Serrurerie, position à Abidjan | 652 | 212 | 1 691 ms, 2 063 requêtes | 196 ms, 11 requêtes |
| Livraison, position à Abidjan | 381 | 102 | 492 ms, 1 047 requêtes | 142 ms, 11 requêtes |

Avant correctif :

- le coût croissait avec le nombre de professionnels du métier **dans tout le pays**, à raison d'environ 10 requêtes par professionnel ;
- ce calcul tournait dans une transaction qui verrouille la demande, **à l'intérieur de la requête HTTP** de création.

À 200 000 comptes, cela approchait déjà le délai de 20 s de l'application mobile.

### 2.3 Débit HTTP du serveur d'application (même machine, même base)

| Scénario | Daphne, 1 processus (comme en prod) | gunicorn, 4 processus |
|---|---|---|
| Catalogue, 16 utilisateurs simultanés | 211 req/s, p95 160 ms | **1 289 req/s**, p95 18 ms |
| Notifications authentifiées, 16 utilisateurs | 146 req/s, p95 173 ms | **713 req/s**, p95 37 ms |
| Mélange réaliste (recherche, Flash…), 8 à 64 utilisateurs | ~20 req/s, p95 jusqu'à 6,8 s | ~20 req/s : la **base** sature, pas le serveur |

### 2.4 Autres mesures

- **WebSocket** :
  - un processus Daphne tient **5 000 connexions** ouvertes, sans échec (ouverture : p95 1,6 s) ;
  - environ **58 Ko de mémoire par connexion** ;
  - environ **1,9 Ko dans Redis** par connexion (Channels).
- **Connexion par mot de passe** : PBKDF2 à 600 000 itérations, soit **153 ms de CPU** par vérification (≈ 6,5 connexions/s par cœur).
- **Annonce** (diffusion en base, sans réseau) :
  - avant : 449 comptes/s, 4 requêtes par compte ;
  - après : **2 125 comptes/s**, 0,01 requête par compte.
- **URL signée MinIO** : 0,29 ms de CPU par URL, calcul local.
- **Stockage**, données et index compris : notifications 771 o/ligne, réservations 929, comptes 506, appareils 577, propositions Flash 645, messages 220.
  À 200 000 comptes, les notifications pèsent déjà **757 Mo** : c'est la première table, et elle n'a aucune purge.

### 2.5 Inconnues (à mesurer, jamais à supposer)

- **Serveur de production** : CPU, mémoire, disque (IOPS), réglages PostgreSQL effectifs, latence réseau Côte d'Ivoire ↔ serveur.
- **Trafic réel** : mélange des écrans, pic horaire, part des comptes actifs, connexions WebSocket simultanées.
- **Géographie réelle** : densité de professionnels par commune, part des professionnels sans position GPS.
- **CGNAT des opérateurs mobiles** : nombre d'utilisateurs derrière une même adresse IP. Cela touche les limites par IP (inscriptions, SMS, débit anonyme 60/min).
- **Firebase** : latence et quota du projet FCM ; débit et limites du fournisseur SMS.
- **Infrastructure** : coût de Traefik et Cloudflare, comportement de la limite Traefik derrière Cloudflare.
- **Sauvegardes** : temps de sauvegarde et de restauration à volume réel.

## 3. Goulots d'étranglement par criticité

| # | Criticité | Goulot | Preuve | État |
|---|---|---|---|---|
| C1 | Critique | Smart Dispatch : tous les professionnels du métier du pays examinés, environ 10 requêtes chacun, dans la requête HTTP et sous verrou | § 2.2 : 14,4 s et 16 435 requêtes | **Corrigé** : préfiltre par index spatial, lectures groupées, 11 requêtes constantes |
| C2 | Critique | « Choisir son pro » et « mode conseillé » : cartes construites une à une (avis et offres) pour **tous** les candidats | § 2.1 : 4,8 s et 6 841 requêtes | **Corrigé** : 19–23 requêtes constantes |
| C3 | Critique | Un seul processus Daphne pour toute l'API ; impossible de garder les connexions SQL sous ASGI | § 2.3 : six fois moins de débit que 4 processus gunicorn | **À faire** (configuration, § 5) |
| C4 | Critique | Éligibilité recalculée à chaque recherche publique : sous-requête nationale (profils, KYC, spécialités, expérience), comptée deux fois par page | Comptage de 88 ms à 200 000 comptes ; liste par métier 56 → 236 ms quand le volume est multiplié par 10 | **À faire** : drapeau d'éligibilité dénormalisé et indexé |
| C5 | Critique | Une seule file Celery : une annonce de masse retarde les alertes de mission (90 s pour répondre) | Code (aucune route) | **Corrigé** : file `bulk` pour les annonces |
| C6 | Critique | Diffusion d'une annonce compte par compte | 449 comptes/s, soit ≈ 19 h pour 30 M sur ce banc | **Corrigé** pour la base (2 125 comptes/s) ; envoi FCM restant : un appel par appareil (M4) |
| E1 | Élevé | Recherche de proximité : distance calculée pour **chaque** offre, rayon illimité, total exact compté | § 2.1 : 40 → 187 ms ; plan SQL en parcours séquentiel | **Partiel** : rayon plafonné à 50 km et préfiltre indexé. Le gain n'apparaît pas sur ce banc : 70 % des comptes y sont à moins de 10 km du centre d'Abidjan. Il dépend de la géographie réelle (inconnue). Restent le tri et le comptage exact, chers dans une zone dense |
| E2 | Élevé | Redis unique sans persistance, pour tous les usages | Compose | **À faire** : Redis séparés, AOF pour le broker |
| E3 | Élevé | PostgreSQL non réglé, sans pooler ni réplica, sauvegarde par `pg_dump` | Compose, `scripts/staging/backup.sh` | **À faire** : PgBouncer, réglages, réplica, sauvegarde continue (PITR) |
| E4 | Élevé | Un seul serveur : point unique de panne pour toute la pile | Compose | **À faire** par palier (§ 4) |
| E5 | Élevé | Quotas statiques : SMS 150/jour et 30/h, inscriptions 60/h, 5/h et 20/jour par IP, débit anonyme 60/min par IP | Réglages ; CGNAT inconnu | **À ajuster par palier** (variables d'environnement existantes) |
| E6 | Élevé | Limite Traefik par adresse du pair, probablement celle du nœud Cloudflare | Compose (aucun `sourceCriterion`) | **À vérifier**, puis `sourceCriterion` sur `CF-Connecting-IP` |
| E7 | Élevé | Géocodage : Nominatim public, 30 appels/min au total | Réglages | **À faire** dès 100 000 comptes : instance dédiée ou fournisseur sous contrat |
| M1 | Moyen | Notifications sans purge ; plus grosse table | 771 o/ligne, 757 Mo à 200 000 comptes | **À faire** : rétention (ex. 180 jours), partition mensuelle à 10 M |
| M2 | Moyen | Tableau de bord pro (102 requêtes), passeport Trust (55) | § 2.1 | À regrouper, ou cache court |
| M3 | Moyen | Connexion : 153 ms de CPU par mot de passe | § 2.4 | Prévoir des cœurs pour les reconnexions massives ; garder PBKDF2 |
| M4 | Moyen | Push FCM : un POST HTTPS par appareil, sans connexion réutilisée | Code (`requests.post`) | **À faire** : session keep-alive (tests à adapter), concurrence du worker `bulk` |
| M5 | Moyen | WebSocket : 58 Ko par connexion ; abonnement Redis renouvelé toutes les 120 s | § 2.4 | Prévoir des nœuds WebSocket dédiés |
| M6 | Moyen | Suggestions Business : les 200 premiers profils éligibles, pas les plus proches | Code (`business/services.py`) | Trier par distance avant de limiter |
| F1 | Faible | Catalogue, notifications, messages, non-lus : index utilisés, coût constant | § 2.1 et plans SQL | Aucun |

## 4. Plan progressif

Hypothèses de trafic (à remplacer par les mesures réelles dès qu'elles existent) :

- **H1** : 10 % des comptes actifs chaque jour ;
- **H2** : 30 appels d'API par actif et par jour ;
- **H3** : 12 % du trafic quotidien dans l'heure de pointe ;
- **H4** : rafales à 2 fois la moyenne de cette heure.

Pic ≈ comptes × 0,10 × 30 × 0,12 / 3 600 × 2 = **comptes × 0,0002 req/s**.

| Palier | Pic (H1–H4) | Prérequis | Architecture cible |
|---|---|---|---|
| **100 000** | 20 req/s | C1, C2, C5, C6 (faits) ; C3 ; E5 (relever les quotas : 300 inscriptions/jour dépasseraient déjà les 150 SMS/jour) ; E6 ; E7 ; sauvegarde restaurée une fois | Serveur unique ; gunicorn pour HTTP ; Daphne seulement pour `/ws/` ; worker `bulk` séparé |
| **1 M** | 200 req/s | C4 ; E1 (comptage plafonné, tri par plus proche voisin) ; E2 ; E3 (PgBouncer, réglages) ; M1 ; M4 | Base sur sa propre machine, avec réplica en lecture ; Redis séparés (broker persistant, cache, Channels) ; 2 serveurs d'application derrière Traefik ; stockage objet répliqué |
| **10 M** | 2 000 req/s | Réplica pour les lectures publiques ; partitions des notifications et messages ; Smart Dispatch limité aux K plus proches (**décision produit** : le classement actuel examine toute la zone) ; envoi FCM concurrent | Pool web horizontal (sans état) ; nœuds WebSocket dédiés ; sauvegarde continue (PITR) ; supervision des files Celery |
| **30 M** | 6 000 req/s | Recherche par commune ou par tuiles, en cache ; découpage des domaines Flash / messagerie / notifications si la base primaire sature (mesure à l'appui) | Plusieurs zones de disponibilité ; base primaire et réplicas ; Redis en cluster ; quotas FCM et SMS négociés |

### 4.1 Ressources estimées (hypothèses explicites × coûts mesurés)

- **Serveurs web** :
  - coût mesuré d'un écran léger : ≈ 180 req/s par processus gunicorn sur le banc M3 ;
  - il faut donc environ **pic ÷ 180 × 1,5 de marge**, soit :

    | Palier | Processus web |
    |---|---|
    | 100 000 | 1 |
    | 1 M | 2 |
    | 10 M | 17 |
    | 30 M | 50 |

  - condition : seulement **après C4 et E1**, car tant que la recherche reste à 150–235 ms de SQL, c'est la base qui limite ;
  - à re-mesurer sur le CPU cible.
- **Stockage PostgreSQL** :
  - H5, par compte conservé : 20 notifications, 2 réservations, 30 messages, 0,8 appareil, 0,5 avis ;
  - avec les octets par ligne mesurés, cela donne ≈ **25 Ko par compte** ;
  - les notifications en représentent 62 % : la rétention est le premier levier ;
  - avant marge, WAL et autres tables :

    | Palier | Stockage |
    |---|---|
    | 100 000 | 2,5 Go |
    | 1 M | 25 Go |
    | 10 M | 250 Go |
    | 30 M | 750 Go |
- **WebSocket** :
  - H6 : 2 % des comptes connectés au pic ;
  - à 58 Ko par connexion et ≤ 5 000 connexions par processus :

    | Palier | Connexions | Mémoire | Redis | Renouvellements Redis |
    |---|---|---|---|---|
    | 1 M | 20 000 | 1,2 Go | — | — |
    | 10 M | 200 000 | 11,6 Go | 0,4 Go | 1 700/s |
    | 30 M | 600 000 | 35 Go, environ 120 processus | 1,1 Go | 5 000/s |
- **Connexions par mot de passe** :
  - H7 : 5 % des comptes se connectent chaque jour, dans les mêmes conditions de pic ;
  - à 30 M, cela fait environ 100 connexions/s, soit **≈ 15 cœurs** occupés par le seul hachage (153 ms mesurées).
- **Annonce nationale** :
  - la partie base est mesurée à 2 125 comptes/s par worker sur le banc, soit ≈ 4 h pour 30 M sur un seul worker ;
  - la partie FCM dépend de la latence et du quota du projet (**inconnus**). À mesurer avant 1 M.
- **SMS** : ce n'est pas une limite technique mais un budget et des quotas (E5). Les quotas doivent suivre H8 (inscriptions par jour), à mesurer dans `SignupLog`.

## 5. Correctifs : livrés et prioritaires

**Livrés dans ce lot** (tests ajoutés, comportement inchangé) :

1. **Smart Dispatch et « choisir son pro »** :
   - zone préfiltrée par l'index spatial, qui reste un sur-ensemble exact des règles (position, puis zone d'intervention, puis commune) ;
   - disponibilités et historiques lus en lot ;
   - écartés hors zone toujours expliqués ;
   - code : `flash/services.py`, `flash/hybrid.py`, `handy/reviews.py`, `handy/proximity.py` ;
   - tests : `flash/test_dispatch_scale.py`.
2. **Recherche de proximité** :
   - préfiltre ST_DWithin indexé ;
   - rayon plafonné à 50 km (le site propose 50 km au plus, l'application 25) ;
   - la même chose pour `match` et les alternatives ;
   - tests : `handy/test_proximity.py`.
3. **Annonces** :
   - audience parcourue par lots, sans jamais tout charger en mémoire ;
   - livraisons et notifications insérées en groupe, sous verrou (un compte n'est jamais servi deux fois) ;
   - arrêt entre deux lots si l'annonce est annulée ;
   - tests : `announcements/test_delivery_scale.py`.
4. **Files Celery** :
   - push d'annonces sur la file `bulk`, les autres sur `notifications` ;
   - les deux fichiers compose écoutent `bulk` ;
   - `celery_check` et ses tests le vérifient.

   Au déploiement, le worker doit être **recréé**, car sa commande change (`docker compose up -d worker`). Sinon, les push d'annonces attendraient dans `bulk`.
5. **Banc de charge reproductible** (§ 6).

**Prioritaires, à faire dans l'ordre** :

1. **C3** :
   - servir l'HTTP par `gunicorn tratra.wsgi`, avec un nombre de processus proche du nombre de cœurs disponibles (à ajuster par la mesure sur la cible) et `CONN_MAX_AGE` > 0 ;
   - réserver Daphne aux routes `PathPrefix(/ws/)` dans Traefik ;
   - point à vérifier : le flux SSE de l'assistant fonctionne déjà sous WSGI (générateur synchrone).
2. **E5 et E6** :
   - relever les quotas SMS et d'inscription avant 100 000 comptes, à partir de la distribution réelle des IP dans `SignupLog` ;
   - limite Traefik par visiteur réel.
3. **C4** :
   - colonne `HandymanProfile.publishable` indexée, recalculée par `handy/eligibility.py` à chaque changement (KYC, profil, compte, seuil d'expérience du métier) ;
   - réconciliation périodique ;
   - le contrôle Python à la réservation reste l'autorité.
4. **E1** :
   - pagination sans total exact pour `/services/nearby/` (total plafonné ou « page suivante ») ;
   - tri par plus proche voisin (`<->`) avec l'index GiST.
5. **E2, E3, M1** : Redis séparés et persistants pour le broker, PgBouncer, réglages PostgreSQL, rétention des notifications.
6. **M4** : session FCM réutilisée, worker `bulk` concurrent ; mesurer la latence et le quota FCM en recette, avec des appareils de test.

## 6. Tests de charge reproductibles (hors production)

Trois garde-fous indépendants :

- réglages `DJANGO_ENV=loadtest` ;
- base jetable dont le nom commence par `tratra_loadtest` ;
- refus au démarrage (`loadtest/guard.py`) si DEBUG est actif, si un fournisseur SMS ou un compte FCM est configuré, ou si la base n'est pas locale.

Les cibles `tratra.net`, `www`, `api` et `minioapi` sont refusées quoi qu'il arrive. Une recette doit être nommée explicitement avec `--allow-host`.

```bash
scripts/loadtest/run_local.sh seed 200000 20000      # base jetable : 200 000 comptes dont 20 000 professionnels (~13 min)
scripts/loadtest/run_local.sh measure                 # coût par écran, Smart Dispatch, annonces, stockage, hachage, plans SQL
SCENARIOS="mix catalog notifications" scripts/loadtest/run_local.sh http   # Daphne 1 processus puis gunicorn N processus
DURATION=60 scripts/loadtest/run_local.sh ws 5000     # connexions WebSocket tenues + mémoire
scripts/loadtest/run_local.sh stop-redis              # arrête le Redis dédié (port 6391)
```

Les résultats (JSON) sont écrits dans `loadtest-results/`, ignoré par Git.

En recette, la même chose est possible avec `scripts/loadtest/http_load.py --target https://staging… --allow-host staging…`. La recette doit tourner avec `SMS_ENABLED=false` et sans compte FCM.

Avant chaque palier, refaire `seed` au volume visé, puis `measure` et `http` : un écran dont le nombre de requêtes croît avec le volume est un goulot.
