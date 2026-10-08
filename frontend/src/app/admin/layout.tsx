"use client";
import { LayoutDashboard, Scale, ShieldCheck } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { AppShell } from "@/components/ds";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["admin"]}>
      <AppShell
        title="Back-office"
        nav={[
          { href: "/admin", label: "Vue d’ensemble", icon: LayoutDashboard },
          { href: "/admin/kyc", label: "Vérifications KYC", icon: ShieldCheck },
          { href: "/admin/disputes", label: "Litiges", icon: Scale },
        ]}
      >
        {children}
      </AppShell>
    </RoleGuard>
  );
}
