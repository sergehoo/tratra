const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/handy";
let apiOrigin = "http://localhost:8000";

try {
  apiOrigin = new URL(apiBase).origin;
} catch {
  // La configuration d'environnement sera signalée par les appels API ; garder
  // une politique sûre et fonctionnelle plutôt que faire échouer le build.
}

const contentSecurityPolicy = [
  "default-src 'self'",
  // Next.js injecte des scripts de démarrage ; un nonce par requête est l'étape
  // suivante lorsqu'un BFF/cookies HttpOnly sera introduit.
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          ...(process.env.NODE_ENV === "production"
            ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
            : []),
        ],
      },
    ];
  },
};

export default nextConfig;
