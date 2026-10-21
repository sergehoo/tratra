# Push mobile (FCM) — mise en service et qualification

**État** : le serveur et l'application sont prêts ; il manque uniquement le projet Firebase de Tratra (compte de service + applications Android/iOS + clé APNs).
Tant qu'il n'est pas configuré : aucun push, aucune erreur — la notification in-app reste la source fiable. **Aucun secret n'est dans Git** (règles : `.gitignore`,
`.dockerignore`, test `handy/test_secrets_hygiene.py`, `test/firebase_config_test.dart`).

## 1. Projet Firebase (une fois, par environnement : staging distinct de la production)

1. Console Firebase → projet dédié → **Cloud Messaging API (V1)** activée (Google Cloud → API et services).
2. Ajouter l'app **Android** `com.tratra` et l'app **iOS** `com.tratra` (identifiants réels du build ; la copie de recette Android utilise `com.tratra.recette`).
3. **iOS** : Paramètres du projet → Cloud Messaging → *Clé d'authentification APNs* : téléverser la clé `.p8` (Apple Developer → Keys → APNs) avec Key ID et Team ID.
   Dans Xcode : capacité *Push Notifications* et *Background Modes → Remote notifications* (déjà déclarées dans `Runner.entitlements` / `Info.plist`), équipe de signature valide.
4. Comptes de service → **Générer une nouvelle clé privée** (JSON) — réservé au SERVEUR.

## 2. Serveur (secret hors Git)

```bash
sudo install -o 10001 -g 10001 -m 400 fcm-service-account.json secrets/        # dossier ./secrets monté en lecture seule
# .env : FCM_CREDENTIALS_FILE=/run/tratra-secrets/fcm-service-account.json   (FCM_PROJECT_ID facultatif)
docker compose … up -d tratraweb-stg worker                                    # recharge l'environnement
docker compose … exec tratraweb-stg python manage.py push_check --token       # configuration chargée + jeton OAuth Google obtenu
```
`push_check` n'affiche jamais de secret. Détruire la copie locale du JSON (`shred -u`).

## 3. Application (configuration injectée au build, rien dans le dépôt)

Valeurs : Console Firebase → Paramètres du projet → Vos applications. Deux options, au choix :
- **Fichiers natifs** (hors Git) : `android/app/google-services.json` ; iOS : `GoogleService-Info.plist` ajouté à la cible Runner dans Xcode.
- **`--dart-define`** (recommandé en CI, sans fichier) — `lib/services/firebase_config.dart` :
  ```bash
  flutter build apk --release --dart-define=TRATRA_API_BASE=https://api-staging.example.com/handy \
    --dart-define=FIREBASE_PROJECT_ID=… --dart-define=FIREBASE_MESSAGING_SENDER_ID=… \
    --dart-define=FIREBASE_API_KEY_ANDROID=… --dart-define=FIREBASE_APP_ID_ANDROID=…
  flutter build ipa … --dart-define=FIREBASE_API_KEY_IOS=… --dart-define=FIREBASE_APP_ID_IOS=… --dart-define=FIREBASE_IOS_BUNDLE_ID=com.tratra
  ```
  Si une valeur manque, l'application retombe sur la configuration native, puis sur « sans push » : jamais de configuration à moitié renseignée.

## 4. Qualification sur appareils réels (à faire par un opérateur — non réalisable sans projet Firebase ni téléphone)

Préparer : installer l'APK / l'IPA de staging, se connecter avec un compte de recette, **autoriser les notifications** (Android 13+ : dialogue système ; iOS : dialogue au premier lancement).
Vérifier l'enregistrement : `manage.py push_check` doit afficher `android=1` (ou `ios=1`) ; puis, pour chaque cas ci-dessous, depuis le serveur :

