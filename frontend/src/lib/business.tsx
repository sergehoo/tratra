"use client";
/** Tratra Business : types de l'API, contexte d'organisation (rôle et capacités décidés par le serveur) et libellés. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiErrorMessage, get } from "./api";
import { useData } from "./useData";

export interface OrgSummary {
  id: number;
  name: string;
  currency: string;
  role: string;
  role_label: string;
  capabilities: string[];
  scoped_sites: number[];
  city?: string;
  legal_name?: string;
  registration_number?: string;
  industry?: string;
  phone?: string;
  address?: string;
}

export const PRIORITIES: Record<string, { label: string; tone: "gray" | "info" | "warning" | "danger" }> = {
  low: { label: "Basse", tone: "gray" },
  normal: { label: "Normale", tone: "info" },
  high: { label: "Haute", tone: "warning" },
  urgent: { label: "Urgente", tone: "danger" },
};

export const REQUEST_STATUS: Record<string, { label: string; tone: "gray" | "info" | "warning" | "success" | "danger" | "primary" }> = {
  pending_approval: { label: "À valider", tone: "warning" },
  approved: { label: "Validée", tone: "info" },
  dispatched: { label: "Artisan sollicité", tone: "info" },
  scheduled: { label: "Planifiée", tone: "primary" },
  in_progress: { label: "En cours", tone: "primary" },
  completed: { label: "Terminée", tone: "success" },
  rejected: { label: "Refusée", tone: "danger" },
  cancelled: { label: "Annulée", tone: "gray" },
};

export const ROLES: { value: string; label: string; help: string }[] = [
  { value: "admin", label: "Administrateur", help: "Gère l'organisation, les membres, les sites et les règles." },
  { value: "site_manager", label: "Responsable de site", help: "Gère équipements, demandes et affectations de ses sites." },
  { value: "approver", label: "Validateur", help: "Valide ou refuse les demandes." },
  { value: "requester", label: "Demandeur", help: "Crée des demandes d'intervention et suit les siennes." },
  { value: "finance", label: "Finance", help: "Budgets, facturation consolidée, validation des coûts." },
  { value: "viewer", label: "Lecteur", help: "Consultation des tableaux de bord et des demandes." },
];

export interface Site { id: number; name: string; address: string; city: string; postal_code: string; notes: string; is_active: boolean; location: { lat: number; lng: number } | null; equipment_count: number }
export interface Equipment { id: number; name: string; site: number; site_name: string; building: number | null; building_name: string | null; category: number | null; category_name: string | null; reference: string; location_detail: string; installed_on: string | null; warranty_ends_on: string | null; status: string; qr_code: string; notes: string }
export interface Step { order: number; role: string; role_label: string; status: "pending" | "approved" | "rejected"; decided_by_name: string | null; decided_at: string | null; comment: string }
export interface BizRequest {
  id: number; number: string; site: number; site_name: string; equipment: number | null; equipment_name: string | null; title: string; description: string;
  category: number | null; category_name: string | null; priority: string; status: string; source: string; desired_date: string | null;
  estimated_cost: string | null; cost: string | null; contract: number | null; booking_id: number | null; requested_by_name: string; rejection_reason: string;
  steps: Step[]; sla: { due_response_at: string | null; due_resolution_at: string | null; response_met: boolean | null; resolution_met: boolean | null };
  can_decide: boolean; budget_warnings: { budget_id: number; name: string; amount: string; projected: string }[]; created_at: string; completed_at: string | null;
}
export interface Suggestion { user_id: number; profile_id: number; display_name: string; score: number; distance_km: number | null; rating: number; trust_score: number | null; badges: string[]; online: boolean; service_id: number | null; reasons: string[] }
export interface BudgetRow { id: number; name: string; site: number | null; equipment: number | null; period_start: string; period_end: string; amount: string; alert_threshold_pct: number; status: { spent: string; committed: string; remaining: string; percent: number; level: "ok" | "warning" | "exceeded" } }
export interface Dashboard {
  period: { start: string; end: string };
  requests: { created: number; completed: number; open: number; overdue: number; by_status: Record<string, number> };
  pending_my_approval: number;
  sla: { response: { met: number; measured: number; rate: number | null }; resolution: { met: number; measured: number; rate: number | null } };
  durations: { avg_resolution_hours: number | null; avg_response_hours: number | null };
  spend: { total: string; currency: string; unpriced_interventions: number; by_site: { name: string; amount: string }[]; by_category: { name: string; amount: string }[]; by_month: { month: string; amount: string }[] };
  top_equipment: { id: number; name: string; interventions: number }[];
  preventive: { active_plans: number; overdue: number; due_30_days: number };
  budgets: (Omit<BudgetRow, "status" | "site" | "equipment" | "period_start" | "period_end" | "alert_threshold_pct"> & BudgetRow["status"])[];
}

interface Ctx {
  orgs: OrgSummary[];
  org: OrgSummary | null;
  loading: boolean;
  error: string;
  setOrgId: (id: number) => void;
  can: (capability: string) => boolean;
  /** Chemin d'API de l'organisation courante : `/business/orgs/{id}/{sub}`. */
  path: (sub: string) => string;
  reload: () => Promise<void>;
}

const BusinessContext = createContext<Ctx | null>(null);
const STORAGE_KEY = "tratra.business.org";

export function BusinessProvider({ children }: { children: ReactNode }) {
  const [orgs, setOrgs] = useState<OrgSummary[]>([]);
  const [orgId, setId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    try {
      const rows = await get<OrgSummary[]>("/business/orgs/");
      setOrgs(rows);
      setError("");
      let saved: number | null = null;
      try {
        saved = Number(window.localStorage.getItem(STORAGE_KEY)) || null;
      } catch {
        /* stockage indisponible : première organisation */
      }
      setId((cur) => (cur && rows.some((o) => o.id === cur) ? cur : rows.find((o) => o.id === saved)?.id ?? rows[0]?.id ?? null));
    } catch (e) {
      setError(apiErrorMessage(e, "Vos organisations ne peuvent pas être chargées."));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  const org = orgs.find((o) => o.id === orgId) ?? null;
  const value = useMemo<Ctx>(
    () => ({
      orgs,
      org,
      loading,
      error,
      reload,
      setOrgId: (id) => {
        setId(id);
        try {
          window.localStorage.setItem(STORAGE_KEY, String(id));
        } catch {
          /* ignoré */
        }
      },
      can: (c) => Boolean(org?.capabilities.includes(c)),
      path: (sub) => `/business/orgs/${org?.id}/${sub}`,
    }),
    [orgs, org, loading, error, reload],
  );
  return <BusinessContext.Provider value={value}>{children}</BusinessContext.Provider>;
}

export function useBusiness(): Ctx {
  const ctx = useContext(BusinessContext);
  if (!ctx) throw new Error("useBusiness doit être utilisé dans <BusinessProvider>");
  return ctx;
}

/** Ressource GET de l'organisation courante (chemin relatif, ex. « requests/?status=approved »). */
export function useOrgData<T>(sub: string | null, fallback?: string) {
  const { org, path } = useBusiness();
  return useData<T>(org && sub ? path(sub) : null, fallback);
}

export const money = (value: string | number | null | undefined, currency = "XOF"): string => {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} ${currency === "XOF" ? "FCFA" : currency}`;
};

export const shortDate = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" }) : "—";

export const hours = (h: number | null | undefined): string => (h == null ? "—" : h < 48 ? `${Math.round(h * 10) / 10} h` : `${Math.round(h / 24)} j`);
export const pct = (rate: number | null | undefined): string => (rate == null ? "—" : `${Math.round(rate * 100)} %`);
