"use client";
import { RoleGuard } from "@/components/RoleGuard";
import { DashboardShell } from "@/components/DashboardShell";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["admin"]}>
      <DashboardShell
        title="Back-office"
        nav={[{ href: "/admin", label: "Vue d'ensemble" }]}
      >
        {children}
      </DashboardShell>
    </RoleGuard>
  );
}
