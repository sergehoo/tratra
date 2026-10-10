"use client";
import { useEffect, useRef } from "react";
import "leaflet/dist/leaflet.css";
import type { LivePosition } from "@/lib/live";

const TILES = process.env.NEXT_PUBLIC_MAP_TILES ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = process.env.NEXT_PUBLIC_MAP_ATTRIBUTION ?? "© contributeurs OpenStreetMap";

interface Props {
  artisan?: LivePosition | null;
  client?: LivePosition | null;
  destination?: { lat: number; lng: number } | null;
  route?: [number, number][] | null;
  className?: string;
}

const dot = (color: string, ring: string, label: string) =>
  `<span aria-label="${label}" style="display:block;width:18px;height:18px;border-radius:9999px;background:${color};border:3px solid ${ring};box-shadow:0 1px 4px rgba(0,0,0,.45)"></span>`;

/**
 * Carte interactive (Leaflet, chargée côté navigateur uniquement) : artisan, client (s'il partage sa position),
 * lieu d'intervention et itinéraire réels. Aucun marqueur n'est affiché sans position reçue du serveur.
 */
export function LiveMap({ artisan, client, destination, route, className = "" }: Props) {
  const node = useRef<HTMLDivElement>(null);
  const ctx = useRef<{ L: typeof import("leaflet"); map: import("leaflet").Map; layer: import("leaflet").LayerGroup; fitted: boolean } | null>(null);

  // Création unique de la carte
  useEffect(() => {
    let disposed = false;
    (async () => {
      const L = await import("leaflet");
      if (disposed || !node.current || ctx.current) return;
      const map = L.map(node.current, { zoomControl: true, attributionControl: true }).setView([5.36, -4.0083], 12);
      L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
      ctx.current = { L, map, layer: L.layerGroup().addTo(map), fitted: false };
      draw();
    })();
    return () => {
      disposed = true;
      ctx.current?.map.remove();
      ctx.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function draw() {
    const c = ctx.current;
    if (!c) return;
    const { L, map, layer } = c;
    layer.clearLayers();
    const points: [number, number][] = [];
    if (route && route.length > 1) {
      L.polyline(route, { color: "#2E8B57", weight: 5, opacity: 0.85 }).addTo(layer);
      points.push(...route);
    }
    if (destination) {
      L.marker([destination.lat, destination.lng], {
        icon: L.divIcon({ className: "", html: dot("#0B1210", "#F6C90E", "Lieu d’intervention"), iconSize: [18, 18], iconAnchor: [9, 9] }),
        title: "Lieu d’intervention",
      }).addTo(layer);
      points.push([destination.lat, destination.lng]);
    }
    if (client) {
      L.marker([client.lat, client.lng], {
        icon: L.divIcon({ className: "", html: dot("#F6C90E", "#ffffff", "Client"), iconSize: [18, 18], iconAnchor: [9, 9] }),
        title: "Client",
      }).addTo(layer);
      points.push([client.lat, client.lng]);
    }
    if (artisan) {
      L.marker([artisan.lat, artisan.lng], {
        icon: L.divIcon({ className: "", html: dot(artisan.stale ? "#94A3B8" : "#2E8B57", "#ffffff", "Artisan"), iconSize: [18, 18], iconAnchor: [9, 9] }),
        title: "Artisan",
      }).addTo(layer);
      if (artisan.accuracy && artisan.accuracy < 500) {
        L.circle([artisan.lat, artisan.lng], { radius: artisan.accuracy, color: "#2E8B57", weight: 1, fillOpacity: 0.08 }).addTo(layer);
      }
      points.push([artisan.lat, artisan.lng]);
    }
    // Cadrage automatique au premier rendu avec des points, puis à chaque nouveau jeu de repères (pas à chaque tic).
    if (points.length) {
      map.fitBounds(L.latLngBounds(points), { padding: [36, 36], maxZoom: 16, animate: c.fitted });
      c.fitted = true;
    }
  }

  const key = JSON.stringify([artisan && [artisan.lat, artisan.lng, artisan.stale], client && [client.lat, client.lng], destination, route?.length]);
  useEffect(draw, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={node} role="region" aria-label="Carte du suivi en direct" className={`z-0 h-72 w-full overflow-hidden rounded-panel border border-lineSoft ${className}`} />;
}
