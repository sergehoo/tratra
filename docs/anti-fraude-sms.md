# Anti-fraude SMS et inscriptions (« SMS pumping »)

## Incident du 23 oct. 2026

Plus de 300 comptes ont été créés en masse sous le même nom (« Rita Kamal »), avec des numéros ivoiriens consécutifs
(+225 01 03 3x xx xx, +225 01 15 98 1x xx). Chaque compte demandait des codes de vérification par SMS jusqu'à épuiser le crédit Twilio.

**Cause** :

- l'inscription (`POST /handy/users/`) était publique, sans anti-robot, et limitée seulement à 60 requêtes par minute et par IP ;
- chaque compte pouvait ensuite demander 5 SMS par heure (`/auth/otp/request/`), sans limite par IP, par numéro, par appareil ni au total ;
- aucune destination n'était restreinte ;
- aucun cache partagé n'était configuré. Les limites de débit et les compteurs d'essais étaient donc comptés **par processus** :
  avec plusieurs workers, chaque limite valait N fois sa valeur.

## Protections (app `antifraud`)

| Couche | Où | Réglage |
|---|---|---|
| Interrupteurs : plus aucun SMS, ni dépense | `antifraud/sms_guard.py` (tout SMS passe par `handy.sms.send_sms`) | `SMS_ENABLED`, `SMS_OTP_SIGNUP_ENABLED`, `SMS_RECOVERY_ENABLED`, `SMS_ALERTS_ENABLED` |
| Destinations : indicatifs autorisés, numéros mobiles uniquement | idem | `SMS_ALLOWED_COUNTRY_CODES` (225) |
| Quotas atomiques Redis : IP, numéro, compte, global (heure, jour) | idem | `SMS_*_LIMIT` |
| Alertes : journal critique (Sentry) et e-mail aux `ADMINS`, à 80 % puis à l'épuisement | idem | `SMS_ALERT_RATIO` |
| Journal de chaque tentative (envoyé, bloqué, échec), sans texte ni code, numéro masqué + empreinte | `SmsLog` (admin en lecture seule) | — |
| Inscription : anti-robot du site, limites par IP, appareil et global, même nom répété, bloc de numéros | `antifraud/signup_guard.py`, `UserViewSet.create` | `SIGNUP_*`, `TURNSTILE_*` |
| Journal des inscriptions (IP, appareil, acceptée ou refusée, raison) | `SignupLog` | — |
| Code OTP : délai croissant (60 s, 2, 5 puis 10 min), 5 par heure, code encore valide renvoyé, numéro déjà vérifié = aucun SMS, essais comptés atomiquement avant vérification (5 puis verrou) | `handy/api/views.py`, `handy/api/recovery.py` | `THROTTLE_OTP`, `THROTTLE_OTP_VERIFY` |
| Récupération : mêmes contrôles appliqués avant de savoir si le compte existe (aucune énumération) | `recovery.py` | — |
| Changement de numéro limité (3 par jour) | `UserSerializer.update` | `PHONE_CHANGES_DAILY_LIMIT` |
| Comptes non vérifiés : réservation, commande Flash, message, avis, paiement, KYC, engagements refusés (403 `phone_not_verified`) | `antifraud/permissions.py` | `UNVERIFIED_RESTRICTIONS`, `UNVERIFIED_RESTRICTIONS_SINCE` |
| Cache partagé Redis obligatoire en production | `tratra/settings/{base,prod}.py` | `CACHE_URL` (sinon `REDIS_URL`, base n° 1) |

L'application mobile ne peut pas afficher Turnstile. Elle envoie un identifiant d'installation (`X-Tratra-Device`) et reste soumise
aux mêmes protections serveur, qui valent pour tous les clients : un robot peut se faire passer pour l'application. Turnstile
peut être exigé partout (`TURNSTILE_MODE=all`) le jour où l'application l'intégrera.

## Actions urgentes en production (dans cet ordre)

