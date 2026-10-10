"use client";
import { useMemo, type ReactNode } from "react";
import {
  Bell,
  Award,
  Briefcase,
  Building2,
  CalendarCheck,
  Compass,
  LayoutDashboard,
  MessageSquare,
  PlusCircle,
  ShieldCheck,
  Star,
  Wallet,
} from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { AppShell, type NavItem } from "@/components/ds";
import { DashboardProvider, useDashboard } from "@/lib/dashboard";

/** Navigation de l'espace unifié : les entrées « artisan » dépendent du profil réel du compte. */
function Shell({ children }: { children: ReactNode }) {
  const { data } = useDashboard();
  const provider = data?.capabilities.provider ?? false;
  const company = data?.capabilities.company ?? false;

  const nav = useMemo<NavItem[]>(() => {
    const items: NavItem[] = [
      { href: "/dashboard", label: "Tableau de bord", short: "Accueil", icon: LayoutDashboard, primary: true },
      { href: "/dashboard/services", label: "Explorer les services", short: "Explorer", icon: Compass, primary: true },
      { href: "/dashboard/bookings", label: "Mes réservations", short: "Réservations", icon: CalendarCheck, primary: true },
    ];
    if (provider) {
      items.push({ href: "/dashboard/provider", label: "Mes prestations", short: "Prestations", icon: Briefcase, primary: true });
    }
    items.push(
      { href: "/dashboard/provide", label: "Proposer un service", short: "Proposer", icon: PlusCircle, primary: !provider },
      { href: "/dashboard/messages", label: "Messages", icon: MessageSquare, badge: data?.unread.messages },
      { href: "/dashboard/wallet", label: "Portefeuille", icon: Wallet },
      { href: "/dashboard/reviews", label: "Avis", icon: Star },
      { href: "/dashboard/notifications", label: "Notifications", icon: Bell, badge: data?.unread.notifications },
      { href: "/dashboard/profile", label: "Mon profil et KYC", icon: ShieldCheck },
    );
    items.push(
      company
        ? { href: "/company", label: "Espace entreprise", icon: Building2 }
        : { href: "/dashboard/company/new", label: "Créer un espace entreprise", icon: Building2 },
    );
    return items;
  }, [provider, company, data?.unread.messages, data?.unread.notifications]);

  return (
    <AppShell title="Mon espace" nav={nav}>
      {children}
    </AppShell>
  );
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <RoleGuard roles={["client", "employeur", "entreprise", "handyman"]}>
      <DashboardProvider>
        <Shell>{children}</Shell>
      </DashboardProvider>
    </RoleGuard>
  );
}
