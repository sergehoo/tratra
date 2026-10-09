"use client";
import { ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";
import { BadgeDollarSign, Building2, Search } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { AppShell, Skeleton } from "@/components/ds";
import { DashboardProvider, useDashboard } from "@/lib/dashboard";

/** L'espace entreprise est une capacité du compte (organisation liée), pas un type de compte :
 *  sans organisation, on propose de la créer. */
function CompanyGate({ children }: { children: ReactNode }) {
  const { data, loading } = useDashboard();
  const router = useRouter();
  const hasCompany = data?.capabilities.company ?? false;

  useEffect(() => {
    if (!loading && data && !hasCompany) router.replace("/dashboard/company/new");
  }, [loading, data, hasCompany, router]);

  if (loading || !data || !hasCompany) {
    return <Skeleton className="m-6 h-64 !rounded-card" />;
  }
  return (
    <AppShell
      title="Espace entreprise"
      nav={[
        { href: "/company", label: "Mon entreprise", icon: Building2 },
        { href: "/company/plans", label: "Offres B2B", icon: BadgeDollarSign },
        { href: "/dashboard", label: "Tableau de bord", icon: Search },
        { href: "/dashboard/services", label: "Trouver un service", icon: Search },
      ]}
    >
      {children}
    </AppShell>
  );
}

export default function CompanyLayout({ children }: { children: ReactNode }) {
  return (
    <RoleGuard roles={["client", "employeur", "entreprise", "handyman"]}>
      <DashboardProvider>
        <CompanyGate>{children}</CompanyGate>
      </DashboardProvider>
    </RoleGuard>
  );
}
