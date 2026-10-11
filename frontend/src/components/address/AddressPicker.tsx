"use client";
import { useEffect, useRef } from "react";
import "leaflet/dist/leaflet.css";

const TILES = process.env.NEXT_PUBLIC_MAP_TILES ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = process.env.NEXT_PUBLIC_MAP_ATTRIBUTION ?? "© contributeurs OpenStreetMap";
const ABIDJAN: [number, number] = [5.36, -4.0083];

/** Carte de sélection : un clic (ou le glissement du repère) choisit le point. Chargée côté navigateur uniquement. */
export function AddressPicker({ value, onPick, className = "" }: { value: { lat: number; lng: number } | null; onPick: (lat: number, lng: number) => void; className?: string }) {
  const node = useRef<HTMLDivElement>(null);
  const ctx = useRef<{ L: typeof import("leaflet"); map: import("leaflet").Map; marker: import("leaflet").Marker | null } | null>(null);
  const pick = useRef(onPick);
  pick.current = onPick;

  useEffect(() => {
    let disposed = false;
    (async () => {
      const L = await import("leaflet");
      if (disposed || !node.current || ctx.current) return;
      const map = L.map(node.current).setView(value ? [value.lat, value.lng] : ABIDJAN, value ? 16 : 12);
      L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
      ctx.current = { L, map, marker: null };
      map.on("click", (e) => pick.current(Number(e.latlng.lat.toFixed(6)), Number(e.latlng.lng.toFixed(6))));
      place();
    })();
    return () => {
      disposed = true;
      ctx.current?.map.remove();
      ctx.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function place() {
    const c = ctx.current;
    if (!c || !value) return;
    const at: [number, number] = [value.lat, value.lng];
    if (c.marker) c.marker.setLatLng(at);
    else {
      // Icône par défaut de Leaflet : ses images ne sont pas résolues par le bundler ; repère dessiné en CSS (comme Tratra Live).
      const icon = c.L.divIcon({ className: "", html: '<span style="display:block;width:22px;height:22px;border-radius:9999px;background:#2E8B57;border:4px solid #F6C90E;box-shadow:0 1px 5px rgba(0,0,0,.45)"></span>', iconSize: [22, 22], iconAnchor: [11, 11] });
      c.marker = c.L.marker(at, { draggable: true, title: "Lieu choisi", icon }).addTo(c.map);
      c.marker.on("dragend", () => {
        const p = c.marker!.getLatLng();
        pick.current(Number(p.lat.toFixed(6)), Number(p.lng.toFixed(6)));
      });
    }
    c.map.setView(at, Math.max(c.map.getZoom(), 16));
  }

  useEffect(place, [value?.lat, value?.lng]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={node} role="application" aria-label="Carte : touchez le lieu exact" className={`h-64 w-full rounded-panel border border-line ${className}`} />;
}
