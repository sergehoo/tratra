"use client";
import { RoleGuard } from "@/components/RoleGuard";
import { DashboardShell } from "@/components/DashboardShell";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["client", "employeur", "entreprise"]}>
      <DashboardShell
        title="Espace client"
        nav={[
          { href: "/client", label: "Mes réservations" },
          { href: "/client/services", label: "Trouver un service" },
        ]}
      >
        {children}
      </DashboardShell>
    </RoleGuard>
  );
}
