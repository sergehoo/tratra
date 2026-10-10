"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Alert, Select, SkeletonPage, cx } from "@/components/ds";
import { BusinessProvider, useBusiness } from "@/lib/business";
import { Onboarding } from "@/components/business/Onboarding";

const NAV: { href: string; label: string; cap?: string[] }[] = [
  { href: "/dashboard/business", label: "Vue d’ensemble" },
  { href: "/dashboard/business/requests", label: "Demandes" },
  { href: "/dashboard/business/sites", label: "Sites et équipements", cap: ["view.structure"] },
  { href: "/dashboard/business/contracts", label: "Contrats et préventif", cap: ["view.structure"] },
  { href: "/dashboard/business/budgets", label: "Budgets", cap: ["reports.view", "budgets.manage"] },
  { href: "/dashboard/business/invoices", label: "Facturation", cap: ["invoices.manage"] },
  { href: "/dashboard/business/members", label: "Membres", cap: ["members.manage"] },
  { href: "/dashboard/business/settings", label: "Paramètres", cap: ["approval_rules.manage", "audit.view", "org.manage"] },
];

function Frame({ children }: { children: ReactNode }) {
  const { orgs, org, loading, error, setOrgId, can } = useBusiness();
  const pathname = usePathname();
  if (loading) return <SkeletonPage />;
  if (error) return <Alert tone="danger">{error}</Alert>;
  if (!org) return <Onboarding />;
  const items = NAV.filter((n) => !n.cap || n.cap.some(can));
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        {orgs.length > 1 ? (
          <div className="w-64 max-w-full">
            <label htmlFor="org-switch" className="sr-only">Organisation</label>
            <Select id="org-switch" value={org.id} onChange={(e) => setOrgId(Number(e.target.value))}>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </Select>
          </div>
        ) : (
          <p className="font-display text-lg font-bold text-ink">{org.name}</p>
        )}
        <span className="rounded-full bg-primarySoft px-3 py-1 text-xs font-semibold text-primaryDark">{org.role_label}</span>
      </div>
      <nav aria-label="Tratra Business" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {items.map((n) => {
          const active = n.href === "/dashboard/business" ? pathname === n.href : pathname.startsWith(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              aria-current={active ? "page" : undefined}
              className={cx(
                "whitespace-nowrap rounded-full px-4 py-2 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                active ? "bg-primaryDark text-white shadow-hair" : "bg-white text-inkSoft ring-1 ring-line hover:bg-primarySoft",
              )}
            >
              {n.label}
            </Link>
          );
        })}
      </nav>
      <div key={org.id}>{children}</div>
    </div>
  );
}

export default function BusinessLayout({ children }: { children: ReactNode }) {
  return (
    <BusinessProvider>
      <Frame>{children}</Frame>
    </BusinessProvider>
  );
}
