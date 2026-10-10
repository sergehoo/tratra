"use client";
import { useEffect, useState } from "react";
import { Search, UserRound } from "lucide-react";
import { TextField } from "@/components/ds";
import { eng } from "@/lib/engagements";
import { useDebouncedValue } from "./useDebouncedValue";

export interface PickedWorker { id: number; name: string; commune: string }

/** Recherche d'un professionnel VÉRIFIÉ par son nom (le serveur ne renvoie que nom public, commune et identifiant). */
export function WorkerPicker({ label = "Professionnel", onPick, picked }: { label?: string; onPick: (w: PickedWorker | null) => void; picked: PickedWorker | null }) {
  const [q, setQ] = useState("");
  const dq = useDebouncedValue(q.trim());
  const [rows, setRows] = useState<PickedWorker[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  useEffect(() => {
    if (dq.length < 2) {
      setRows([]);
      setState("idle");
      return;
    }
    let alive = true;
    setState("loading");
    eng.get<{ results: PickedWorker[] }>(`/workers/?q=${encodeURIComponent(dq)}`)
      .then((r) => { if (alive) { setRows(r.results); setState("idle"); } })
      .catch(() => { if (alive) setState("error"); });
    return () => { alive = false; };
  }, [dq]);

  if (picked) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-panel border border-primary/20 bg-primarySoft/50 p-3 text-sm">
        <span className="inline-flex min-w-0 items-center gap-2 font-semibold text-ink"><UserRound aria-hidden className="h-4 w-4 text-primary" /><span className="truncate">{picked.name}{picked.commune ? ` · ${picked.commune}` : ""}</span></span>
        <button type="button" className="shrink-0 text-sm font-semibold text-primaryDark underline underline-offset-2" onClick={() => onPick(null)}>Changer</button>
      </div>
    );
  }
  return (
    <div>
      <TextField label={label} type="search" value={q} onChange={(e) => setQ(e.target.value)} leading={<Search className="h-4 w-4" />} placeholder="Prénom ou nom (2 lettres minimum)"
        hint="Seuls les professionnels vérifiés par Tratra apparaissent." />
      {state === "error" ? <p role="alert" className="mt-2 text-xs font-medium text-dangerInk">Recherche indisponible. Réessayez.</p> : null}
      {state === "loading" ? <p role="status" className="mt-2 text-xs text-ash">Recherche…</p> : null}
      {dq.length >= 2 && state === "idle" && rows.length === 0 ? <p className="mt-2 text-xs text-ash">Aucun professionnel vérifié ne correspond.</p> : null}
      {rows.length > 0 ? (
        <ul className="mt-2 divide-y divide-lineSoft rounded-panel border border-lineSoft bg-white">
          {rows.map((w) => (
            <li key={w.id}>
              <button type="button" onClick={() => onPick(w)} className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left text-sm hover:bg-lineSoft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                <span className="font-semibold text-ink">{w.name}</span>
                <span className="text-xs text-ash">{w.commune}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
