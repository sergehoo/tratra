export type ClassValue = string | number | bigint | boolean | null | undefined;

/** Concatène des classes en ignorant les valeurs falsy (pas de dépendance externe). */
export function cx(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
