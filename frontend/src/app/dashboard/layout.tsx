"use client";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Bell,
  Award,
  Briefcase,
  Building2,
  CalendarCheck,
  Compass,
  FileSignature,
  IdCard,
  LayoutDashboard,
  Megaphone,
  MessageSquare,
  PlusCircle,
  ShieldCheck,
  Star,
  Wallet,
} from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { AppShell, type NavItem } from "@/components/ds";
import { get } from "@/lib/api";
import { DashboardProvider, useDashboard } from "@/lib/dashboard";

/** Navigation de l'espace unifié : les entrées « artisan » dépendent du profil réel du compte. */
function Shell({ children }: { children: ReactNode }) {
  const { data } = useDashboard();
  const provider = data?.capabilities.provider ?? false;
  const company = data?.capabilities.company ?? false;
  const business = data?.capabilities.business ?? false;
  const [engagementTodo, setEngagementTodo] = useState(0);
  // Pastille « à faire » des engagements : compteur réel du serveur ; en cas d'échec, simplement absente.
  useEffect(() => {
    let alive = true;
    get<{ todo_count: number }>("/engagements/me/overview/").then((o) => alive && setEngagementTodo(o.todo_count)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

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
      { href: "/dashboard/engagements", label: "Engagements", icon: FileSignature, badge: engagementTodo || undefined },
      { href: "/dashboard/messages", label: "Messages", icon: MessageSquare, badge: data?.unread.messages },
      { href: "/dashboard/wallet", label: "Portefeuille", icon: Wallet },
      { href: "/dashboard/reviews", label: "Avis", icon: Star },
      { href: "/dashboard/notifications", label: "Notifications", icon: Bell, badge: data?.unread.notifications },
      { href: "/dashboard/announcements", label: "Annonces", icon: Megaphone },
      { href: "/dashboard/profile", label: "Mon profil et KYC", icon: ShieldCheck },
    );
    if (business || company) items.push({ href: "/dashboard/business", label: "Tratra Business", icon: Building2, primary: false });
    items.push(
      company
        ? { href: "/company", label: "Espace entreprise", icon: Building2 }
        : { href: "/dashboard/company/new", label: "Créer un espace entreprise", icon: Building2 },
    );
    return items;
  }, [provider, company, business, engagementTodo, data?.unread.messages, data?.unread.notifications]);

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
