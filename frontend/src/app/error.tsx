"use client";
import { useEffect } from "react";
import { House, RotateCw, Wrench } from "lucide-react";
import { Button, buttonClass } from "@/components/ds";
import { SystemScreen, SystemTile } from "@/components/system/SystemScreen";

/**
 * Erreur inattendue pendant l'affichage d'une page (limite d'erreur racine).
 * Le message reste volontairement sans détail technique ; l'erreur est seulement
 * consignée dans la console du navigateur pour le diagnostic.
 */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <SystemScreen
      eyebrow="Erreur inattendue"
      title="Une erreur est"
      accent="survenue"
      titleId="erreur-titre"
      description="Nous n’avons pas pu afficher cette page. Ce n’est pas de votre fait : réessayez dans un instant, ou revenez à l’accueil pour reprendre depuis le début."
      visual={
        <SystemTile>
          <Wrench className="h-8 w-8 sm:h-10 sm:w-10" strokeWidth={2.2} />
        </SystemTile>
      }
      actions={
        <>
          <Button type="button" variant="accent" size="lg" onClick={() => reset()} leftIcon={<RotateCw aria-hidden className="h-5 w-5" />}>
            Réessayer
          </Button>
          {/* Lien natif : un rechargement complet sort de l'état d'erreur, même si la panne est sur « / ». */}
          <a href="/" className={buttonClass("outlineLight", "lg")}>
            <House aria-hidden className="h-5 w-5" />
            Retour à l’accueil
          </a>
        </>
      }
    />
  );
}
