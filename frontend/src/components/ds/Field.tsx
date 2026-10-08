"use client";
import {
  forwardRef,
  useId,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { ChevronDown, Eye, EyeOff } from "lucide-react";
import { cx } from "./cx";

/** Classes communes des contrôles de saisie (champ, zone de texte, liste). */
export const CONTROL =
  "w-full rounded-control border border-line bg-white text-[15px] text-ink outline-none transition duration-200 " +
  "placeholder:text-fog hover:border-fog focus:border-primary focus:ring-4 focus:ring-primary/15 " +
  "aria-[invalid=true]:border-danger aria-[invalid=true]:focus:ring-danger/15 " +
  "disabled:cursor-not-allowed disabled:bg-canvas disabled:text-ash disabled:hover:border-line read-only:bg-canvas";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
  /** Élément décoratif à gauche (icône) — le champ réserve la place. */
  leading?: ReactNode;
  /** Élément interactif/décoratif à droite (bouton afficher/masquer, unité…). */
  trailing?: ReactNode;
};

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { invalid, leading, trailing, className = "", ...props },
  ref,
) {
  const wrapped = Boolean(leading || trailing);
  const input = (
    <input
      ref={ref}
      aria-invalid={invalid || props["aria-invalid"] || undefined}
      className={cx(CONTROL, "min-h-[48px] px-4", leading && "pl-11", trailing && "pr-12", !wrapped && className)}
      {...props}
    />
  );
  if (!wrapped) return input;
  return (
    <div className={cx("relative", className)}>
      {leading ? (
        <span aria-hidden className="pointer-events-none absolute inset-y-0 left-0 grid w-11 place-items-center text-fog">
          {leading}
        </span>
      ) : null}
      {input}
      {trailing ? <span className="absolute inset-y-0 right-0 flex items-center pr-1.5">{trailing}</span> : null}
    </div>
  );
});

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean };

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { invalid, className = "", rows = 4, ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      aria-invalid={invalid || props["aria-invalid"] || undefined}
      className={cx(CONTROL, "min-h-[96px] resize-y px-4 py-3 leading-relaxed", className)}
      {...props}
    />
  );
});

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean };

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { invalid, className = "", children, ...props },
  ref,
) {
  return (
    <div className={cx("relative", className)}>
      <select
        ref={ref}
        aria-invalid={invalid || props["aria-invalid"] || undefined}
        className={cx(CONTROL, "min-h-[48px] appearance-none px-4 pr-11")}
        {...props}
      >
        {children}
      </select>
      <ChevronDown aria-hidden className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ash" />
    </div>
  );
});

/** Champ mot de passe avec bouton afficher/masquer (accessible, aria-pressed). */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputProps, "type" | "trailing">>(
  function PasswordInput(props, ref) {
    const [visible, setVisible] = useState(false);
    return (
      <Input
        ref={ref}
        {...props}
        type={visible ? "text" : "password"}
        trailing={
          <button
            type="button"
            onClick={() => setVisible((v) => !v)}
            aria-pressed={visible}
            aria-label={visible ? "Masquer le mot de passe" : "Afficher le mot de passe"}
            className="grid h-10 w-10 place-items-center rounded-xl text-ash transition hover:bg-lineSoft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            {visible ? <EyeOff aria-hidden className="h-4 w-4" /> : <Eye aria-hidden className="h-4 w-4" />}
          </button>
        }
      />
    );
  },
);

/** Props injectées par <Field> dans son contrôle (à répartir via `{...c}`). */
export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-required"?: true;
  invalid?: boolean;
}

/**
 * Étiquette + contrôle + aide + erreur, correctement reliés pour les lecteurs d'écran.
 * `children` est une fonction recevant les props à répartir sur le contrôle.
 */
export function Field({
  label,
  hint,
  error,
  required,
  optional,
  className = "",
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  /** Affiche « (facultatif) » à côté de l'étiquette. */
  optional?: boolean;
  className?: string;
  children: (props: FieldControlProps) => ReactNode;
}) {
  const uid = useId();
  const id = `${uid}-field`;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cx("space-y-1.5", className)}>
      <label htmlFor={id} className="block text-sm font-semibold text-ink">
        {label}
        {required ? (
          <span aria-hidden className="ml-0.5 text-danger">
            *
          </span>
        ) : null}
        {optional ? <span className="ml-1.5 text-xs font-normal text-ash">(facultatif)</span> : null}
      </label>
      {children({
        id,
        "aria-describedby": describedBy,
        "aria-required": required ? true : undefined,
        invalid: Boolean(error),
      })}
      {hint && !error ? (
        <p id={hintId} className="text-xs text-ash">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs font-medium text-dangerInk">
          {error}
        </p>
      ) : null}
    </div>
  );
}

type FieldWrapperProps = {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  optional?: boolean;
  fieldClassName?: string;
};

/** Champ texte complet (étiquette + saisie + aide/erreur). */
export function TextField({
  label,
  hint,
  error,
  optional,
  fieldClassName,
  required,
  ...inputProps
}: FieldWrapperProps & InputProps) {
  return (
    <Field label={label} hint={hint} error={error} optional={optional} required={required} className={fieldClassName}>
      {(c) => <Input {...c} required={required} {...inputProps} />}
    </Field>
  );
}

/** Zone de texte complète. */
export function TextareaField({
  label,
  hint,
  error,
  optional,
  fieldClassName,
  required,
  ...props
}: FieldWrapperProps & TextareaProps) {
  return (
    <Field label={label} hint={hint} error={error} optional={optional} required={required} className={fieldClassName}>
      {(c) => <Textarea {...c} required={required} {...props} />}
    </Field>
  );
}

/** Liste déroulante complète. */
export function SelectField({
  label,
  hint,
  error,
  optional,
  fieldClassName,
  required,
  children,
  ...props
}: FieldWrapperProps & SelectProps) {
  return (
    <Field label={label} hint={hint} error={error} optional={optional} required={required} className={fieldClassName}>
      {(c) => (
        <Select {...c} required={required} {...props}>
          {children}
        </Select>
      )}
    </Field>
  );
}

/** Case à cocher avec libellé cliquable. */
export function Checkbox({
  label,
  className = "",
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: ReactNode }) {
  return (
    <label className={cx("flex cursor-pointer items-start gap-3 text-sm text-inkSoft", className)}>
      <input
        type="checkbox"
        className="mt-0.5 h-5 w-5 shrink-0 cursor-pointer rounded-md border-line accent-primaryDark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
        {...props}
      />
      <span className="leading-snug">{label}</span>
    </label>
  );
}