```bash
manage.py push_check --user <ID> --validate     # FCM valide le message SANS le remettre (jeton, droits, charge utile)
manage.py push_check --user <ID> --send         # push RÉEL « Test Tratra »
```
| Cas | Procédure | Attendu |
|---|---|---|
| Application **fermée** (balayée) | `--send`, écran verrouillé | Notification visible (canal « tratra_default » Android, son iOS) ; toucher → l'app s'ouvre sur les notifications |
| Application en **arrière-plan** | idem | idem ; toucher → `onMessageOpenedApp` |
| Application **ouverte** | idem | bandeau in-app (Android) / bannière (iOS) |
| Lien profond | créer un contrat de test, laisser `engagements-tick` envoyer « Échéance à venir » | toucher → fiche du contrat (`tratra://contract/<id>`) |
| Mission | réserver / confirmer une mission de recette | l'autre partie reçoit le push, toucher → mission/suivi |
| Annonce | publier une annonce depuis le Back-Office | reçue une seule fois ; coupée si « Annonces » est désactivée |
| Compte différent | se déconnecter, se connecter avec un autre compte | l'appareil ne reçoit plus les notifications du premier compte |
| Jeton périmé | désinstaller puis relancer `--send` | `removed: 1` (jeton supprimé) ; réinstaller → réenregistrement |

Résultat attendu de `--send` : `{'sent': 1, 'removed': 0, 'failed': 0, 'devices': 1, 'skipped': None}`. Échec fréquent : `skipped: no_access_token` → compte de service invalide ou API FCM v1 non activée ;
iOS sans notification → clé APNs absente de Firebase ou identifiant de bundle différent.

## 5. Écran verrouillé, pastilles, widget et raccourcis

- **Contenu sensible** : messages, paiements, compte (KYC, sécurité) → push à texte NEUTRE (« Nouveau message — Awa K. vous a écrit »,
  « Mise à jour d'un paiement : ouvrez Tratra… ») et visibilité Android `PRIVATE` ; le détail reste dans l'application. Aperçu du texte des
  messages activable par l'exploitant : `PUSH_MESSAGE_PREVIEW=True`.
- **Pastilles** : nombre de notifications non lues envoyé à iOS (`aps.badge`) et à Android (`notification_count`, affiché par les lanceurs
  qui le gèrent, Samsung notamment ; ailleurs un point).
- **Widget d'accueil Android** et **raccourcis d'application** (Android, iOS) : voir `lib/services/home_widget_sync.dart` ; mêmes liens
  profonds que les notifications (`tratra://explore|bookings|messages|pro`). Widget iOS (WidgetKit) : non réalisé (cible d'extension Xcode).

## 6. Ce qui est vérifié automatiquement (sans Firebase)

Charge utile exacte (priorité haute Android, canal, APNs priority 10, badge, `collapse_key`), jeton OAuth mis en cache, jetons morts supprimés, échecs transitoires comptés pour reprise,
préférences par catégorie, une seule notification par événement (idempotence), cycle de vie d'une mission, annonces planifiées livrées une fois, échéances mensuelles
(tick → notification → push avec lien profond du contrat), liens profonds et reprise à froid côté Flutter. **Non vérifiable sans compte Firebase réel : la remise effective par Google/Apple.**

## 7. Activation réelle (21 oct. 2026) — projet Firebase « Tratra »

- Projet `tratra-380c5` (expéditeur 386488746571), API Firebase Cloud Messaging (V1) activée, ancienne API désactivée.
- Applications Android enregistrées : `com.tratra` (Play Store) et `com.tratra.recette` (recette, installable à côté). Un seul
  `google-services.json` contient les deux ; il va dans `flutter_tratra/android/app/` (ignoré par Git) et le plugin Google Services
  s'applique alors automatiquement au build.
- Compte de service `firebase-adminsdk-fbsvc` : clé privée gardée hors Git (poste de développement : `~/.tratra-firebase/`,
  droits 600) ; en production, la déposer sur le serveur et renseigner `FCM_CREDENTIALS_FILE`. Ne jamais la committer ni l'afficher.
- **Qualifié sur Galaxy S10+ (Android 12)**, backend local + FCM réel, événements réels (client qui réserve et écrit) :
  nouvelle demande de réservation/mission (app en arrière-plan), nouveau message (app FERMÉE, processus tué), app ouverte
  (bandeau « Voir » + pastille d'onglet), téléphone en veille ; canal `tratra_default` importance haute (bannière), visibilité
  PRIVATE (rien sur l'écran verrouillé, texte du message jamais envoyé), compteur de pastille, regroupement par conversation ;
  toucher → conversation ou détail de la mission ; préférence « Messages » coupée → aucun push (`skipped: disabled`).
- Restent à qualifier : permission Android 13+ (le S10+ est en Android 12), iOS (APNs), déconnexion sur l'appareil (couverte par
  les tests automatisés).
