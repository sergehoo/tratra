# Back-Office — console d'administration

Console React (`frontend/src/app/backoffice`) au-dessus de l'API Django `/handy/backoffice/…`. **Les droits sont appliqués par le serveur** (`backoffice/rbac.py`, une permission par vue) ; l'interface ne fait que les refléter : un bouton masqué ne protège rien, un lien direct vers un module non autorisé est refusé par l'API. Sécurité des administrateurs : `docs/securite-admin.md`.

## Navigation (7 rubriques)

| Rubrique | Modules (routes inchangées) |
|---|---|
| Vue d'ensemble | Tableau de bord · Statistiques et exports |
| Utilisateurs & Identités | Utilisateurs · Vérification KYC · Tratra Trust · Tratra ID |
| Prestations & Missions | Services · Réservations et litiges · Suivi en direct · Avis · Engagements · Continuité |
| Tratra Business | Organisations · Demandes · Factures |
| Finances | Paiements · Retraits · Factures |
| Communication | Annonces · Notifications · Support |
| Administration | Réglages (5 onglets) · Sécurité et audit |

Le menu n'affiche que les modules autorisés au rôle (`/handy/backoffice/me/`) ; une rubrique sans module visible disparaît, un futur module non classé tombe dans « Administration ». Les sous-menus pointent vers les onglets réels (`?tab=`). Barre latérale rétractable (préférence mémorisée), défilement indépendant, tiroir en mobile, fil d'Ariane, **recherche globale `Ctrl/Cmd + K`** (pages + comptes, dossiers, réservations, paiements… via les API existantes et selon les droits). Le classement est dans `frontend/src/lib/boNavModel.ts` ; `npm run test:bo` vérifie que chaque module du registre serveur apparaît exactement une fois.

## Listes de gestion

Toutes les pages de gestion partagent : recherche et filtres métier **gardés dans l'URL** (lien partageable), pastilles de statut avec **compteurs réels**, tri serveur (en-têtes), pagination (25 / 50 / 100), actualisation, états chargement / vide / erreur, menu d'actions par ligne, actions visibles (ex. Valider / Rejeter un retrait). Colonnes secondaires affichées selon la largeur de l'écran ; le défilement horizontal est borné au tableau (jamais à la page).

- **Actions groupées** (services, avis, signalements, comptes, organisations, besoins, évaluations) : exécutées **élément par élément** par l'endpoint existant — mêmes droits, même motif d'audit, une trace par élément ; le récapitulatif liste les échecs. Aucune API « en masse ».
- **Export CSV** : bouton affiché seulement si le rôle a `analytics.view` **et** le droit du jeu de données (utilisateurs, réservations, paiements, avis, audit, contrats, échéances). Le serveur revérifie, journalise, plafonne à 50 000 lignes et n'exporte jamais de nom, contact ni commentaire.
- Filtres ajoutés côté API : par compte (`user=`) sur réservations, litiges, paiements, contrats, échéances ; texte sur paiements, retraits, factures, litiges, signalements ; période (`from`/`to`) et tri partout où c'est utile ; personnel par texte, rôle, statut et activation de la double authentification.

## Fiches (onglets)

Comptes, dossiers KYC, réservations et organisations ont une fiche à six onglets : Informations générales · Activités et historique · Documents et justificatifs · Paiements et engagements · Notes internes et audit · Actions administratives. Un onglet dont le droit manque n'affiche qu'un message « réservé » ; ses données ne sont chargées qu'à l'ouverture.

## Super Admin

Voit tout ce que le serveur autorise, y compris les coordonnées complètes dans les listes (consultation journalisée, voir `docs/securite-admin.md` § 2 bis) et l'original des pièces KYC (accès protégé, journalisé à chaque ouverture). Aucune validation métier n'est contournée : suspendre, rembourser, trancher un litige passent par les mêmes services et exigent un motif.

## Vérifier visuellement

Dev : API Django + `npm run dev`, un compte staff (jeton JWT dans `sessionStorage` : `tratra_access` / `tratra_refresh`). Largeurs de contrôle : 1920, 1440, 1280, 768, 390 px — aucune barre de défilement horizontale sur la page, aucun texte coupé, aucune erreur console.
