"use client";
import type { ReactNode } from "react";
import { Radio } from "lucide-react";
import { Alert, ButtonLink, Card, Spinner, cx } from "@/components/ds";

/**
 * Disponibilité de l'artisan : contrôle segmenté accessible (aria-pressed).
 * Trois états conservés : inconnu (`null`, aucun segment actif), en ligne, hors ligne.
 * L'appel API (POST /handymen/presence/) reste porté par la page.
 */

const SEGMENT =
  "inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-full px-4 text-sm font-semibold transition duration-200 ease-emphasized sm:flex-none sm:px-5 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-night " +
  "disabled:cursor-not-allowed disabled:opacity-60";

function Segment({
  pressed,
  pending,
  disabled,
  pressedClass,
  dotClass,
  onClick,
  children,
}: {
  pressed: boolean;
  pending: boolean;
  disabled: boolean;
  pressedClass: string;
  dotClass: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={cx(SEGMENT, pressed ? pressedClass : "text-white/80 hover:bg-white/10 hover:text-white")}
    >
      {pending ? (
        <Spinner className="h-3.5 w-3.5" />
      ) : (
        <span aria-hidden className={cx("h-2 w-2 rounded-full", dotClass, pressed && "animate-pulseDot")} />
      )}
      {children}
    </button>
  );
}

export function PresenceCard({
  online,
  pending,
  error,
  onChange,
  className = "",
}: {
  online: boolean | null;
  /** Valeur demandée dont l'envoi est en cours (`null` : aucune requête). */
  pending: boolean | null;
  error: string;
  onChange: (value: boolean) => void;
  className?: string;
}) {
  const busy = pending !== null;
  const copy =
    online === true
      ? { title: "Vous êtes en ligne", hint: "Vous pouvez être proposé aux clients qui cherchent un artisan disponible." }
      : online === false
        ? { title: "Vous êtes hors ligne", hint: "Vous n’apparaissez pas parmi les artisans disponibles." }
        : { title: "Choisissez votre disponibilité", hint: "Seuls les profils vérifiés peuvent passer en ligne." };

  return (
    <Card variant="night" className={cx("relative overflow-hidden", className)}>
      <span aria-hidden className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-accent/15 blur-3xl" />
      <div className="relative">
        <p className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-accent">
          <Radio aria-hidden className="h-4 w-4" />
          Disponibilité
        </p>
        <div aria-live="polite" className="mt-3">
          <p className="font-display text-xl font-extrabold leading-tight text-white">{copy.title}</p>
          <p className="mt-1 text-sm leading-relaxed text-white/70">{copy.hint}</p>
        </div>

        <div role="group" aria-label="Disponibilité" className="mt-4 flex rounded-full bg-white/10 p-1 sm:inline-flex">
          <Segment
            pressed={online === true}
            pending={pending === true}
            disabled={busy}
            pressedClass="bg-accent text-ink shadow-glowAccent"
            dotClass={online === true ? "bg-primaryDark" : "bg-white/40"}
            onClick={() => onChange(true)}
          >
            En ligne
          </Segment>
          <Segment
            pressed={online === false}
            pending={pending === false}
            disabled={busy}
            pressedClass="bg-white text-ink"
            dotClass={online === false ? "bg-ash" : "bg-white/40"}
            onClick={() => onChange(false)}
          >
            Hors ligne
          </Segment>
        </div>

        {error ? (
          <Alert
            tone="danger"
            className="mt-4"
            action={
              <ButtonLink href="/worker/kyc" size="sm" variant="outline">
                Vérifier mon profil
              </ButtonLink>
            }
          >
            {error}
          </Alert>
        ) : null}
      </div>
    </Card>
  );
}
