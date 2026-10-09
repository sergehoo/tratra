import type { Metadata } from "next";
import { House, WifiOff } from "lucide-react";
import { Badge } from "@/components/ds/Badge";
import { buttonClass } from "@/components/ds/Button";
import RetryButton from "./RetryButton";

export const metadata: Metadata = {
  title: "Hors ligne",
  description: "Connexion interrompue : vérifiez votre réseau puis réessayez.",
  robots: { index: false, follow: false },
  alternates: { canonical: "/offline" },
};

// Page entièrement statique : pré-cachée par le service worker (public/sw.js).
export const dynamic = "force-static";

export default function OfflinePage() {
  return (
    <main className="relative flex min-h-[100svh] items-center justify-center overflow-hidden bg-canvas px-4 py-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 left-1/2 h-80 w-[44rem] max-w-[160vw] -translate-x-1/2 rounded-full bg-primary/15 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-28 -right-24 h-64 w-64 rounded-full bg-accent/25 blur-3xl"
      />

      <section
        aria-labelledby="offline-title"
        className="relative w-full max-w-md animate-rise overflow-hidden rounded-card border border-lineSoft bg-white shadow-strong"
      >
        <div aria-hidden="true" className="h-1.5 bg-gradient-to-r from-primary via-primary to-accent" />

        <div className="px-6 pb-8 pt-10 text-center sm:px-10">
          <div className="relative mx-auto flex h-20 w-20 items-center justify-center rounded-card bg-night shadow-glow">
            <WifiOff className="h-9 w-9 text-accent" strokeWidth={2.2} aria-hidden="true" />
            <span
              aria-hidden="true"
              className="absolute -right-1.5 -top-1.5 h-4 w-4 animate-pulseDot rounded-full border-2 border-white bg-accent"
            />
          </div>

          <Badge tone="accent" dot className="mt-6">
            Connexion interrompue
          </Badge>

          <h1
            id="offline-title"
            className="mt-4 font-display text-2xl font-extrabold tracking-tight text-ink sm:text-3xl"
          >
            Vous êtes hors ligne
          </h1>
          <p className="mx-auto mt-3 max-w-sm text-[15px] leading-relaxed text-ash">
            Impossible de joindre Tratra pour le moment. Vérifiez votre Wi‑Fi ou vos données mobiles, puis
            réessayez&nbsp;: la page se rechargera dès le retour du réseau.
          </p>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:justify-center">
            <RetryButton />
            {/* Lien natif (pas de navigation client) : traité par le service worker même hors-ligne. */}
            <a href="/" className={buttonClass("outline", "lg")}>
              <House className="h-5 w-5 text-primary" aria-hidden="true" />
              Retour à l&apos;accueil
            </a>
          </div>
        </div>

        <footer className="flex items-center justify-center gap-2.5 border-t border-lineSoft bg-canvas px-6 py-4 text-xs font-medium text-ash">
          {/* Icône pré-cachée par le service worker : visible même sans réseau. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/icons/icon-192.png" alt="" width={20} height={20} className="h-5 w-5 rounded" />
          <span>
            <span className="font-display font-bold text-night">Tratra</span> · Artisans vérifiés à domicile
          </span>
        </footer>
      </section>
    </main>
  );
}
