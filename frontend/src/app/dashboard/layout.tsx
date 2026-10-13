"use client";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Bell,
  Award,
  Briefcase,
  Building2,
  CalendarCheck,
  CircleDot,
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
import { InboxProvider, useInbox } from "@/lib/inbox";

/** Accès rapides de la barre supérieure : statuts, messages (non lus en temps réel) et notifications. */
function HeaderActions({ notifications }: { notifications: number }) {
  const { unread } = useInbox();
  const items = [
    { href: "/dashboard/statuses", label: "Statuts", icon: CircleDot, badge: 0 },
    { href: "/dashboard/messages", label: unread ? `Messages, ${unread} non lu${unread > 1 ? "s" : ""}` : "Messages", icon: MessageSquare, badge: unread },
    { href: "/dashboard/notifications", label: notifications ? `Notifications, ${notifications} non lue${notifications > 1 ? "s" : ""}` : "Notifications", icon: Bell, badge: notifications },
  ];
  return (
    <nav aria-label="Accès rapides" className="flex items-center gap-0.5">
      {items.map(({ href, label, icon: Icon, badge }) => (
        <Link key={href} href={href} aria-label={label} className="relative grid h-11 w-11 place-items-center rounded-full text-inkSoft transition hover:bg-primarySoft hover:text-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
          <Icon aria-hidden className="h-5 w-5" />
          {badge ? <span className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 text-[10px] font-bold leading-none text-ink ring-2 ring-white">{badge > 99 ? "99+" : badge}</span> : null}
        </Link>
      ))}
    </nav>
  );
}

/** Navigation de l'espace unifié : les entrées « artisan » dépendent du profil réel du compte. */
function Shell({ children }: { children: ReactNode }) {
  const { data } = useDashboard();
  const { unread: unreadMessages } = useInbox();
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
      { href: "/dashboard/messages", label: "Messages", icon: MessageSquare, badge: unreadMessages },
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
  }, [provider, company, business, engagementTodo, unreadMessages, data?.unread.notifications]);

  return (
    <AppShell title="Mon espace" nav={nav} actions={<HeaderActions notifications={data?.unread.notifications ?? 0} />}>
      {children}
    </AppShell>
  );
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <RoleGuard roles={["client", "employeur", "entreprise", "handyman"]}>
      <DashboardProvider>
        <InboxProvider>
          <Shell>{children}</Shell>
        </InboxProvider>
      </DashboardProvider>
    </RoleGuard>
  );
}
