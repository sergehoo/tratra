"use client";
import { useEffect } from "react";

/** Préfixe des caches créés par public/sw.js (purgés en développement). */
const CACHE_PREFIX = "tratra-";

/**
 * Enregistre le service worker (/sw.js) en production uniquement.
 * En développement, désenregistre tout service worker existant et purge ses
 * caches pour ne jamais servir de ressources obsolètes pendant le dev (HMR).
 */
export default function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;

    if (process.env.NODE_ENV !== "production") {
      navigator.serviceWorker
        .getRegistrations()
        .then((registrations) => Promise.all(registrations.map((registration) => registration.unregister())))
        .catch(() => undefined);
      if ("caches" in window) {
        caches
          .keys()
          .then((keys) => Promise.all(keys.filter((key) => key.startsWith(CACHE_PREFIX)).map((key) => caches.delete(key))))
          .catch(() => undefined);
      }
      return;
    }

    const register = () => {
      navigator.serviceWorker
        .register("/sw.js", { scope: "/", updateViaCache: "none" })
        .catch(() => undefined); // PWA = amélioration progressive : l'échec reste silencieux.
    };

    // Après le chargement complet : ne concurrence pas le rendu initial.
    if (document.readyState === "complete") {
      register();
      return;
    }
    window.addEventListener("load", register, { once: true });
    return () => window.removeEventListener("load", register);
  }, []);

  return null;
}
