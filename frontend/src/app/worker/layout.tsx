"use client";
import { LayoutDashboard, ShieldCheck } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { AppShell } from "@/components/ds";

export default function WorkerLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["handyman"]}>
      <AppShell
        title="Espace artisan"
        nav={[
          { href: "/worker", label: "Tableau de bord", icon: LayoutDashboard },
          { href: "/worker/kyc", label: "Vérification (KYC)", icon: ShieldCheck },
        ]}
      >
        {children}
      </AppShell>
    </RoleGuard>
  );
}
