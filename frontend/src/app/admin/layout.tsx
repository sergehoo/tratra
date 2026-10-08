"use client";
import { RoleGuard } from "@/components/RoleGuard";
import { DashboardShell } from "@/components/DashboardShell";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["admin"]}>
      <DashboardShell
        title="Back-office"
        nav={[
          { href: "/admin", label: "Vue d'ensemble" },
          { href: "/admin/kyc", label: "Vérif. KYC" },
          { href: "/admin/disputes", label: "Litiges" },
        ]}
      >
        {children}
      </DashboardShell>
    </RoleGuard>
  );
}
