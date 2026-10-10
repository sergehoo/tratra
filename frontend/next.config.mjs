const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/handy";
let apiOrigin = "http://localhost:8000";

try {
  apiOrigin = new URL(apiBase).origin;
} catch {
  // La configuration d'environnement sera signalée par les appels API ; garder
  // une politique sûre et fonctionnelle plutôt que faire échouer le build.
}

// Origines servant les médias (photos de services/artisans) : l'API elle-même
// et, en production, le stockage objet (S3/MinIO) déclaré explicitement.
const mediaOrigins = (process.env.NEXT_PUBLIC_MEDIA_ORIGINS ?? "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean)
  .flatMap((value) => {
    try {
      return [new URL(value).origin];
    } catch {
      return [];
    }
  });
// Fond de carte du suivi en direct : gabarit d'URL de tuiles configurable (OpenStreetMap par défaut — à remplacer par un
// fournisseur adapté au volume en production, cf. docs). Son origine est ajoutée à img-src.
const tileTemplate = process.env.NEXT_PUBLIC_MAP_TILES ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
let tileOrigins = [];
try {
  tileOrigins = [new URL(tileTemplate.replace(/\{[a-z]\}/g, "a")).origin];
} catch {
  // gabarit invalide : aucune origine supplémentaire (la carte n'affichera pas de fond)
}
const imgSources = Array.from(new Set(["'self'", "data:", "blob:", apiOrigin, ...mediaOrigins, ...tileOrigins]));
// WebSocket du suivi en direct : même origine que l'API (ws:// ou wss://).
const wsOrigin = apiOrigin.replace(/^http/, "ws");

// `next dev` (React Refresh / sourcemaps webpack « eval ») exige 'unsafe-eval' :
// sans lui aucune page n'hydrate en développement. Jamais en production.
const isDev = process.env.NODE_ENV !== "production";

const contentSecurityPolicy = [
  "default-src 'self'",
  // Next.js injecte des scripts de démarrage ; un nonce par requête est l'étape
  // suivante lorsqu'un BFF/cookies HttpOnly sera introduit.
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src ${imgSources.join(" ")}`,
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin} ${wsOrigin}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Dossier de build surchargeable (ex. NEXT_DIST_DIR=.next-verify) pour vérifier un build
  // sans perturber un `next dev` en cours dans le même dossier.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Espace utilisateur unifié : les anciennes routes (/client, /worker) restent valides (redirections
  // temporaires 307 : la requête, query comprise, est conservée).
  async redirects() {
    return [
      { source: "/client", destination: "/dashboard/bookings", permanent: false },
      { source: "/client/services", destination: "/dashboard/services", permanent: false },
      { source: "/client/services/:id", destination: "/dashboard/services/:id", permanent: false },
      { source: "/client/bookings/:id", destination: "/dashboard/bookings/:id", permanent: false },
      { source: "/worker", destination: "/dashboard/provider", permanent: false },
      { source: "/worker/missions/:id", destination: "/dashboard/provider/missions/:id", permanent: false },
      { source: "/worker/kyc", destination: "/dashboard/profile/kyc", permanent: false },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          // geolocation=(self) : nécessaire à la recherche « autour de moi ».
          { key: "Permissions-Policy", value: "camera=(), geolocation=(self), microphone=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          ...(process.env.NODE_ENV === "production"
            ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
            : []),
        ],
      },
      {
        // Service worker PWA : toujours revalidé (mises à jour immédiates),
        // portée racine autorisée, type MIME explicite.
        source: "/sw.js",
        headers: [
          { key: "Content-Type", value: "application/javascript; charset=utf-8" },
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
    ];
  },
};

export default nextConfig;
