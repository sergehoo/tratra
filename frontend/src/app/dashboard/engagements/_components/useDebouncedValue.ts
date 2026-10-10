"use client";
import { useEffect, useState } from "react";

/** Valeur « débattue » (saisie de recherche) : évite une requête par frappe. */
export function useDebouncedValue<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
