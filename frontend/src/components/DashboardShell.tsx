"use client";
import { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

export interface NavItem {
  href: string;
  label: string;
}

export function DashboardShell({
  title,
  nav,
  children,
}: {
  title: string;
  nav: NavItem[];
  children: ReactNode;
}) {
  const { user, logout } = useAuth();
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-slate-50 text-ink">
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-slate-100 bg-white p-5 md:flex">
        <div className="mb-8 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary font-extrabold text-white">T</span>
          <span className="text-xl font-extrabold">
            <span className="text-primary">TRA</span>
            <span className="text-accent">TRA</span>
          </span>
        </div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-ash">{title}</p>
        <nav className="flex flex-col gap-1">
          {nav.map((n) => {
            const active = pathname === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`rounded-xl px-3 py-2 text-sm font-medium transition ${
                  active ? "bg-primarySoft text-primaryDark" : "text-ash hover:bg-slate-50 hover:text-ink"
                }`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <button
          onClick={logout}
          className="mt-auto rounded-xl px-3 py-2 text-left text-sm font-medium text-ash hover:bg-slate-50 hover:text-ink"
        >
          Déconnexion
        </button>
      </aside>

      <div className="md:pl-64">
        <header className="flex h-16 items-center justify-between border-b border-slate-100 bg-white px-6">
          <h1 className="text-lg font-bold">{title}</h1>
          <span className="text-sm text-ash">
            {user?.first_name || user?.username}{" "}
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">{user?.user_type}</span>
          </span>
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  );
}
