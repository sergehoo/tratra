"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { apiErrorMessage, get } from "./api";
import { useAuth } from "./auth";

/** Réponse de GET /me/dashboard/ — données réelles de l'utilisateur courant (client ET/OU artisan). */
export interface BookingCounts {
  pending: number;
  confirmed: number;
  in_progress: number;
  completed: number;
  cancelled: number;
  total: number;
}

export interface DashItem {
  id: number;
  /** « client » : j'ai réservé ; « handyman » : on m'a réservé. */
  role: "client" | "handyman";
  title: string;
  category: string | null;
  status: string;
  booking_date: string | null;
  city: string | null;
  counterpart: string;
}

export interface ChecklistItem {
  key: string;
  label: string;
  hint: string;
  done: boolean;
}

export type KycStatus = "none" | "pending" | "approved" | "rejected";

export interface ProviderBlock {
  profile_id: number;
  /** Badges Tratra Trust actuels (NOUVEAU tant que l'identité n'est pas vérifiée). */
  badges?: { code: "NOUVEAU" | "VERIFIE" | "EXPERT" | "SUR"; label: string }[];
  trust_score?: number | null;
  online: boolean;
  is_approved: boolean;
  publishable: boolean;
  rating: number | null;
  completed_jobs: number;
  completion: { percent: number; done: number; total: number; items: ChecklistItem[] };
  kyc: {
    status: KycStatus;
    required: string[];
    documents: { pending: number; approved: number; rejected: number };
    rejection_reason: string | null;
  };
  services: { active: number; total: number };
  missions: BookingCounts;
  earnings: { available: string; currency: string };
  next_missions: DashItem[];
  recent_missions: DashItem[];
}

/** Destinations neutres renvoyées par l'API (le backend ne connaît aucune URL). */
export type ActionTarget = "provider" | "profile" | "profile_kyc" | "reviews" | "messages" | "verify_phone";

export interface DashAction {
  key: string;
  severity: "danger" | "warning" | "info";
  target: ActionTarget;
  title: string;
  description: string;
}

export interface DashboardData {
  generated_at: string;
  user: { id: number; first_name: string; display_name: string; phone: string | null; is_verified: boolean; user_type: string };
  capabilities: { client: boolean; provider: boolean; publishable: boolean; company: boolean; business?: boolean };
  client: { bookings: BookingCounts; next_bookings: DashItem[]; recent_bookings: DashItem[]; reviews_to_write: number };
  provider: ProviderBlock | null;
  upcoming: DashItem[];
  reviews: { received_count: number; received_average: number | null; to_write: number };
  unread: { notifications: number; messages: number };
  actions: DashAction[];
}

/** Traduction des destinations de l'API en routes de l'application web. */
export const TARGET_HREF: Record<ActionTarget, string> = {
  provider: "/dashboard/provider",
  profile: "/dashboard/profile",
  profile_kyc: "/dashboard/profile/kyc",
  reviews: "/dashboard/reviews",
  messages: "/dashboard/messages",
  verify_phone: "/verify-phone?next=/dashboard",
};

interface DashboardState {
  data: DashboardData | null;
  loading: boolean;
  error: string;
  reload: () => Promise<void>;
}

const Ctx = createContext<DashboardState | null>(null);

/** Charge une seule fois le tableau de bord pour le layout (navigation) et les pages.
 *  Lié au COMPTE : un changement d'utilisateur vide les données et ignore toute réponse en vol
 *  du compte précédent (aucune donnée d'une session ne survit à la suivante). */
export function DashboardProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const uid = user?.id ?? null;
  const current = useRef<number | null>(uid);
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    const asked = current.current;
    setError("");
    try {
      const fresh = await get<DashboardData>("/me/dashboard/");
      if (asked === current.current) setData(fresh);
    } catch (e) {
      if (asked === current.current) setError(apiErrorMessage(e, "Le tableau de bord n’a pas pu être chargé."));
    } finally {
      if (asked === current.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    current.current = uid;
    setData(null);
    setError("");
    setLoading(true);
    if (uid !== null) void reload();
  }, [uid, reload]);

  const value = useMemo(() => ({ data, loading, error, reload }), [data, loading, error, reload]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDashboard(): DashboardState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useDashboard doit être utilisé dans <DashboardProvider>");
  return ctx;
}
