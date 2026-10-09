/*
 * Service worker Tratra (vanilla, sans dépendance).
 *
 * Principes :
 *  - Uniquement les requêtes GET de même origine.
 *  - JAMAIS de mise en cache : l'API (/handy/), les requêtes portant un en-tête
 *    Authorization, les espaces connectés (/client, /worker, /company, /admin),
 *    /login et /register. Ces navigations passent par le réseau ; hors-ligne,
 *    elles affichent la page /offline (sans rien stocker de leur contenu).
 *  - Cache-first pour les ressources statiques (/_next/static/, /icons/,
 *    /images/, polices, fichiers de marque).
 *  - Network-first avec repli /offline pour les navigations publiques.
 *
 * Changer CACHE_VERSION purge tous les anciens caches à l'activation.
 */
const CACHE_VERSION = "v3"; // v3 : espace /dashboard unifié, v2 : nouveau logo officiel
const CACHE_PREFIX = "tratra-";
const CORE_CACHE = `${CACHE_PREFIX}core-${CACHE_VERSION}`;
const STATIC_CACHE = `${CACHE_PREFIX}static-${CACHE_VERSION}`;
const PAGES_CACHE = `${CACHE_PREFIX}pages-${CACHE_VERSION}`;
const KNOWN_CACHES = [CORE_CACHE, STATIC_CACHE, PAGES_CACHE];

const OFFLINE_URL = "/offline";
const CORE_ASSETS = ["/icons/icon-192.png", "/icons/icon-512.png", "/icons/maskable-512.png"];

const STATIC_CACHE_MAX = 180;
const PAGES_CACHE_MAX = 30;

/** Préfixes jamais mis en cache (comparaison stricte par segment). */
const NEVER_CACHE = ["/handy", "/api", "/dashboard", "/client", "/worker", "/company", "/admin", "/login", "/register"];

function matchesPrefix(pathname, prefix) {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

function isNeverCached(pathname) {
  return NEVER_CACHE.some((prefix) => matchesPrefix(pathname, prefix));
}

function isStaticAsset(request, url) {
  const path = url.pathname;
  return (
    path.startsWith("/_next/static/") ||
    path.startsWith("/icons/") ||
    path.startsWith("/images/") ||
    request.destination === "font" ||
    /\.(?:woff2?|ttf|otf)$/i.test(path) ||
    path === "/tratra_logo.webp" ||
    path === "/icon.png" ||
    path === "/apple-icon.png"
  );
}

/** Réponse stockable : 200, même origine, non redirigée, sans no-store/private. */
function isCacheable(response) {
  if (!response || response.status !== 200 || response.type !== "basic" || response.redirected) return false;
  const cacheControl = (response.headers.get("Cache-Control") || "").toLowerCase();
  return !cacheControl.includes("no-store") && !cacheControl.includes("private");
}

async function trimCache(cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  const excess = keys.length - maxEntries;
  for (let i = 0; i < excess; i += 1) {
    await cache.delete(keys[i]);
  }
}

async function cacheIfOk(cache, url) {
  const response = await fetch(new Request(url, { cache: "reload", credentials: "same-origin" }));
  if (response.ok) await cache.put(url, response);
}

/**
 * Pré-cache la page hors-ligne ET les ressources /_next/static/ qu'elle
 * référence (CSS, JS, polices préchargées) : elle s'affiche alors stylée et
 * interactive même sans réseau.
 */
async function precacheCore() {
  const cache = await caches.open(CORE_CACHE);
  const response = await fetch(new Request(OFFLINE_URL, { cache: "reload", credentials: "same-origin" }));
  if (!response.ok) throw new Error(`Page hors-ligne indisponible (${response.status})`);
  const html = await response.clone().text();
  await cache.put(OFFLINE_URL, response);

  const assets = new Set(html.match(/\/_next\/static\/[^"'\s<>()\\]+/g) || []);
  CORE_ASSETS.forEach((asset) => assets.add(asset));
  await Promise.allSettled(Array.from(assets, (asset) => cacheIfOk(cache, asset)));
}

self.addEventListener("install", (event) => {
  // skipWaiting est sûr ici : aucune coquille applicative n'est pré-cachée,
  // le nouveau worker ne change que la stratégie réseau/cache.
  event.waitUntil(precacheCore().then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && !KNOWN_CACHES.includes(key))
          .map((key) => caches.delete(key)),
      );
      await self.clients.claim();
    })(),
  );
});

async function offlineFallback() {
  const cached = await caches.match(OFFLINE_URL);
  return (
    cached ||
    new Response(
      "<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Hors ligne · Tratra</title><body style=\"font-family:system-ui,sans-serif;padding:2rem;text-align:center;color:#0f172a\"><h1>Vous êtes hors ligne</h1><p>Vérifiez votre connexion puis rechargez la page.</p><p><a href=\"/\" style=\"color:#1f6a41\">Retour à l'accueil</a></p></body></html>",
      { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } },
    )
  );
}

/** Navigation publique : réseau d'abord, copie locale en secours, sinon /offline. */
async function networkFirstPage(request) {
  try {
    const response = await fetch(request);
    if (isCacheable(response)) {
      const copy = response.clone();
      caches
        .open(PAGES_CACHE)
        .then((cache) => cache.put(request, copy))
        .then(() => trimCache(PAGES_CACHE, PAGES_CACHE_MAX))
        .catch(() => undefined);
    }
    return response;
  } catch (error) {
    const cached = await caches.match(request, { cacheName: PAGES_CACHE });
    return cached || offlineFallback();
  }
}

/** Navigation privée (espaces connectés, login, register) ou /offline : réseau seul. */
async function networkOnlyPage(request) {
  try {
    return await fetch(request);
  } catch (error) {
    return offlineFallback();
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (isCacheable(response)) {
    const copy = response.clone();
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.put(request, copy))
      .then(() => trimCache(STATIC_CACHE, STATIC_CACHE_MAX))
      .catch(() => undefined);
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  // Contournement d'un bug Chrome DevTools (only-if-cached hors same-origin).
  if (request.cache === "only-if-cached" && request.mode !== "same-origin") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.headers.has("Authorization")) return;
  if (url.pathname === "/sw.js") return;

  if (request.mode === "navigate") {
    // /offline est déjà dans le cache « core » : inutile de le dupliquer.
    if (isNeverCached(url.pathname) || url.pathname === OFFLINE_URL) {
      event.respondWith(networkOnlyPage(request));
    } else {
      event.respondWith(networkFirstPage(request));
    }
    return;
  }

  // API et ressources privées : jamais interceptées (comportement réseau natif).
  if (isNeverCached(url.pathname)) return;

  if (isStaticAsset(request, url)) {
    event.respondWith(cacheFirst(request));
  }
  // Tout le reste (données RSC, /_next/image, manifest…) : réseau natif.
});
