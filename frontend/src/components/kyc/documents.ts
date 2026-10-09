import { DURATION } from "@/components/ds";
import { ApiError, apiErrorMessage } from "@/lib/api";

/**
 * Utilitaires d'affichage de la surface KYC (dépôt artisan, revue admin).
 * Aucune règle métier ici : libellés, formats et mise en forme uniquement.
 */

/** Types que l'artisan peut déposer — `value` est la valeur exacte attendue par l'API (`document_type`). */
export const DOC_TYPES = [
  { value: "id_card", label: "Pièce d’identité" },
  { value: "license", label: "Permis" },
  { value: "casier", label: "Casier judiciaire" },
  { value: "insurance", label: "Assurance" },
  { value: "certification", label: "Certificat / diplôme" },
] as const;

/** Libellés d'affichage : inclut `other`, type existant côté serveur mais non proposé au dépôt. */
const TYPE_LABEL: Record<string, string> = {
  ...Object.fromEntries(DOC_TYPES.map((t) => [t.value, t.label])),
  other: "Autre document",
};

export function documentTypeLabel(value: string | null | undefined): string {
  return (value && TYPE_LABEL[value]) || "Document";
}

/** Attribut `accept` du champ fichier : formats réellement acceptés par l'API (PDF, JPEG, PNG). */
export const KYC_ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";
/** Taille maximale annoncée : valeur par défaut de KYC_MAX_UPLOAD_BYTES côté serveur (10 Mo). */
export const KYC_MAX_MB = 10;

const SENT = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });

/** « 8 octobre 2026 » ; `null` si la date est absente ou invalide. */
export function formatSentDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : SENT.format(date);
}

/** Taille lisible (o, Ko, Mo) ; chaîne vide si la valeur est invalide. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`;
  return `${(bytes / (1024 * 1024)).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Mo`;
}

const STAGGER = DURATION.fast / 3;

/** Délai d'apparition échelonné (classe `animate-rise`), plafonné aux 7 premiers éléments. */
export function riseDelay(index: number): { animationDelay: string } {
  return { animationDelay: `${Math.min(index, 6) * STAGGER}s` };
}

/**
 * Message d'erreur affichable : celui du serveur quand l'API a répondu en JSON,
 * sinon le texte par défaut (ex. page HTML d'un proxy ou d'une erreur 500).
 */
export function kycErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && typeof error.data === "string") return fallback;
  return apiErrorMessage(error, fallback);
}
