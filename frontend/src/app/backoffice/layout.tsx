"use client";
import { useMemo, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Award, BarChart3, Bell, Briefcase, Building2, CalendarCheck, FileSignature, IdCard, LayoutDashboard, LifeBuoy, Lock, MapPin, Megaphone, RefreshCw, Settings,
  ShieldCheck, Star, Users, Wallet, type LucideIcon,
} from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { Alert, AppShell, Button, ButtonLink, EmptyState, SkeletonPage, type NavItem } from "@/components/ds";
import { BoProvider, useBo } from "@/lib/BoProvider";

const ICONS: Record<string, LucideIcon> = {
  "layout-dashboard": LayoutDashboard, users: Users, "shield-check": ShieldCheck, award: Award, "id-card": IdCard, briefcase: Briefcase,
  "calendar-check": CalendarCheck, "map-pin": MapPin, star: Star, "building-2": Building2, wallet: Wallet, megaphone: Megaphone, bell: Bell,
  "file-signature": FileSignature, "refresh-cw": RefreshCw, "life-buoy": LifeBuoy, "bar-chart-3": BarChart3, settings: Settings, lock: Lock,
};

/** Menu = modules que le rôle peut ouvrir (confort : chaque endpoint refuse de toute façon ce que le rôle n'autorise pas). */
function Shell({ children }: { children: ReactNode }) {
  const { me, loading, forbidden, error, reload } = useBo();
  const pathname = usePathname();
  const nav = useMemo<NavItem[]>(
    () => (me?.modules ?? []).map((m, i) => ({ href: m.path, label: m.label, icon: ICONS[m.icon], primary: i < 4 })),
    [me],
  );

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
  // Module non autorisé pour ce rôle (lien direct, signet) : état explicite plutôt qu'une page vide ou des squelettes sans fin.
  // Le serveur refuse de toute façon chaque appel : ceci n'est qu'une explication.
  const segment = pathname.split("/")[2];
  const blocked = Boolean(segment) && !me.modules.some((m) => m.path === `/backoffice/${segment}`);
  return (
    <AppShell title="Back-Office" nav={nav}>
      <p className="mb-5 text-xs text-ash">
        Connecté en tant que <strong className="text-inkSoft">{me.user.name}</strong> · rôle{me.roles.length > 1 ? "s" : ""} : {me.roles.join(", ")}.{" "}
        <Link href="/dashboard" className="font-semibold text-primaryDark underline underline-offset-2">Mon espace</Link>
      </p>
      {blocked ? (
        <EmptyState
          title="Accès non autorisé"
          description="Votre rôle ne donne pas accès à ce module. Les droits sont appliqués par le serveur : même avec le lien, aucune donnée n’est accessible."
          actions={<ButtonLink href="/backoffice">Retour au tableau de bord</ButtonLink>}
        />
      ) : (
        children
      )}
    </AppShell>
  );
}

export default function BackOfficeLayout({ children }: { children: ReactNode }) {
  // Tout compte connecté peut ouvrir la page : le serveur décide (403 sans rôle). Le garde ne gère que la session.
  return (
    <RoleGuard>
      <BoProvider>
        <Shell>{children}</Shell>
      </BoProvider>
    </RoleGuard>
  );
}
