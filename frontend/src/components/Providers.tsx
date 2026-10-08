"use client";
import type { ReactNode } from "react";
import { LazyMotion, MotionConfig, domAnimation } from "framer-motion";
import { AuthProvider } from "@/lib/auth";

/**
 * Fournisseurs globaux côté client.
 * - LazyMotion + domAnimation : charge uniquement les fonctions d'animation DOM
 *   (utiliser les composants `m.*` de framer-motion pour un bundle léger).
 * - MotionConfig reducedMotion="user" : respecte prefers-reduced-motion.
 */
export default function Providers({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domAnimation}>
      <MotionConfig reducedMotion="user">
        <AuthProvider>{children}</AuthProvider>
      </MotionConfig>
    </LazyMotion>
  );
}
