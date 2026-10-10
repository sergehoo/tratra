export type UserType = "client" | "employeur" | "handyman" | "entreprise" | "admin";

export interface User {
  id: number;
  /** Identifiant technique hérité (jamais saisi ni affiché : connexion par téléphone). */
  username: string;
  /** Facultatif : renseigné après connexion. */
  email: string | null;
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
  is_active?: boolean;
  parent?: number | null;
  /** Nombre de services actifs — présent uniquement sur la liste /categories/. */
  services_count?: number | null;
}

export type PriceType = "hourly" | "fixed" | "quote";

/**
 * Identité publique minimale d'un artisan (`Service.handyman_detail`) :
 * jamais le nom complet, l'email, le rôle ni l'état de vérification du compte.
 */
export interface PublicUserMini {
  id: number;
  first_name: string;
  /** « Prénom N. » (ou « Membre Tratra »). */
  display_name: string;
}

/** Résumé public d'un artisan embarqué dans un service (aucune donnée sensible). */
export interface PublicArtisanMini {
  id: number;
  display_name: string;
  commune?: string | null;
  rating: number;
  completed_jobs: number;
  experience_years: number;
  is_verified: boolean;
  online: boolean;
  photo?: string | null;
  /** Tratra Trust : score expliqué (null tant que l'activité mesurée est insuffisante) et badges actuels. */
  trust_score?: number | null;
  badges?: { code: "NOUVEAU" | "VERIFIE" | "EXPERT" | "SUR"; label: string }[];
}

/** Carte artisan publique (GET /handymen/featured/). */
export interface PublicArtisan extends PublicArtisanMini {
  user_id: number;
  quartier?: string | null;
  hourly_rate?: string | number | null;
  skills: { id: number; name: string; slug: string }[];
  /** Nombre de prestations ACTIVES publiées par l'artisan. */
  services_count?: number;
}

export interface FeaturedArtisansResponse {
  count: number;
  results: PublicArtisan[];
}

/** Avis publié (GET /reviews/public/) — auteur affiché « Prénom N. ». */
export interface PublicReview {
  id: number;
  rating: number;
  comment: string;
  author: string;
  artisan: string;
  category?: string | null;
  created_at: string;
}

export interface PublicReviewsResponse {
  count: number;
  average: number | null;
  results: PublicReview[];
}

/** Chiffres réels de la plateforme (GET /public/stats/). */
export interface PublicStats {
  categories: number;
  services: number;
  artisans_verified: number;
  artisans_online: number;
  missions_completed: number;
  reviews_count: number;
  rating_average: number | null;
}

export interface ServiceImage {
  id: number;
  image?: string | null;
  alt_text?: string | null;
}

export interface Service {
  id: number;
  title: string;
  description?: string;
  price?: string | number | null;
  price_type?: PriceType | string;
  duration?: number | null;
  category?: number | null;
  handyman?: number | null;
  category_detail?: Category | null;
  handyman_detail?: PublicUserMini | null;
  /** Profil public de l'artisan (note, commune, vérifié, en ligne). */
  artisan?: PublicArtisanMini | null;
  /** Distance en km — présent uniquement sur /services/nearby/. */
  distance_km?: number | null;
  banner?: string | null;
  image_url?: string | null;
  images?: ServiceImage[];
  is_active?: boolean;
  created_at?: string;
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
