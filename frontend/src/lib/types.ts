export type UserType = "client" | "employeur" | "handyman" | "entreprise" | "admin";

export interface User {
  id: number;
  username: string;
  email: string;
  first_name?: string;
  last_name?: string;
  user_type: UserType;
  phone?: string | null;
  is_verified?: boolean;
}

export interface Category {
  id: number;
  name: string;
  slug: string;
  description?: string | null;
  icon?: string | null;
}

export interface Service {
  id: number;
  title: string;
  description?: string;
  price?: string | number | null;
  price_type?: string;
  category?: number | null;
  handyman?: number | null;
  category_detail?: Category | null;
  handyman_detail?: (Partial<User> & { id?: number }) | null;
  banner?: string | null;
}

export interface Booking {
  id: number;
  status: "pending" | "confirmed" | "in_progress" | "completed" | "cancelled";
  type?: "instant" | "scheduled";
  booking_date?: string;
  address?: string;
  city?: string;
  service_detail?: Service | null;
  client_detail?: Partial<User> | null;
  handyman_detail?: Partial<User> | null;
  proposed_price?: string | number | null;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface HandymanDocument {
  id: number;
  document_type: string;
  download_url?: string | null;
  status: "pending" | "approved" | "rejected";
  rejection_reason?: string | null;
  uploaded_at: string;
  handyman_detail?: { user_detail?: Partial<User> } | null;
}

export interface Dispute {
  id: number;
  booking: number;
  reason: string;
  status: "open" | "under_review" | "resolved" | "rejected";
  resolution?: string | null;
  resolution_action?: string;
  created_at: string;
  reporter_detail?: Partial<User> | null;
}

export interface SubscriptionPlan {
  id: number;
  name: string;
  slug: string;
  audience: string;
  price: string;
  interval: string;
  features: string[];
  active: boolean;
}

export interface ReplacementSuggestion {
  id: number;
  score: number;
  accepted: boolean;
  suggested_service_detail?: Service | null;
}
