"use client";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

const MIN_INTERVAL_MS = 5000; // une position toutes les 5 s au plus

export type GeoStatus = "idle" | "waiting" | "sharing" | "denied" | "unavailable";

/**
 * Partage la position de l'appareil (watchPosition) tant que `active` : une mesure toutes les 5 s, envoyée à
 * l'API via `send`. Gère le refus du GPS (`denied`), l'absence de signal (`unavailable`) et les échecs réseau
 * (la position suivante repart : le serveur ignore de toute façon les mesures trop anciennes).
 */
export function useGeoShare(active: boolean, send: (payload: Record<string, unknown>) => Promise<unknown>) {
  const [status, setStatus] = useState<GeoStatus>("idle");
  const [lastError, setLastError] = useState("");
  const last = useRef(0);
  const sendRef = useRef(send);
  sendRef.current = send;

  useEffect(() => {
    if (!active) {
      setStatus("idle");
      return;
    }
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setStatus("unavailable");
      return;
    }
    setStatus("waiting");
    const id = navigator.geolocation.watchPosition(
      (pos) => {
        const now = Date.now();
        if (now - last.current < MIN_INTERVAL_MS) return;
        last.current = now;
        const c = pos.coords;
        const payload: Record<string, unknown> = {
          lat: c.latitude,
          lng: c.longitude,
          accuracy: c.accuracy,
          captured_at: new Date(pos.timestamp).toISOString(),
        };
        if (c.speed != null && c.speed >= 0) payload.speed = c.speed;
        if (c.heading != null && c.heading >= 0) payload.heading = c.heading;
        sendRef.current(payload)
          .then(() => {
            setStatus("sharing");
            setLastError("");
          })
          .catch((e) => {
            // 409/429 : le serveur refuse (partage arrêté, trop fréquent) ; autre : réseau — on réessaie à la mesure suivante.
            setLastError(e instanceof ApiError ? "Le serveur a refusé la position." : "Connexion perdue : la position reprendra automatiquement.");
          });
      },
      (err) => setStatus(err.code === err.PERMISSION_DENIED ? "denied" : "unavailable"),
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [active]);

  return { status, lastError };
}
