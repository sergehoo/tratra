"use client";
import { useCallback, useEffect, useState } from "react";
import { apiErrorMessage, get } from "./api";

/** Chargement d'une ressource GET avec états loading / error / reload (pages du tableau de bord). */
export function useData<T>(path: string | null, fallback = "Les données n’ont pas pu être chargées.") {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    if (!path) return;
    setError("");
    try {
      setData(await get<T>(path));
    } catch (e) {
      setError(apiErrorMessage(e, fallback));
    } finally {
      setLoading(false);
    }
  }, [path, fallback]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, loading, error, reload, setData };
}
