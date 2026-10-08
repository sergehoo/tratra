# Design System Tratra

Référence visuelle officielle : **la landing** (`src/app/page.tsx`). Le Design System en
extrait la langue visuelle — vert de marque dominant, accents **jaune** et **noir**,
surfaces blanches, titres Montserrat, texte Poppins, formes arrondies (pilules et cartes
à 24 px), ombres douces, animations discrètes — et la rend réutilisable sur le web (React)
et sur mobile (Flutter).

## Source unique : `tokens.json`

Toute valeur visuelle vit dans [`tokens.json`](./tokens.json). Rien de « de marque » n'est écrit en dur ailleurs.

```sh
npm run ds:build   # régénère src/styles/tokens.css et lib/design/tokens.dart (app Flutter)
npm run ds:check   # échoue si un fichier généré est périmé (CI)
```

| Sortie | Fichier | Consommateur |
| --- | --- | --- |
| Variables CSS `--tt-*` | `src/styles/tokens.css` | `globals.css`, styles ad hoc |
| Thème Tailwind | `tailwind.config.ts` (lit `tokens.json`) | toutes les classes utilitaires |
| Classes Dart | `<flutter>/lib/design/tokens.dart` | `TratraTheme` + widgets `Tratra*` |

Le dossier Flutter se règle avec `TRATRA_FLUTTER_DIR` (défaut : `../handy_tratra/flutter_tratra`
à côté du dépôt). S'il est absent, seule la sortie CSS est produite.

## Jetons

| Famille | Jetons (web = Tailwind · Flutter) |
| --- | --- |
| Marque | `primary #2e8b57`, `primaryDark #1f6a41`, `primaryDeep #185736`, `primarySoft #e8f6ee` · `accent #F6C90E`, `accentBright`, `accentDark`, `accentSoft #FFF8D6` · `night #0b1210`, `nightSoft #15201b` — `TtColors.primary` … |
| Neutres | `ink`, `inkSoft`, `ash`, `fog`, `line`, `lineSoft`, `canvas`, `surface` |
| Sémantiques | `success`, `warning`, `danger`, `info`, chacun avec `…Soft` (fond) et `…Ink` (texte AA sur fond soft) |
| Typographie | Montserrat 600/700/800 (titres) · Poppins 400–700 (texte) ; échelle `displayXl`, `displayLg`, `h1`–`h3`, `title`, `bodyLg`, `body`, `bodySm`, `caption`, `eyebrow`, `button` (`text-h1`, `TtType.h1`) |
| Espacement | base 4 px (`1,2,3,4,5,6,8,10,12,16,20,28`) — échelle Tailwind native · `TtSpace.s4` |
| Rayons | `control` 12 (champs) · `panel` 16 (lignes denses) · `card` 24 (cartes) · `sheet` 28 (feuilles basses) · `pill` (boutons, badges) — `rounded-control`… · `TtRadius.control` |
| Ombres | `hair`, `soft`, `strong`, `glow` (vert), `glowAccent` (jaune) — `shadow-soft`… · `TtShadows.soft` |
| Mouvement | durées `fast 150 / base 220 / slow 420 / hero 900` ms ; courbe `emphasized (.22,1,.36,1)` — `duration-base ease-emphasized` · `TtMotion` |
| Mise en page | conteneur 1280, gouttières 16/24, cible tactile 44, champ 48, barre latérale 256, barre haute 64, barre basse 64 |

### Règles de couleur (accessibilité)

- Texte blanc **uniquement sur `primaryDark`/`primaryDeep`/`night`** (≥ 4,5:1). Le vert `primary` sert aux grands titres, icônes et surfaces décoratives.
- Texte courant : `ink` ; secondaire : `inkSoft` ; tertiaire : `ash` (≥ 4,5:1 sur blanc) ; `fog` est réservé aux placeholders et icônes décoratives.
- Le jaune se pose sur `night` (bouton `accent`) ou sert de fond clair (`accentSoft`) avec du texte `ink`.
- Jamais d'information portée par la seule couleur : un statut a toujours un libellé (`StatusBadge`).

## Composants web — `@/components/ds`

| Composant | Rôle | Remarques |
| --- | --- | --- |
| `Button`, `ButtonLink`, `buttonClass` | Actions | variantes `primary accent night soft outline ghost danger outlineLight outlineNight`, tailles `sm md lg`, `loading`, `block` |
| `TextField`, `TextareaField`, `SelectField`, `Field`, `Input`, `Textarea`, `Select`, `PasswordInput`, `Checkbox` | Formulaires | `Field` relie étiquette, aide et erreur (`aria-describedby`, `aria-invalid`) |
| `Card`, `CardHeader`, `Stat` | Surfaces | variantes `default flat soft accent night`, `interactive` |
| `Badge`, `StatusBadge` | Étiquettes | `StatusBadge` + `@/lib/status` : libellés français des statuts réservation / document / litige / abonnement |
| `Alert` | Messages | `info success warning danger brand` ; `danger`/`warning` annoncés (`role="alert"`) |
| `Modal`, `ConfirmDialog` | Dialogues | portail, focus piégé et restitué, Échap, feuille basse en mobile |
| `AppShell` (+ `NavItem`) | Navigation des espaces connectés | barre latérale ≥ `lg`, barre haute + navigation basse mobile, menu du compte |
| `PageHeader`, `BackLink` | En-tête de page | porte l'unique `<h1>` |
| `Tabs` | Onglets / filtres | ARIA tablist + clavier |
| `DataTable` | Tableaux | table dès `md`, cartes empilées en mobile, états chargement/vide |
| `Skeleton*` | Chargement | `SkeletonList`, `SkeletonStats`, `SkeletonTable`, `SkeletonPage` |
| `EmptyState` | États vides | décrit la situation réelle, propose une action réelle |
| `Avatar` | Identité | photo réelle sinon initiales sur dégradé de marque |
| `Container`, `Eyebrow`, `SectionHeading` | Marketing | utilisés par la landing via `landing/kit.tsx` |
| `motion.ts` | Animations | `EASE`, `DURATION`, variantes `fadeUp`, `scaleIn`, `sheetUp` ; classes `animate-rise/fadeIn/scaleIn/sheetUp/pulseDot` |

Le rendu vivant (tous les états) est sur **`/design-system`** — disponible en développement
seulement (404 en production, `noindex`).

## Correspondance Flutter

| Web | Flutter (`lib/design/`) |
| --- | --- |
| `Button` | `TratraButton` (variantes identiques, `loading`, `block`) |
| `Card` | `TratraCard` |
| `Input`/`TextField` | `TratraInput` |
| `Badge`/`StatusBadge` | `TratraBadge` |
| `AppShell` topbar | `TratraAppBar` |
| barre basse mobile | `TratraBottomNav` |
| `EmptyState` | `TratraEmptyState` |
| `Skeleton*` | `TratraSkeleton` |
| thème Tailwind | `TratraTheme.light()` (Material 3 adapté à la marque) |

## Règles d'usage

1. **Aucune valeur de marque en dur** : couleurs, rayons, ombres viennent des jetons.
2. **Aucune donnée fictive, aucun bouton mort** : un état vide reflète la réalité, tout CTA mène à une route réelle.
3. **Mobile d'abord** : cible tactile ≥ 44 px, gouttière 16 px, navigation basse en mobile, tableaux en cartes.
4. **Animations discrètes** : ≤ 420 ms (900 ms réservé au hero), `prefers-reduced-motion` respecté (règle globale + `MotionConfig`).
5. **Un seul `<h1>` par page**, fourni par `PageHeader` ; focus visible partout.
