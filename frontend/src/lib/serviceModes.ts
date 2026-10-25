// Modes d'une offre (ponctuel, récurrent, contractuel) : bornés par les règles du métier, le serveur revalide tout.
export type ServiceMode = "one_off" | "recurring" | "contract";

export const SERVICE_MODES: { id: ServiceMode; label: string; hint: string }[] = [
  { id: "one_off", label: "Ponctuel", hint: "Une intervention réservée par le client." },
  { id: "recurring", label: "Récurrent", hint: "Interventions régulières encadrées par un contrat (ex. ménage chaque semaine)." },
  { id: "contract", label: "Contractuel (mensuel)", hint: "Engagement au mois : nounou, chauffeur, gardien…" },
];

export interface ModeRules { allow_recurring: boolean; allow_long_term: boolean }

/** Modes ouverts par le métier : le ponctuel l'est toujours ; récurrent et contractuel selon la règle du métier. */
export function allowedModes(rules: ModeRules | null): Set<ServiceMode> {
  const out = new Set<ServiceMode>(["one_off"]);
  if (rules?.allow_recurring) out.add("recurring");
  if (rules?.allow_long_term) out.add("contract");
  return out;
}

/** Retire les modes que le métier n'ouvre pas, dans l'ordre canonique ; sans règle connue, rien n'est retiré. */
export function sanitizeModes(modes: ServiceMode[], rules: ModeRules | null): ServiceMode[] {
  const allowed = rules ? allowedModes(rules) : null;
  return SERVICE_MODES.map((m) => m.id).filter((id) => modes.includes(id) && (!allowed || allowed.has(id)));
}

export function modesLabel(modes: string[] | undefined): string {
  return SERVICE_MODES.filter((m) => modes?.includes(m.id)).map((m) => m.label).join(", ");
}
