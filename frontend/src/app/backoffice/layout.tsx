"use client";
import { Suspense, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { RoleGuard } from "@/components/RoleGuard";
import { Alert, Button, ButtonLink, EmptyState, SkeletonPage } from "@/components/ds";
import { BoProvider, useBo } from "@/lib/BoProvider";
import { BoShell } from "./_components/BoShell";
import { MfaGate } from "./_components/MfaGate";

/** Menu = modules que le rôle peut ouvrir, regroupés en 7 rubriques (confort : chaque endpoint refuse de toute façon ce que le rôle n'autorise pas). */
function Shell({ children }: { children: ReactNode }) {
  const { me, loading, forbidden, error, reload } = useBo();
  const pathname = usePathname();

  if (loading) return <SkeletonPage />;
  if (forbidden) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16">
        <EmptyState
          title="Accès réservé au personnel Tratra"
          description="Ce compte n’a aucun rôle d’administration. Si vous pensez que c’est une erreur, demandez à un super administrateur de vous attribuer un rôle."
          actions={<ButtonLink href="/dashboard">Retour à mon espace</ButtonLink>}
        />
      </div>
    );
  }
  if (error || !me) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16">
        <Alert tone="danger" title="Back-Office indisponible" action={<Button size="sm" variant="outline" onClick={() => void reload()}>Réessayer</Button>}>
          {error || "Les droits n’ont pas pu être chargés."}
        </Alert>
      </div>
    );
  }
  // Double authentification exigée et non vérifiée : aucun module n'est ouvert (le serveur refuse de toute façon chaque appel).
  if (me.mfa?.required && !me.mfa.verified) return <MfaGate mfa={me.mfa} onVerified={() => void reload()} />;
  // Module non autorisé pour ce rôle (lien direct, signet) : état explicite plutôt qu'une page vide ou des squelettes sans fin.
  // Le serveur refuse de toute façon chaque appel : ceci n'est qu'une explication.
  const segment = pathname.split("/")[2];
  const blocked = Boolean(segment) && !me.modules.some((m) => m.path === `/backoffice/${segment}`);
  return (
    <BoShell me={me}>
      {blocked ? (
        <EmptyState
          title="Accès non autorisé"
          description="Votre rôle ne donne pas accès à ce module. Les droits sont appliqués par le serveur : même avec le lien, aucune donnée n’est accessible."
          actions={<ButtonLink href="/backoffice">Retour au tableau de bord</ButtonLink>}
        />
      ) : (
        children
      )}
    </BoShell>
  );
}

export default function BackOfficeLayout({ children }: { children: ReactNode }) {
  // Tout compte connecté peut ouvrir la page : le serveur décide (403 sans rôle). Le garde ne gère que la session.
  return (
    <RoleGuard>
      <BoProvider>
        {/* Les pages lisent `?tab=` et leurs filtres dans l'URL (useSearchParams) : la frontière Suspense est exigée par Next. */}
        <Suspense fallback={<SkeletonPage />}>
          <Shell>{children}</Shell>
        </Suspense>
      </BoProvider>
    </RoleGuard>
  );
}
