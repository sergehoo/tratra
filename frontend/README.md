# Tratra — Frontend Web (React / Next.js)

Frontend découplé de la marketplace Tratra. Consomme l'API Django (`/handy/…`).
Trois espaces : **Client**, **Ouvrier (handyman)**, **Entreprise (B2B)** + **Admin**.

## Stack
- Next.js 14 (App Router) + TypeScript
- Tailwind CSS (thème vert `#2e8b57` / jaune `#F6C90E`)
- Auth JWT (access + refresh) avec **rafraîchissement automatique sur 401**

## Démarrage
```bash
cd frontend
cp .env.local.example .env.local      # ajuster NEXT_PUBLIC_API_BASE si besoin
npm install
npm run dev                           # http://localhost:3000
```
Le backend Django doit tourner (`python manage.py runserver`) et autoriser
`http://localhost:3000` dans `CORS_ALLOWED_ORIGINS` (déjà configuré).

## Documentation de l'API
- Swagger : http://localhost:8000/api/docs/
- Schéma OpenAPI : http://localhost:8000/api/schema/

## Structure
```
src/
  lib/        config, types, client API (api.ts), contexte d'auth (auth.tsx)
  components/ UI (Button/Card/Input), DashboardShell, RoleGuard
  app/        login, register, et espaces client/ worker/ company/ admin/
```

## Conventions
- Routes protégées par rôle via `<RoleGuard role="...">` (redirige selon `user_type`).
- Toutes les requêtes passent par `apiJson()` / `apiFetch()` (Authorization + refresh).
- Après login, redirection automatique vers l'espace correspondant au `user_type`.
