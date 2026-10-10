import type { ReactNode } from "react";

// L'ancien « back-office » (/admin) est remplacé par /backoffice : droits par rôle, motifs, audit.
export default function AdminLayout({ children }: { children: ReactNode }) {
  return children;
}
