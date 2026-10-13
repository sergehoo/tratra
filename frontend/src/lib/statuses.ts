/** Statuts éphémères : types de l'API (mêmes charges utiles que le mobile) et petits utilitaires de média. */
export type StatusType = "text" | "photo" | "video" | "text_media";

export interface StatusMedia {
  url: string | null;
  mime: string;
  size: number;
  width?: number;
  height?: number;
  duration?: number;
}

export interface StatusItem {
  id: number;
  type: StatusType;
  kind: "text" | "photo" | "video";
  text: string;
  background: string | null;
  media: StatusMedia | null;
  created_at: string;
  expires_at: string;
  audience: "contacts" | "extended" | null;
  allow_replies: boolean;
  mine: boolean;
  seen?: boolean;
  /** Réservé à l'auteur : compteurs de vues. */
  views?: { unique: number; total: number };
}

export interface StatusAuthor {
  id: number;
  name: string;
  avatar: string | null;
}

export interface StatusGroup {
  author: StatusAuthor;
  statuses: StatusItem[];
  unseen: number;
  seen: boolean;
  latest_at: string;
}

export interface StatusLimits {
  ttl_hours: number;
  text_max: number;
  video_max_seconds: number;
  image_max_bytes: number;
  video_max_bytes: number;
  max_active: number;
  repeat_views: boolean;
  backgrounds: string[];
}

export interface StatusFeed {
  mine: { author: StatusAuthor; statuses: StatusItem[]; count: number };
  contacts: StatusGroup[];
  discover_count: number;
  limits: StatusLimits;
}

export interface StatusViewer {
  user: StatusAuthor;
  viewed_at: string;
  last_viewed_at?: string;
  count?: number;
}

export const BACKGROUNDS: Record<string, { bg: string; fg: string; label: string }> = {
  green: { bg: "#2e8b57", fg: "#ffffff", label: "Vert" },
  yellow: { bg: "#f5c400", fg: "#111111", label: "Jaune" },
  night: { bg: "#10201a", fg: "#ffffff", label: "Nuit" },
  sky: { bg: "#2b6cb0", fg: "#ffffff", label: "Bleu" },
  rose: { bg: "#c2410c", fg: "#ffffff", label: "Orange" },
  violet: { bg: "#6b46c1", fg: "#ffffff", label: "Violet" },
};

/** Compression côté client avant l'envoi (le serveur réencode de toute façon et retire les métadonnées). */
export async function compressImage(file: File, maxSide = 1600, quality = 0.82): Promise<File> {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/jpeg", quality));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return file;
  }
}

/** Durée réelle d'une vidéo (secondes) lue dans le navigateur, pour refuser tôt une vidéo trop longue. */
export function videoDuration(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const v = document.createElement("video");
    v.preload = "metadata";
    v.onloadedmetadata = () => {
      URL.revokeObjectURL(url);
      resolve(v.duration);
    };
    v.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("unreadable"));
    };
    v.src = url;
  });
}

export function newClientId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      });
}

export function timeLeft(expiresAt: string): string {
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return "expiré";
  const h = Math.floor(ms / 3_600_000);
  return h >= 1 ? `${h} h` : `${Math.max(1, Math.round(ms / 60_000))} min`;
}
