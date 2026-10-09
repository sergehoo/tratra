"use client";
import { useEffect, type RefObject } from "react";

/**
 * Ramène un message de retour (erreur, confirmation) dans la zone visible dès
 * qu'il apparaît ou change : indispensable quand le bouton d'action est collé en
 * bas d'écran et que le message s'affiche plus haut dans la page.
 * Respecte « mouvement réduit » (défilement instantané).
 */
export function useReveal(ref: RefObject<HTMLElement>, message: string) {
  useEffect(() => {
    if (!message) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    ref.current?.scrollIntoView({ block: "center", behavior: reduceMotion ? "auto" : "smooth" });
  }, [ref, message]);
}
