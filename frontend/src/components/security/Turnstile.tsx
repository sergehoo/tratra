"use client";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Cloudflare Turnstile (anti-robot) pour les parcours qui créent un compte ou envoient un SMS : inscription, code de vérification,
 * code de récupération. Actif seulement si `NEXT_PUBLIC_TURNSTILE_SITE_KEY` est défini ; le jeton (à usage unique) est vérifié par
 * le serveur (antifraud/turnstile.py), qui refuse la demande sans lui. Après chaque envoi, `reset()` en redemande un nouveau.
 */
export const TURNSTILE_SITE_KEY = (process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "").trim();
const SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

interface TurnstileApi {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  reset: (id?: string) => void;
  remove: (id: string) => void;
}
declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

let loading: Promise<void> | null = null;
function loadScript(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (window.turnstile) return Promise.resolve();
  loading ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SCRIPT;
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => {
      loading = null;
      reject(new Error("turnstile"));
    };
    document.head.appendChild(s);
  });
  return loading;
}

/** Widget + jeton courant. `required` faux : rien à afficher, aucun jeton exigé. Le widget peut changer de place (étapes d'un
 *  formulaire) : il est rendu dans l'élément actuellement monté (référence-fonction). */
export function useTurnstile(): { required: boolean; token: string | null; widget: ReactNode; reset: () => void; failed: boolean } {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const id = useRef<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const required = Boolean(TURNSTILE_SITE_KEY);

  useEffect(() => {
    if (!required || !box) return;
    let cancelled = false;
    loadScript()
      .then(() => {
        if (cancelled || !window.turnstile) return;
        id.current = window.turnstile.render(box, {
          sitekey: TURNSTILE_SITE_KEY,
          language: "fr",
          theme: "light",
          callback: (t: string) => { setToken(t); setFailed(false); },
          "expired-callback": () => setToken(null),
          "error-callback": () => { setToken(null); setFailed(true); },
        });
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      if (id.current && window.turnstile) window.turnstile.remove(id.current);
      id.current = null;
      setToken(null);
    };
  }, [required, box]);

  const reset = useCallback(() => {
    setToken(null);
    if (id.current && window.turnstile) window.turnstile.reset(id.current);
  }, []);

  const widget = required ? (
    <div className="space-y-1">
      <div ref={setBox} className="min-h-[65px]" data-testid="turnstile" />
      {failed ? <p className="text-xs text-dangerInk">La vérification anti-robot n’a pas pu se charger : vérifiez votre connexion puis rechargez la page.</p> : null}
    </div>
  ) : null;
  return { required, token, widget, reset, failed };
}
