"use client";
import { BadgeDollarSign, Building2, Search } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { AppShell } from "@/components/ds";

export default function CompanyLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["entreprise"]}>
      <AppShell
        title="Espace entreprise"
        nav={[
          { href: "/company", label: "Mon entreprise", icon: Building2 },
          { href: "/company/plans", label: "Offres B2B", icon: BadgeDollarSign },
          { href: "/dashboard/services", label: "Trouver un service", icon: Search },
        ]}
      >
        {children}
      </AppShell>
    </RoleGuard>
  );
}
