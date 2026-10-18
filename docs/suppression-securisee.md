# Suppression sécurisée des données (administration et nettoyage des données de démonstration)

`on_delete=PROTECT` reste en place (paiements, réservations, pièces KYC…). La suppression passe par `handy/safe_delete.py`.

## Dans l'administration (`/admin/`, superutilisateur uniquement)
Comptes (`Users`) et `Bookings` : cocher les lignes → action **« Supprimer en sécurité (aperçu et confirmation)… »** (ou le bouton « Supprimer » d'une fiche).
1. **Aperçu exact** : la suppression est exécutée puis annulée ; décision par ligne et décompte des objets.
2. **Décisions** : *Suppression définitive* (donnée fictive reconnue), *Anonymisation* (compte réel ou argent réel : écritures conservées, plus de nom / téléphone / e-mail), *Conservé* (administrateur, son propre compte, réservation à paiement réel).
3. **Confirmation** : taper `SUPPRIMER` ; la case « données fictives » permet de supprimer vraiment un compte qui n'en a pas l'apparence, **jamais** de l'argent réel.
4. Trace d'audit `admin.safe_delete` (identifiants et compteurs, aucune donnée personnelle). 50 éléments au plus par opération.

Argent réel (jamais effacé) : paiement vérifié auprès d'un prestataire ou avec session prestataire, retrait demandé/envoyé, caution encaissée, abonnement, compte de versement vérifié.
Donnée fictive (signaux structurels, jamais le nom ou l'e-mail) : jamais connecté, conditions jamais acceptées, aucune session, aucun OTP, aucun appareil, hors administration.

## Nettoyage en masse : `cleanup_demo_data`
```bash
# 1. Simulation (rien n'est modifié) + fichier de sélection à RELIRE
docker compose exec tratraweb python manage.py cleanup_demo_data --dry-run --selection-out /tmp/demo_selection.json
# 2. Relire le fichier (retirer toute ligne douteuse), faire une sauvegarde de la base de moins de 48 h
docker compose exec tratradb pg_dump -U "$DB_USER" "$DB_NAME" > /sauvegardes/tratra_avant_nettoyage.sql
# 3. Exécution : sélection relue + sauvegarde + mot de confirmation
docker compose exec tratraweb python manage.py cleanup_demo_data --execute --selection /tmp/demo_selection.json \
    --backup /sauvegardes/tratra_avant_nettoyage.sql --confirm SUPPRIMER-DONNEES-DEMO
```
Chaque compte de la sélection est revérifié avant l'exécution : un seul qui a changé (connexion, argent réel…) arrête tout, rien n'est supprimé.
Pour quelques comptes précis choisis à la main : `python manage.py purge_accounts --ids 12,13` (simulation par défaut, `--apply` pour supprimer).
