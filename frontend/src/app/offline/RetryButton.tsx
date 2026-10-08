"use client";
import { useEffect, useState } from "react";
import { RotateCw } from "lucide-react";

/**
 * Recharge la page demandée (le service worker sert /offline à la place de
 * l'URL d'origine, qui reste dans la barre d'adresse). Recharge aussi
 * automatiquement dès que le navigateur signale le retour du réseau.
 */
export default function RetryButton() {
  const [retrying, setRetrying] = useState(false);

  const retry = () => {
    setRetrying(true);
    window.location.reload();
  };

  useEffect(() => {
    const onOnline = () => {
      setRetrying(true);
      window.location.reload();
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, []);

  return (
    <button
      type="button"
      onClick={retry}
      disabled={retrying}
      className="inline-flex min-h-[48px] items-center justify-center gap-2 rounded-xl bg-primary px-6 py-3 font-semibold text-white shadow-glow transition hover:bg-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-wait disabled:opacity-80"
    >
      <RotateCw className={`h-5 w-5 ${retrying ? "animate-spin" : ""}`} aria-hidden="true" />
      {retrying ? "Nouvelle tentative…" : "Réessayer"}
    </button>
  );
}