1. **Couper les dépenses tout de suite**, sans déploiement. Dans le `.env` de production, retirer `SMS_BACKEND` empêche tout
   démarrage (prod.py l'exige) : ne pas le faire. Il faut plutôt :
   - désactiver les identifiants SMS côté fournisseur : console Twilio, *Messaging > Settings > Geo permissions* (garder la Côte
     d'Ivoire seule), et activer *SMS Pumping Protection* / *Fraud Guard* ;
   - ou laisser le crédit à zéro tant que le correctif n'est pas déployé.
2. **Déployer ce correctif**, migrations comprises : `antifraud 0001`, `announcements 0002`, `handy 0059`. Puis vérifier :
   - que le cache est bien Redis : `python manage.py shell -c "from django.conf import settings; print(settings.CACHES['default']['BACKEND'])"` ;
   - le cas échéant, que le démarrage refuse un cache local (production).
3. **Tant que l'attaque dure**, poser `SMS_OTP_SIGNUP_ENABLED=false`, redémarrer le web et le worker, puis vérifier les journaux.
   Les utilisateurs voient : « L'envoi de codes par SMS est momentanément suspendu ».
4. **Turnstile** (gratuit, Cloudflare) : créer un widget pour `tratra.net`, poser `TURNSTILE_SECRET_KEY` (API), puis reconstruire le
   site avec `NEXT_PUBLIC_TURNSTILE_SITE_KEY`.
5. **Comptes suspects** : rapport d'abord, action ensuite.
   ```
   python manage.py antifraud_accounts report --since 2026-10-20 --out /tmp/suspects.json
   # relire /tmp/suspects.json et /tmp/suspects.csv
   python manage.py antifraud_accounts suspend --report /tmp/suspects.json --confirm DESACTIVER-COMPTES
   # annulation complète : antifraud_accounts revert --batch N --confirm REACTIVER-COMPTES
   # un compte légitime : antifraud_accounts restore --batch N --user ID
   ```
   Rien n'est supprimé. Un compte vérifié ou ayant une activité réelle n'est jamais désactivé (revérifié au moment de l'action).
6. **Comptes historiques non vérifiés** (clients réels du pilote) : poser `UNVERIFIED_RESTRICTIONS_SINCE` à la date du déploiement
   pour ne pas bloquer leurs réservations.
7. Configurer `ADMINS` (« Nom <adresse>, adresse2 ») et un SMTP réel (`EMAIL_*`, `SERVER_EMAIL`), ainsi que Sentry, pour recevoir
   les alertes de quota. Sans `ADMINS`, aucune alerte ne part par e-mail (seulement le journal critique).

## Réglages par défaut (pilote)

- SMS : 30 par heure, 150 par jour au total ; 3 par heure et 6 par jour par numéro ; 5 par heure et 15 par jour par IP ; 8 par jour par compte.
- Inscriptions : 5 par heure et 20 par jour par IP ; 3 par jour par appareil ; 60 par heure au total ; même nom complet 3 par jour ;
  même bloc de 1 000 numéros 3 par heure.

Ces valeurs sont à ajuster à la croissance réelle du trafic, en surveillant `SmsLog` (raisons des blocages) et `SignupLog`.

## Cloudflare (compte sergehoo@gmail.com, zone `tratra.net`, offre Free)

Préparé le 23 oct. 2026, **sans effet tant que les serveurs DNS ne sont pas basculés** chez Hostinger :

- **Turnstile** : widget « Tratra - inscription et codes SMS » (mode géré, `tratra.net`). Clé publique : `0x4AAAAAAFizZy2RKlNFFRgd` →
  `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (au BUILD du site). Clé secrète : à copier depuis Cloudflare → `TURNSTILE_SECRET_KEY` (API). Les deux en
  même temps, sinon les inscriptions du site sont refusées (« vérification anti-robot requise »).
- **DNS** importés et complétés : `tratra.net`, `api` (proxy), `minioapi` (**DNS seulement** : médias et pièces servis comme aujourd'hui),
  `www` (proxy, à rediriger vers `tratra.net`).
- **Règles** : limitation de débit (10 requêtes / 10 s par IP sur inscription, codes SMS, récupération, connexion → blocage 10 s) ;
  blocage des chemins de scanners (`/wp-admin`, `/.env`, `/.git`, `phpmyadmin`, `/cgi-bin`…).
- **Ne PAS activer** : « Under Attack », « Bot Fight Mode », défis JavaScript sur `api.tratra.net` (l'application mobile n'est pas un
  navigateur et serait bloquée).

### Avant de basculer les serveurs DNS (dans cet ordre)

1. Déployer ce code puis poser `CLOUDFLARE_PROXY=true` : l'API lit alors l'adresse réelle du visiteur (`CF-Connecting-IP`, crue seulement
   depuis une adresse Cloudflare). Sans cela, toutes les limites par IP verraient Cloudflare et bloqueraient tout le monde.
2. SSL/TLS → mode **Full (strict)** (certificats Let's Encrypt valides sur les trois hôtes), « Always Use HTTPS » laissé à **off** :
   Traefik et Django redirigent déjà vers HTTPS, et un renouvellement Let's Encrypt par défi HTTP doit pouvoir passer en http.
3. Vérifier le type de défi ACME de Traefik : `tlsChallenge` (TLS-ALPN) **ne fonctionne pas** derrière le proxy Cloudflare → passer au
   défi HTTP, au défi DNS (jeton API Cloudflare limité à la zone) ou à un certificat d'origine Cloudflare.
4. Hostinger → domaine `tratra.net` → serveurs DNS : remplacer `ns1/ns2.dns-parking.com` par `casey.ns.cloudflare.com` et
   `nancy.ns.cloudflare.com` ; DNSSEC désactivé chez Hostinger (réactivable ensuite depuis Cloudflare).
5. Après activation : tester le site, l'application mobile (connexion, réservation, notifications, images), le Back-Office.
6. Ensuite seulement : n'autoriser que les adresses Cloudflare sur les ports 80/443 du serveur (pare-feu), pour qu'on ne puisse plus
   contourner Cloudflare en appelant l'IP 147.93.84.26 directement.

### E-mail du domaine et adresse du serveur (recommandations Cloudflare)

- **Recevoir `support@tratra.net`** (affichée dans l'application, les pages légales et Google Play) : Cloudflare → Email → Email
  Routing → activer, puis règle `support@` → boîte de l'équipe (adresse à confirmer depuis l'e-mail de vérification). Cloudflare
  ajoute lui-même les MX, le SPF (`include:_spf.mx.cloudflare.net`) et la clé DKIM de routage.
- **DMARC** : Email → DMARC Management → activer (rapports agrégés chez Cloudflare), d'abord `p=quarantine`, puis `p=reject` après
  deux semaines de rapports propres. Si le serveur envoie un jour en `@tratra.net` (alertes, SMTP), ajouter son fournisseur au SPF
  et publier sa clé DKIM AVANT de durcir DMARC.
- **IP d'origine** : `minioapi` passé en « Proxied » (règle de cache « jamais en cache » déjà en place pour cet hôte : toutes les URL
  de médias sont signées et privées). Limite Cloudflare Free : 100 Mo par requête (pièces KYC limitées à 10 Mo). Retour arrière :
  repasser l'enregistrement en « DNS only ». L'IP 147.93.84.26 reste connue de l'historique DNS : seul un pare-feu n'acceptant que
  les adresses Cloudflare sur 80/443 la protège vraiment (attention aux autres sites hébergés sur ce serveur).
