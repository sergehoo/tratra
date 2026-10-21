"use client";
import { useEffect, useId, useRef, useState } from "react";
import { Bookmark, Crosshair, Loader2, MapPin } from "lucide-react";
import { Input } from "@/components/ds";
import { currentPosition, listAddresses, reverseAddress, searchAddress, type Address, type Suggestion } from "@/lib/addresses";

/** Adresse retenue : libellé, commune ou quartier, ville, position (si connue) et origine. */
export interface AddressPick {
  label: string;
  commune: string;
  city: string;
  lat: number | null;
  lng: number | null;
  source: "manual" | "saved" | "geocoder" | "device";
}

function fromSuggestion(s: Pick<Suggestion, "street" | "commune" | "city" | "latitude" | "longitude"> & { label?: string }, source: AddressPick["source"]): AddressPick {
  const label = [s.street, s.commune, s.city].filter(Boolean).join(", ") || s.label || "";
  return { label, commune: s.commune || "", city: s.city || "", lat: s.latitude ?? null, lng: s.longitude ?? null, source };
}

/**
 * Adresse d'intervention : mes adresses enregistrées d'abord, puis les suggestions du service d'adresses du serveur (communes, quartiers,
 * rues — fournisseur configurable : OpenStreetMap ou Google Maps avec une clé), et « Utiliser ma position actuelle » (une lecture, à la demande).
 * Saisie libre toujours acceptée ; navigation au clavier (flèches, Entrée, Échap).
 */
export function AddressAutocomplete({ onChange, label = "Adresse de l’intervention", hint }: { onChange: (pick: AddressPick | null) => void; label?: string; hint?: string }) {
  const id = useId();
  const [text, setText] = useState("");
  const [saved, setSaved] = useState<Address[]>([]);
  const [results, setResults] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [locating, setLocating] = useState(false);
  const [notice, setNotice] = useState("");
  const [picked, setPicked] = useState<AddressPick | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    listAddresses().then((r) => setSaved(r.results ?? [])).catch(() => setSaved([]));
  }, []);

  useEffect(() => {
    const q = text.trim();
    if (picked || q.length < 3) {
      setResults([]);
      return;
    }
    const mine = ++seq.current;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const r = await searchAddress(q);
        if (mine !== seq.current) return;
        setResults(r.results);
        setNotice(r.manual ? "Suggestions indisponibles : saisissez l’adresse et la commune." : "");
      } catch {
        if (mine === seq.current) setNotice("Suggestions indisponibles : saisissez l’adresse et la commune.");
      } finally {
        if (mine === seq.current) setBusy(false);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [text, picked]);

  const q = text.trim().toLowerCase();
  const savedShown = picked ? [] : saved.filter((a) => !q || `${a.label} ${a.street} ${a.commune}`.toLowerCase().includes(q)).slice(0, 3);
  const options: { key: string; pick: AddressPick; title: string; sub: string; saved: boolean }[] = [
    ...savedShown.map((a) => ({ key: `s${a.id}`, saved: true, title: a.label || a.street || a.commune, sub: [a.street, a.commune].filter(Boolean).join(", "),
      pick: fromSuggestion({ street: a.street, commune: a.commune, city: a.city, latitude: a.latitude ?? (null as unknown as number), longitude: a.longitude ?? (null as unknown as number) }, "saved") })),
    ...results.map((r, i) => ({ key: `g${i}`, saved: false, title: [r.street, r.commune].filter(Boolean).join(", ") || r.label, sub: r.city, pick: fromSuggestion(r, "geocoder") })),
  ];

  function choose(pick: AddressPick) {
    setPicked(pick);
    setText(pick.label);
    setOpen(false);
    setNotice("");
    onChange(pick);
  }

  async function useMyPosition() {
    setLocating(true);
    setNotice("");
    try {
      const p = await currentPosition();
      const found = await reverseAddress(p.lat, p.lng).catch(() => null);
      if (found) choose(fromSuggestion(found, "device"));
      else {
        choose({ label: text.trim() || "Ma position actuelle", commune: "", city: "", lat: p.lat, lng: p.lng, source: "device" });
        setNotice("Position enregistrée ; précisez la rue ou un repère si besoin.");
      }
    } catch {
      setNotice("Position indisponible ou refusée : saisissez l’adresse.");
    } finally {
      setLocating(false);
    }
  }

  return (
    <div className="relative">
      <label htmlFor={id} className="block text-sm font-semibold text-ink">{label} <span className="text-danger" aria-hidden>*</span></label>
      <div className="mt-1.5">
        <Input
          id={id}
          role="combobox"
          aria-expanded={open && options.length > 0}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          autoComplete="off"
          placeholder="Commune, quartier, rue…"
          leading={<MapPin aria-hidden className="h-4 w-4" />}
          trailing={busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : undefined}
          value={text}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onChange={(e) => {
            setText(e.target.value);
            setPicked(null);
            setOpen(true);
            setActive(-1);
            onChange(e.target.value.trim() ? { label: e.target.value.trim(), commune: "", city: "", lat: null, lng: null, source: "manual" } : null);
          }}
          onKeyDown={(e) => {
            if (!options.length) return;
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(options.length - 1, a + 1)); setOpen(true); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(options[active].pick); }
            if (e.key === "Escape") setOpen(false);
          }}
        />
      </div>
      {hint ? <p className="mt-1 text-xs text-ash">{hint}</p> : null}
      {open && options.length ? (
        <ul id={`${id}-list`} role="listbox" className="absolute z-20 mt-1 w-full overflow-hidden rounded-panel border border-line bg-white shadow-strong">
          {options.map((o, i) => (
            <li key={o.key} role="option" aria-selected={i === active}>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => choose(o.pick)}
                className={`flex w-full items-start gap-3 px-4 py-2.5 text-left text-sm hover:bg-primarySoft ${i === active ? "bg-primarySoft" : ""}`}>
                {o.saved ? <Bookmark aria-hidden className="mt-0.5 h-4 w-4 text-primary" /> : <MapPin aria-hidden className="mt-0.5 h-4 w-4 text-ash" />}
                <span className="min-w-0"><span className="block font-semibold text-ink">{o.title}</span>{o.sub ? <span className="block text-xs text-ash">{o.sub}</span> : null}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <button type="button" onClick={() => void useMyPosition()} disabled={locating}
        className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-primaryDark hover:underline disabled:opacity-60">
        <Crosshair aria-hidden className="h-4 w-4" />{locating ? "Localisation…" : picked?.source === "device" ? "Position utilisée" : "Utiliser ma position actuelle"}
      </button>
      {notice ? <p role="status" className="mt-1 text-xs text-warningInk">{notice}</p> : null}
    </div>
  );
}
