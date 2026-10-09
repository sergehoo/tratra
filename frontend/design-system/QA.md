# QA visuelle du Design System — 9 octobre 2026

Périmètre : web (React/Next) et Flutter, sans changement de règle métier.

## Vérifications automatiques

| Contrôle | Résultat |
| --- | --- |
| `npm run ds:check` (tokens web/Flutter synchronisés) | OK |
| `npx tsc --noEmit` | 0 erreur ; compile aussi contre les versions `HEAD` de `lib/api.ts` et `lib/types.ts` |
| `next build` (23 pages) | OK |
| `flutter analyze` | 0 erreur, 0 warning (12 infos antérieures : noms locaux `_x` des modèles, `if` sans accolades et un `print` dans `api_service.dart`) |
| `flutter test` | 20 tests verts (contrats de modèles, shell, 18 tests des composants du DS) |

## Contrôles visuels

- **Web** (volet navigateur, comptes de test `qa_*` du dev local) : `/`, `/search`, `/login`, `/register`, 404, `/client`, `/client/services`, `/client/services/[id]`, `/worker`, `/worker/missions/[id]`, `/worker/kyc`, `/company`, `/company/plans`, `/admin`, `/admin/disputes`, `/admin/kyc` à 332 px de large : aucun débordement horizontal, un seul `<h1>` par page, navigation basse active. Tableau des litiges mesuré à 800 et 1100 px : sans défilement horizontal.
- **Flutter** (build Web du même code, ≈ 280 dp de large) : connexion, accueil client, liste des réservations, suivi, tunnel de réservation, missions artisan, compte, KYC.
- **Non fait** : test sur le Samsung SM-G975F (débranché en cours de session) et sur simulateur iOS (plateforme iOS 26.2 absente de Xcode). À rejouer sur appareil : `flutter run --dart-define=TRATRA_API_BASE=http://127.0.0.1:8000/handy` après `adb reverse tcp:8000 tcp:8000`.

## Défauts trouvés et corrigés pendant la QA

- Flutter : `TratraButton(block: true)` et `BookingContentWidth` s'étiraient sur toute la hauteur dans une barre basse (écran KYC, fiche service, réservation, paiement vides).
- Flutter : `setState` renvoyant un `Future` (assertion en debug), champ de recherche sans effet, détail d'exception brut affiché, étapes de suivi coupées au milieu d'un mot, chevauchement avatar/badge sur la carte artisan, contraste du texte « Pas encore noté ».
- Web : grilles sans colonne explicite qui débordaient en mobile (fiche service, missions…), tableau des litiges trop large entre 768 et 1165 px, bouton principal de la feuille de filtres rogné à 360 px, libellés non factuels (« Client remboursé », « les plus récents », « Services actifs », total de missions inventé), badge « Non vérifié » affiché quand le profil n'a pas pu être chargé.

## Points ouverts (décisions produit / hors périmètre visuel)

1. **OTP** : aucun écran n'existe côté React ni Flutter (le backend expose `/auth/otp/*`). Non créé, c'est un changement de parcours (programme auth/KYC).
2. **Flutter « Services urgents »** : l'API n'a pas de notion d'urgence (`urgent=true` est ignoré) et le filtre de catégorie envoie `category__name`, que l'API ignore. Comportement antérieur conservé ; à arbitrer avec le backend.
3. **Polices Flutter** : Montserrat/Poppins via `google_fonts` (téléchargées au premier lancement). Pour un fonctionnement 100 % hors ligne, déposer les `.ttf` dans `assets/google_fonts/`.
4. **Relecture indépendante** : quatre surfaces Flutter (accueil, réservation/paiement, auth, artisan) n'ont pas eu de relecture adverse (quota atteint) ; elles ont été contrôlées par l'analyseur, les tests et la navigation ci-dessus.
