"use client";
import { TextField } from "@/components/ds";
import { DEFAULT_COUNTRY_PREFIX } from "@/lib/phone";

/** Valeur initiale d'un champ téléphone : l'indicatif par défaut est déjà saisi. */
export const PHONE_INITIAL = `${DEFAULT_COUNTRY_PREFIX} `;

/**
 * Champ « Téléphone » du compte unique : +225 par défaut, format international (E.164).
 * Le numéro est normalisé côté serveur (lib/phone.ts reprend la même règle pour valider avant envoi).
 */
export function PhoneField({
  value,
  onChange,
  error,
  label = "Téléphone",
  hint = "Avec l’indicatif du pays : +225 pour la Côte d’Ivoire.",
  autoFocus,
  name = "phone",
}: {
  value: string;
  onChange: (value: string) => void;
  error?: string;
  label?: string;
  hint?: string;
  autoFocus?: boolean;
  name?: string;
}) {
  return (
    <TextField
      label={label}
      required
      name={name}
      type="tel"
      autoComplete="tel"
      inputMode="tel"
      placeholder="+225 07 00 00 00 00"
      autoFocus={autoFocus}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      error={error}
      hint={hint}
    />
  );
}
