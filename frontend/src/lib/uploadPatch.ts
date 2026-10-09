import { ApiError, get, tokens } from "./api";
import { API_BASE } from "./config";

/** PATCH multipart (ex. photo de profil) — `upload()` de api.ts ne fait que des POST. */
export async function patchForm<T>(path: string, form: FormData): Promise<T> {
  // Un GET authentifié rafraîchit au besoin le jeton d'accès avant l'envoi.
  await get("/users/me/").catch(() => null);
  const access = tokens.access;
  const res = await fetch(`${API_BASE}${path.startsWith("/") ? path : `/${path}`}`, {
    method: "PATCH",
    headers: access ? { Authorization: `Bearer ${access}` } : {},
    body: form,
    cache: "no-store",
    credentials: "omit",
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}
