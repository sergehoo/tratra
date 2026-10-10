/** Tratra Live : types de l'API de suivi en direct (mêmes charges utiles que le mobile). */
import { API_BASE } from "./config";

export type LivePhase = "pending" | "confirmed" | "en_route" | "arrived" | "in_progress" | "completed" | "cancelled";

export interface LivePosition {
  lat: number;
  lng: number;
  accuracy: number | null;
  speed: number | null;
  heading: number | null;
  captured_at: string;
  age_seconds: number;
  stale: boolean;
}

export interface LiveRoute {
  eta_seconds: number;
  eta_minutes: number;
  distance_m: number;
  polyline: [number, number][];
  /** « osrm » : itinéraire routier réel ; « estimate » : estimation à vol d'oiseau. */
  source: "osrm" | "estimate";
  updated_at: string;
}

export interface LiveState {
  booking_id: number;
  role: "artisan" | "client";
  phase: LivePhase;
  status: string;
  server_time: string;
  window_open: boolean;
  stale_after_seconds: number;
  consent: { artisan: boolean; client: boolean };
  can: { start_route: boolean; arrive: boolean; share_position: boolean };
  artisan: { sharing: boolean; position: LivePosition | null };
  client: { sharing: boolean; position: LivePosition | null };
  destination: { lat: number; lng: number; source: "booking" | "client_position" } | null;
  route: LiveRoute | null;
  milestones: { en_route_at: string | null; arrived_at: string | null };
}

/** URL WebSocket (même origine que l'API) pour un billet délivré par POST /live/ticket/. */
export function liveSocketUrl(path: string, ticket: string): string {
  const origin = new URL(API_BASE).origin.replace(/^http/, "ws");
  return `${origin}${path}?ticket=${encodeURIComponent(ticket)}`;
}

export function formatDistance(meters: number | null | undefined): string {
  if (meters == null) return "—";
  return meters < 1000 ? `${Math.round(meters / 10) * 10} m` : `${(meters / 1000).toFixed(1).replace(".", ",")} km`;
}

export function formatEta(minutes: number | null | undefined): string {
  if (minutes == null) return "—";
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

export function ageLabel(seconds: number): string {
  if (seconds < 10) return "à l’instant";
  if (seconds < 60) return `il y a ${seconds} s`;
  return `il y a ${Math.round(seconds / 60)} min`;
}
