# Sécurité de l'administration Tratra — procédure

Périmètre : comptes `is_staff` (Back-Office `/backoffice`, API `/handy/backoffice/…`, droits « personnel » de l'ancienne API, `/admin/`).

## 1. Rôles des administrateurs historiques

Un compte du personnel sans rôle garde un accès global à l'ancienne API tant que `LEGACY_STAFF_BYPASS` est vrai. **En production le défaut est désormais FAUX.**
À faire AVANT la mise en service (poste avec accès à la base cible) :

```bash
python manage.py assign_legacy_staff_roles                        # simulation : liste les comptes sans rôle (aucune modification)
python manage.py assign_legacy_staff_roles --assign 8=super_admin --assign 12=support --apply   # rôle choisi compte par compte (moindre privilège)
python manage.py security_preflight --strict                      # doit afficher « Aucun bloquant » (code 0)
```
Rôles : `super_admin`, `ops`, `support`, `finance`, `marketing`, `analyst` (droits : `backoffice/rbac.py`). Garder **au moins deux** super administrateurs.
Chaque attribution est journalisée (`security.legacy_role_assigned`). Poste de développement : les comptes #8 (propriétaire) et #12 (QA) ont reçu `super_admin` / `support`.

## 2. Double authentification (TOTP)

- Exigée par `BACKOFFICE_MFA_REQUIRED` (**défaut : vrai en production**, faux en développement). Applications : Google/Microsoft Authenticator, 1Password…
- Activation par l'administrateur lui-même à sa première connexion : Back-Office (écran « Activer la double authentification ») ou `/admin/mfa/`.
  Mot de passe → QR → premier code → **10 codes de secours affichés une seule fois**.
- Sans preuve de vérification : Back-Office → 403 `mfa_required` / `mfa_enrollment_required` ; ancienne API → aucun droit « personnel » (même superutilisateur) ; `/admin/` → redirection vers `/admin/mfa/`.
- La preuve est portée par le jeton d'accès (`mfa_at`, `mfa_c`) : validité `BACKOFFICE_MFA_MAX_AGE` (12 h), invalidée par toute réinitialisation de l'appareil.
- Protections : secret chiffré au repos (Fernet, clé `MFA_ENCRYPTION_KEY` dédiée sinon `SECRET_KEY`), code à usage unique (anti-rejeu), verrouillage 15 min après 5 échecs, limitation de débit (`THROTTLE_MFA`), journal d'audit (`backoffice.mfa.*`).
- **Appareil perdu** : un AUTRE super administrateur ouvre Back-Office → Sécurité → Administrateurs → « Réinit. MFA » (motif obligatoire, sessions révoquées), ou en console :
  `python manage.py staff_mfa --reset <id> --reason "…"`. Le compte réactive un appareil à sa connexion suivante. État : `python manage.py staff_mfa`.
- Changer `MFA_ENCRYPTION_KEY` (ou `SECRET_KEY` si pas de clé dédiée) rend les secrets illisibles : chaque administrateur doit être réinitialisé puis ré-enrôler son appareil.

## 3. Ordre de mise en service

1. Migrations (`backoffice` 0003 : nouvelle table `backoffice_staffmfa`, non destructive).
2. `assign_legacy_staff_roles` puis `security_preflight --strict`.
3. Variables : `BACKOFFICE_MFA_REQUIRED=1`, `LEGACY_STAFF_BYPASS=0` (ce sont les défauts de production ; les écrire explicitement dans `.env`).
4. Chaque administrateur active son appareil et range ses codes de secours.
5. `check --deploy` : aucun avertissement `tratra.W001` / `tratra.W002`.

Retour arrière d'urgence (perte de tous les appareils) : `BACKOFFICE_MFA_REQUIRED=0` le temps de réinitialiser les comptes — l'écart est signalé par `check --deploy` et doit être court.
