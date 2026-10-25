"use client";
import { useEffect, useState } from "react";
import { Checkbox } from "@/components/ds";
import { eng } from "@/lib/engagements";
import { SERVICE_MODES, allowedModes, sanitizeModes, type ModeRules, type ServiceMode } from "@/lib/serviceModes";

/** Règle du métier choisi (récurrent / contractuel ouverts ou non) — lue sur le serveur, jamais supposée. */
export function useModeRules(categoryId: string | number | null | undefined): ModeRules | null {
  const [rules, setRules] = useState<ModeRules | null>(null);
  useEffect(() => {
    setRules(null);
    if (!categoryId) return;
    let alive = true;
    eng.get<ModeRules>(`/rules/?category=${encodeURIComponent(String(categoryId))}`)
      .then((r) => { if (alive) setRules(r); })
      .catch(() => { if (alive) setRules({ allow_recurring: false, allow_long_term: false }); });
    return () => { alive = false; };
  }, [categoryId]);
  return rules;
}

/** Cases « Ponctuel / Récurrent / Contractuel (mensuel) » ; un mode que le métier n'ouvre pas est grisé et retiré. */
export function ServiceModesField({ value, onChange, rules, error, disabled }: {
  value: ServiceMode[]; onChange: (v: ServiceMode[]) => void; rules: ModeRules | null; error?: string; disabled?: boolean;
}) {
  const allowed = allowedModes(rules);
  useEffect(() => {
    if (!rules) return;
    const next = sanitizeModes(value, rules);
    if (next.length !== value.length) onChange(next.length ? next : ["one_off"]);
  }, [rules, value, onChange]);
  return (
    <fieldset className="space-y-3 rounded-panel border border-lineSoft p-4" disabled={disabled}>
      <legend className="px-1 text-sm font-semibold text-ink">Modes proposés</legend>
      {SERVICE_MODES.map((m) => {
        const open = allowed.has(m.id);
        return (
          <Checkbox key={m.id} checked={value.includes(m.id)} disabled={disabled || (rules !== null && !open)}
            onChange={(e) => onChange(sanitizeModes(e.target.checked ? [...value, m.id] : value.filter((x) => x !== m.id), rules))}
            label={<><span className="font-semibold text-ink">{m.label}</span> — {m.hint}{rules && !open ? " (non ouvert pour ce métier)" : ""}</>} />
        );
      })}
      {error ? <p role="alert" className="text-xs font-medium text-dangerInk">{error}</p> : null}
    </fieldset>
  );
}
