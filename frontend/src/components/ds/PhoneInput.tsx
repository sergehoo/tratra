"use client";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { cx } from "./cx";
import { CONTROL, Field } from "./Field";
import { Modal } from "./Modal";
import {
  allCountries, countryName, exampleNational, flagOf, formatNational, searchCountries, splitInternational,
  type CountryCode, type PhoneValue,
} from "@/lib/phone";
import { rememberCountry, resolveDefaultCountry } from "@/lib/phoneCountry";

/**
 * Saisie du téléphone : [drapeau ▼] [numéro national]. Le pays se choisit dans une liste avec recherche (nom, code, indicatif) ;
 * l'utilisateur ne tape jamais l'indicatif. Coller un numéro complet (« +33 6… ») change le pays automatiquement.
 * `autoCountry` : le pays de départ est déduit (préférence, appareil, IP connue, Côte d'Ivoire) tant que rien n'a été saisi.
 */
export function PhoneInput({
  id,
  value,
  onChange,
  invalid,
  autoFocus,
  autoCountry = true,
  name = "phone",
  autoComplete = "tel-national",
  disabled,
  ...aria
}: {
  id?: string;
  autoComplete?: string;
  value: PhoneValue;
  onChange: (value: PhoneValue) => void;
  invalid?: boolean;
  autoFocus?: boolean;
  autoCountry?: boolean;
  name?: string;
  disabled?: boolean;
  "aria-describedby"?: string;
  "aria-required"?: true;
}) {
  const [open, setOpen] = useState(false);
  const touched = useRef(false);
  const latest = useRef(value);
  latest.current = value;
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!autoCountry) return;
    let alive = true;
    void resolveDefaultCountry().then((country) => {
      const v = latest.current;
      if (alive && !touched.current && !v.national && country !== v.country) onChange({ ...v, country });
    });
    return () => {
      alive = false;
    };
  }, []);

  const pick = (country: CountryCode) => {
    touched.current = true;
    rememberCountry(country);
    onChange({ country, national: formatNational(latest.current.national, country) });
    setOpen(false);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const type = (raw: string) => {
    touched.current = true;
    const pasted = splitInternational(raw);
    if (pasted) {
      rememberCountry(pasted.country);
      onChange(pasted);
      return;
    }
    if (/^\s*(\+|00)/.test(raw)) {
      // Indicatif en cours de saisie (« +3… ») : gardé tel quel jusqu'à ce que le pays soit reconnu, puis le pays change tout seul.
      onChange({ ...latest.current, national: raw.replace(/[^\d+ ]/g, "") });
      return;
    }
    onChange({ ...latest.current, national: formatNational(raw, latest.current.country) });
  };

  const name_ = countryName(value.country);
  const dial = useMemo(() => allCountries().find((c) => c.code === value.country)?.dial ?? "", [value.country]);
  return (
    <div className="flex gap-2">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Pays : ${name_}, indicatif +${dial}. Changer de pays`}
        className={cx(
          "flex min-h-[48px] shrink-0 items-center gap-1.5 rounded-control border bg-white px-3 text-[15px] font-semibold text-ink outline-none transition duration-200",
          "hover:border-fog focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-primary/15 disabled:cursor-not-allowed disabled:bg-canvas disabled:text-ash",
          invalid ? "border-danger" : "border-line",
        )}
      >
        <span aria-hidden className="text-xl leading-none">{flagOf(value.country)}</span>
        <span className="tabular-nums">+{dial}</span>
        <ChevronDown aria-hidden className="h-4 w-4 text-ash" />
      </button>
      <input
        ref={inputRef}
        id={id}
        name={name}
        type="tel"
        inputMode="tel"
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        disabled={disabled}
        placeholder={exampleNational(value.country)}
        value={value.national}
        onChange={(e) => type(e.target.value)}
        aria-invalid={invalid || undefined}
        aria-describedby={aria["aria-describedby"]}
        aria-required={aria["aria-required"]}
        className={cx(CONTROL, "min-h-[48px] min-w-0 flex-1 px-4 tabular-nums")}
      />
      <CountryPicker open={open} current={value.country} onClose={() => setOpen(false)} onPick={pick} />
    </div>
  );
}

function CountryPicker({ open, current, onClose, onPick }: { open: boolean; current: CountryCode; onClose: () => void; onPick: (c: CountryCode) => void }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const results = useMemo(() => {
    const found = searchCountries(query);
    if (query) return found;
    const head = found.filter((c) => c.code === current || c.code === "CI");     // pays actuel et Côte d'Ivoire en tête
    return [...head, ...found.filter((c) => c.code !== current && c.code !== "CI")];
  }, [query, current]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
    }
  }, [open]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && results[active]) {
      e.preventDefault();
      onPick(results[active].code);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Choisir le pays" description="L’indicatif est ajouté automatiquement : saisissez ensuite votre numéro sans lui.">
      <div className="relative">
        <Search aria-hidden className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fog" />
        <input
          type="search"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKey}
          placeholder="Pays ou indicatif (ex. Sénégal, +221)"
          aria-label="Rechercher un pays ou un indicatif"
          aria-controls={listId}
          aria-activedescendant={results[active] ? `${listId}-${results[active].code}` : undefined}
          className={cx(CONTROL, "min-h-[48px] pl-10 pr-4")}
        />
      </div>
      <p className="sr-only" role="status" aria-live="polite">{results.length} pays</p>
      <ul ref={listRef} id={listId} role="listbox" aria-label="Pays" className="mt-3 max-h-[55vh] overflow-y-auto overscroll-contain sm:max-h-80">
        {results.length === 0 ? <li className="px-3 py-6 text-center text-sm text-ash">Aucun pays ne correspond à « {query} ».</li> : null}
        {results.map((c, i) => (
          <li
            key={c.code}
            id={`${listId}-${c.code}`}
            role="option"
            aria-selected={c.code === current}
            data-index={i}
            onClick={() => onPick(c.code)}
            onMouseEnter={() => setActive(i)}
            className={cx(
              "flex min-h-[48px] cursor-pointer items-center gap-3 rounded-xl px-3 text-[15px]",
              i === active ? "bg-primarySoft" : "hover:bg-canvas",
            )}
          >
            <span aria-hidden className="text-xl leading-none">{c.flag}</span>
            <span className="min-w-0 flex-1 truncate text-ink">{c.name}</span>
            <span className="tabular-nums text-ash">+{c.dial}</span>
            {c.code === current ? <Check aria-hidden className="h-4 w-4 text-primary" /> : null}
          </li>
        ))}
      </ul>
    </Modal>
  );
}

/** Champ complet (étiquette, aide, erreur) autour de <PhoneInput>. */
export function PhoneField({
  label = "Téléphone",
  hint = "Choisissez le pays, puis saisissez votre numéro sans l’indicatif.",
  error,
  required = true,
  optional,
  className,
  ...input
}: Omit<Parameters<typeof PhoneInput>[0], "id" | "invalid"> & {
  label?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  optional?: boolean;
  className?: string;
}) {
  return (
    <Field label={label} hint={hint} error={error} required={required && !optional} optional={optional} className={className}>
      {(c) => <PhoneInput {...input} id={c.id} invalid={c.invalid} aria-describedby={c["aria-describedby"]} aria-required={c["aria-required"]} />}
    </Field>
  );
}
