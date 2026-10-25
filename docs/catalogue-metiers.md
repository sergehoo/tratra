# Catalogue des métiers — une seule source

Django / PostgreSQL (`ServiceCategory`) est la **source unique** : le site, l'application mobile et l'administration affichent les mêmes métiers,
les mêmes noms, les mêmes icônes et la même arborescence. Aucune liste de métiers n'est écrite dans le code web ou mobile.

| Niveau | Dans la base | Exemple |
|---|---|---|
| **Famille** | `CatalogFamily` (navigation, sans offre) | Informatique & Numérique, Auto, moto & vélo |
| **Métier** (= sous-catégorie) | catégorie racine (`parent` vide), rangée dans une famille (`family`, facultative) | Jardinage, Cuisine, Nounou |
| **Prestation** | sous-catégorie (`parent` renseigné) | Entretien de fleurs (sous Jardinage) |
| **Offre** | `Service` publié par un professionnel éligible, rattaché à une catégorie | « Taille de rosiers » |

Règles : un métier **actif** reste visible même **sans offre** (seule sa désactivation le retire) ; une catégorie désactivée disparaît avec ses
prestations ; choisir un métier dans une recherche couvre ses prestations actives.

## Endpoint public commun

`GET /handy/catalog/` — sans authentification, sans donnée personnelle, `ETag` + `Cache-Control: public, max-age=60, stale-while-revalidate=300`
(`If-None-Match` → `304`). Réponse à plat, déjà dans l'ordre d'affichage (métier, puis ses prestations), compatible avec la pagination DRF :

```json
{"count": 8, "next": null, "previous": null, "version": "9f2c…", "generated_at": "…", "results": [
  {"id": 7, "name": "Jardinage", "slug": "jardinage", "parent": null, "trade": 7, "kind": "trade", "depth": 0,
   "icon": "fa-solid fa-tree", "icon_key": "tree", "position": 10, "order": 0, "is_featured": true, "is_active": true,
   "offers_count": 0, "offers_total": 2, "prestations_count": 2, "description": "", "services_count": 2}]}
```

- `offers_count` : offres publiées directement dans la catégorie ; `offers_total` : avec ses prestations (`services_count` = alias historique) ;
- « publiée » = service actif d'un artisan éligible (même règle que la recherche publique) ;
- `icon_key` : icône normalisée (voir plus bas) ; `order` : rang commun à tous les clients ;
- limite de débit : `THROTTLE_CATALOG` (240/min par défaut).

`GET /handy/categories/` (liste historique) reste disponible et expose les mêmes champs utiles (`icon_key`, `kind`, `position`, `is_featured`) ;
**écriture réservée au personnel** (auparavant ouverte à tout compte connecté). Les filtres `categories=`, `category=`, `category__name=` des
services, de `services/nearby/` (`category_id`) et des artisans mis en avant couvrent désormais les prestations d'un métier.

## Administration

