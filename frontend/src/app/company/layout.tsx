"use client";
import { RoleGuard } from "@/components/RoleGuard";
import { DashboardShell } from "@/components/DashboardShell";

export default function CompanyLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["entreprise"]}>
      <DashboardShell
        title="Espace entreprise"
        nav={[
          { href: "/company", label: "Profil & abonnement" },
          { href: "/client/services", label: "Trouver un service" },
        ]}
      >
        {children}
      </DashboardShell>
    </RoleGuard>
  );
}
