"use client";
import { CalendarCheck, Search } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { AppShell } from "@/components/ds";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["client", "employeur", "entreprise"]}>
      <AppShell
        title="Espace client"
        nav={[
          { href: "/client", label: "Mes réservations", icon: CalendarCheck },
          { href: "/client/services", label: "Trouver un service", icon: Search },
        ]}
      >
        {children}
      </AppShell>
    </RoleGuard>
  );
}