- **Django Admin** (`Service Categories`) : niveau (Métier / Prestation), métier parent, **ordre** (`position`, le plus petit d'abord), **mise en avant**
  (`is_featured`), **visibilité** (`is_active`) — modifiables directement dans la liste ; actions « Mettre en avant », « Retirer », « Rendre visible », « Masquer » ;
  filtres Niveau et Métier ; icône vérifiée à la saisie ; anti-cycle (une catégorie ne peut pas devenir sa propre prestation). Pour retirer un métier sans rien perdre,
  le **masquer** (visibilité) : la suppression (écran de confirmation Django) supprime aussi ses prestations et leurs offres.
- **Back-Office** (`Services › Catégories`) : mêmes réglages (ordre, mise en avant, icône) avec audit.
- Les identifiants ne changent jamais ; rien n'est recréé. La migration `0050` ajoute deux colonnes (`position` = 100, `is_featured` = faux) et reprend
  **une seule fois** la sélection historique de la page d'accueil : les catégories **racines actives** existantes dont le slug figurait dans l'ancienne liste
  codée en dur sont marquées « mises en avant » et ordonnées. Sans aucun métier mis en avant, la landing montre les 10 premiers du catalogue.

## Icônes

L'administration saisit un nom Font Awesome (`fa-solid fa-utensils`). Le serveur le normalise (`utensils` ; anciens noms FA5 convertis : `fas fa-home` → `house`)
et sert `icon_key`. Sans icône saisie, une valeur par défaut dépend du slug (table côté serveur uniquement). Le vocabulaire commun est `ICON_KEYS` dans
`handy/catalog.py` ; **web** (Lucide : `ICON_BY_KEY`, `frontend/src/lib/trades.ts`) et **application** (Font Awesome : `categoryIconByKey`,
`lib/screens/home/home_icons.dart`) doivent dessiner chaque clé. Pour ajouter une icône : l'ajouter aux trois endroits ; les tests de contrat
(`npm run test:bo`, `flutter test test/catalog_test.dart`) échouent s'il en manque une. Une clé inconnue donne l'icône par défaut ; l'administration signale
une icône non reconnue.

## Web

- Landing : `TradesSection` affiche les **métiers mis en avant** avec leurs prestations et le nombre d'offres ; « Voir tous les métiers » ouvre `/metiers`
  (catalogue complet, avec ou sans offre) ; la recherche (`/search`) et le pied de page lisent la même réponse.
- `frontend/src/lib/trades.ts` ne contient plus de liste de métiers : il transforme la réponse du catalogue.

## Application mobile (Flutter)

- `CatalogRepository` (`lib/services/catalog_repository.dart`) : une réponse partagée par tous les écrans, cache mémoire + disque **frais 5 minutes**, puis
  revalidation par `ETag` (304 = rien à retélécharger), un seul appel réseau simultané, dernière version connue conservée en cas de panne.
- Accueil : métiers mis en avant ; « Tous les métiers » : catalogue complet avec recherche (métier, prestation), tri, prestations à l'ouverture d'un métier ;
  les filtres de services utilisent le même arbre.

## Recette (Jardinage, Cuisine, Nounou)

1. Django Admin : le métier existe, actif ; ses prestations lui sont rattachées (`parent`).
2. `GET /handy/catalog/` : trois entrées `kind: "trade"`, leurs prestations en dessous, même `icon_key`, `offers_total` cohérent ; **Nounou** présent même à 0 offre.
3. tratra.net : section « Métiers » (si mis en avant) et `/metiers` (toujours) ; l'application : « Tous les métiers ».
4. Changer l'ordre, la visibilité ou la mise en avant dans l'administration : visible sur le web sous ~1 minute, dans l'application à l'expiration du cache (5 minutes)
   ou à l'actualisation par tirage.

## Familles, synonymes et « J'ai une panne » (25 oct. 2026)

**Structure** : famille → métier (sous-catégorie) → prestation. La famille est un regroupement de navigation administrable (`Familles de métiers`
dans l'admin Django : nom, slug, icône, ordre, visibilité, synonymes) ; elle ne change ni l'identifiant ni la place d'un métier. Un métier sans famille
(ou d'une famille masquée) s'affiche dans « Autres métiers ». Les prestations prennent la famille de leur métier.

**Référentiel Côte d'Ivoire** (`handy/catalog_seed.py`, version `ci-2026-10`) : 11 familles — Informatique & Numérique (12 métiers : maintenance,
réseaux/Wi-Fi, développement web/mobile, cybersécurité, vidéosurveillance, téléphonie, bureautique, cloud/serveurs, design numérique, marketing
digital, formation, domotique) et 10 familles pour les 18 catégories de réparation et services de proximité (téléphones/électronique, électroménager
et froid, auto/moto/vélo, électricité et plomberie, bâtiment, menuiserie/métallerie/serrurerie, nettoyage/jardin, couture/cordonnerie/tapisserie,
transport/déménagement, équipements professionnels) — 33 métiers et environ 210 prestations avec leurs synonymes populaires (« frigo », « clim »,
« écran cassé », « vulcanisateur », « compteur CIE », « SODECI »…).

**Application idempotente** — migration `handy.0064` puis, si besoin, `python manage.py sync_catalog [--dry-run]` :
- un métier qui existe déjà (même slug, slug historique — ex. `reparation-smartphone`, `ferronnerie`, `reparation-electromenager` — ou même nom sans
  accents ni casse) est **réutilisé tel quel** : nom, ordre, mise en avant, visibilité et icône conservés ; seules sa famille (si vide), son icône
  (si vide), les prestations manquantes et les synonymes manquants sont ajoutés ;
- une prestation existe déjà si son métier en a une au même nom (sans accents ni casse) : aucun doublon ;
- rien n'est supprimé, renommé ni déplacé ; profils (spécialités), offres et réservations ne sont pas touchés ; ré-appliquer ne change rien.
- Répétition sur base jetable (ancien catalogue de 13 catégories) : 239 catégories après migration, 11 familles, Plomberie conservée (ordre 10, mise en
  avant, icône), aucune prestation en double ; `sync_catalog` ensuite : 0 création ; retour à `handy 0062` puis ré-application OK.

**Synonymes** (`keywords`, séparés par des virgules, éditables dans l'admin) : servis dans `GET /handy/catalog/` (`keywords` par entrée,
`family` par entrée, liste `families`), utilisés par la recherche des services (`search=` couvre aussi les synonymes et le nom du métier d'une
prestation), par la recherche du catalogue (web `/metiers`, application « Tous les métiers », autocomplétion des offres).

**Filtres** : `family=<id ou slug>` (services et `services/nearby/`), en plus de `categories=`, `commune=`, `lat`/`lng`/`radius_km`. Un artisan peut avoir
plusieurs spécialités (`HandymanProfile.skills`) et publier des offres dans plusieurs métiers et familles.

**« J'ai une panne »** : `GET /handy/catalog/match/?q=<description>` (public, sans jeton, limité par `THROTTLE_CATALOG`, `Cache-Control: no-store`) renvoie
les prestations et métiers pertinents, classés (score déterministe : couverture des mots utiles du client par le nom et les synonymes, bonus pour une
expression entière, contexte du métier). Le texte n'est ni enregistré ni journalisé. Web : page `/panne` (description, commune facultative,
prestations proposées, lien vers les artisans ou « Trouvez-moi un professionnel ») ; application : écran « J'ai une panne » (accueil, recherche,
« Tous les métiers »), puis liste des offres filtrée par prestation et commune.

**Icônes ajoutées** au vocabulaire commun : `phone`, `cloud`, `server`, `bullhorn`, `tablet-screen-button`, `radio`, `satellite-dish`, `network-wired`,
`microchip`, `code`, `house-signal`, `shoe-prints`, `industry`, `truck-pickup`, `car-battery`, `bug` (Lucide sur le web, Font Awesome dans l'application ;
tests de contrat des deux côtés).

**Tests en base** : les migrations de données remplissent le catalogue ; le `conftest.py` racine remet la base de test à un catalogue vide après les
migrations (les tests créent leurs catégories) ; `handy/test_catalog_reference.py` applique le référentiel explicitement.

