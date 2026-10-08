# Tratra

Marketplace de services à domicile : API Django/ASGI, interface web Next.js et
application mobile Flutter (maintenue dans le dépôt compagnon
`../handy_tratra/flutter_tratra`).

## Architecture

- `tratra/`, `handy/` : API Django, WebSockets, tâches Celery et administration.
- `frontend/` : interface web Next.js pour clients, artisans, entreprises et
  opérations internes.
- PostgreSQL/PostGIS, Redis, MinIO et Celery sont définis dans
  `docker-compose.yml`.

L’API est disponible sous `/handy/`; la documentation OpenAPI sous
`/api/docs/`. Le frontend est une application distincte et doit être livré avec
sa propre image Next.js (désormais décrite dans le compose).

`/healthz` vérifie que le processus répond ; `/readyz` vérifie aussi Postgres
et Redis et doit être utilisé par l’orchestrateur pour décider si l’API peut
recevoir du trafic.

## Démarrage local

1. Copier `.env.example` vers `.env` et remplacer les valeurs factices. Ne
   versionnez jamais ce fichier. En développement sans MinIO, définissez
   `MINIO_ENABLED=False`.
2. Démarrer les services : `docker compose up --build`.
3. L’API répond sur le domaine défini par `tratraweb_HOST`; le frontend sur
   `FRONTEND_HOST`.

Pour développer uniquement le frontend :

```sh
cd frontend
cp .env.local.example .env.local
npm ci
npm run dev
```

## Vérifications avant livraison

```sh
cd frontend && npm run build
cd .. && pytest
```

La CI exécute ces vérifications depuis un checkout propre. Un changement ne
doit pas dépendre de fichiers ignorés ou présents seulement sur une machine
locale.

## Sécurité et données sensibles

- Les documents KYC doivent rester dans le bucket privé distinct
  `KYC_STORAGE_BUCKET_NAME` et être distribués uniquement via le point de
  téléchargement authentifié. Ne réutilisez jamais le bucket média pour ces
  documents.
- Les variables de paiement, de messagerie et de supervision sont obligatoires
  en production. Les connecteurs de paiement ne doivent pas être activés sans
  identifiants fournisseurs, webhooks signés et réconciliation testée.
- Sauvegardez Postgres et MinIO avant chaque migration ; testez une restauration
  avant une mise en production.

Après le déploiement de la migration KYC, inspectez d’abord les documents
existants sans modifier de données :

```sh
python manage.py migrate_kyc_documents_to_private_storage --limit 20
```

Puis exécutez la copie complète avec `--apply`. N’ajoutez `--delete-source`
qu’après contrôle des copies privées, puis retirez les anciennes politiques ou
objets publics du bucket historique.

## Mise en production

Définissez impérativement `DJANGO_ENV=prod`, `ALLOWED_HOSTS`,
`CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, des hôtes HTTPS distincts pour
l’API et le frontend, et `NEXT_PUBLIC_API_BASE` avec l’URL publique de l’API.
Le reverse proxy Traefik est externe au compose et doit fournir TLS pour les
deux hôtes. Exposez Adminer uniquement derrière une authentification forte et,
idéalement, une liste d’adresses IP autorisées.
