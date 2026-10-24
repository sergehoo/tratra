import { publicUrl } from "@/lib/public";

/** Vérification publique d'un document de contrat Tratra : aucune donnée personnelle n'est jamais renvoyée. */
export type ContractDocState = "authentic" | "superseded" | "revoked" | "altered" | "invalid_signature" | "key_revoked" | "unknown";

export interface ContractVerification {
  state: ContractDocState;
  label: string;
  match?: boolean;
  reference?: string;
  kind?: "contract" | "amendment";
  stage?: "for_signature" | "final";
  version?: number;
  issued_at?: string;
  sha256?: string;
  revoked_at?: string | null;
  nature?: string;
  contract_status?: string;
  superseded_by?: string | null;
  /** Scellement de la plateforme (Ed25519) — distinct des signatures électroniques simples des parties. */
  seal?: { valid: boolean; kid: string; algorithm: string; key_status: string; payload: Record<string, unknown>; signature: string };
  parties_signed?: boolean;
  amendments?: { reference: string; issued_at: string; sha256: string; revoked: boolean }[];
  detail?: string;
}

const JSON_HEADERS = { Accept: "application/json" };

export async function verifyContractToken(token: string, signal?: AbortSignal): Promise<ContractVerification | null> {
  const r = await fetch(publicUrl(`/public/contracts/verify/${encodeURIComponent(token)}/`), {
    headers: JSON_HEADERS, credentials: "omit", cache: "no-store", signal,
  });
  // 200 (connu) et 404 (inconnu) portent la même forme de réponse.
  return r.status === 200 || r.status === 404 ? ((await r.json()) as ContractVerification) : null;
}

export async function verifyContractFile(file: File): Promise<ContractVerification | null> {
  const body = new FormData();
  body.append("file", file);
  const r = await fetch(publicUrl("/public/contracts/verify-file/"), { method: "POST", body, headers: JSON_HEADERS, credentials: "omit" });
  return r.ok || r.status === 400 ? ((await r.json()) as ContractVerification) : null;
}
