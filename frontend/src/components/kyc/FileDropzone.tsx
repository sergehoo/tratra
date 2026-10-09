"use client";
import { forwardRef, type InputHTMLAttributes } from "react";
import { FileText, Upload } from "lucide-react";
import { cx } from "@/components/ds";
import { formatBytes } from "./documents";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "className"> & {
  /** Fichier actuellement choisi (nom + taille réels), sinon `null`. */
  selected?: { name: string; size: number } | null;
  invalid?: boolean;
};

/**
 * Zone de dépôt de fichier accessible : un vrai `<input type="file">` transparent recouvre toute la
 * zone (clavier, lecteur d'écran, sélecteur natif, dépôt par glisser-déposer), l'habillage est décoratif.
 * Relier l'étiquette via `id` (voir <Field>).
 */
export const FileDropzone = forwardRef<HTMLInputElement, Props>(function FileDropzone(
  { selected, invalid, disabled, ...input },
  ref,
) {
  const sizeLabel = selected ? formatBytes(selected.size) : "";
  return (
    <div
      className={cx(
        "relative rounded-card border-2 border-dashed px-5 py-7 text-center transition duration-200 ease-emphasized",
        "focus-within:border-primary focus-within:ring-4 focus-within:ring-primary/15",
        selected ? "border-primary/40 bg-primarySoft/60" : "border-line bg-canvas hover:border-primary/50 hover:bg-primarySoft/40",
        invalid && "border-danger",
        disabled && "opacity-60",
      )}
    >
      <input
        ref={ref}
        type="file"
        disabled={disabled}
        aria-invalid={invalid || undefined}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
        {...input}
      />
      <div aria-hidden className="pointer-events-none flex flex-col items-center gap-2">
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-white text-primary shadow-hair">
          {selected ? <FileText className="h-6 w-6" /> : <Upload className="h-6 w-6" />}
        </span>
        {selected ? (
          <>
            <p className="max-w-full break-all text-sm font-semibold text-ink">{selected.name}</p>
            <p className="text-xs text-ash">
              {sizeLabel ? `${sizeLabel} · ` : ""}Touchez pour changer de fichier
            </p>
          </>
        ) : (
          <>
            <p className="text-sm font-semibold text-ink">Touchez pour choisir un fichier</p>
            <p className="hidden text-xs text-ash sm:block">ou glissez-le ici</p>
          </>
        )}
      </div>
    </div>
  );
});
