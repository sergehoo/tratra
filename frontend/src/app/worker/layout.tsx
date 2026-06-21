"use client";
import { RoleGuard } from "@/components/RoleGuard";
import { DashboardShell } from "@/components/DashboardShell";

export default function WorkerLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["handyman"]}>
      <DashboardShell
        title="Espace ouvrier"
        nav={[
          { href: "/worker", label: "Tableau de bord" },
          { href: "/worker", label: "Mes missions" },
        ]}
      >
        {children}
      </DashboardShell>
    </RoleGuard>
  );
}
