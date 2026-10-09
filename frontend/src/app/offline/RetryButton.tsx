"use client";
import { useEffect, useState } from "react";
import { RotateCw } from "lucide-react";
import { Button } from "@/components/ds/Button";

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
    <Button
      type="button"
      size="lg"
      onClick={retry}
      loading={retrying}
      leftIcon={<RotateCw aria-hidden className="h-5 w-5" />}
    >
      {retrying ? "Nouvelle tentative…" : "Réessayer"}
    </Button>
  );
}
