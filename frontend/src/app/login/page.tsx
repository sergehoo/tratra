"use client";
import Link from "next/link";
import { Suspense, useEffect, useId, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowRight, CalendarCheck, LockKeyhole, Mail, Search, TimerReset } from "lucide-react";
import { Alert, Button, ButtonLink, Field, Input, PasswordInput, PhoneField, Skeleton } from "@/components/ds";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { isProtectedPath, isSafeInternalPath, registerHref, spaceHref } from "@/lib/links";
import { formatCountdown, parseLoginLock, secondsLeft } from "@/lib/loginLock";
import { DEFAULT_COUNTRY, lookupE164, phoneError, type PhoneValue } from "@/lib/phone";

function FormFallback() {
  return (
    <div role="status" aria-busy="true" aria-label="Chargement du formulaire" className="space-y-5">
      <div className="space-y-2">
        <Skeleton className="h-3.5 w-2/5" />
        <Skeleton className="h-12 w-full" />
      </div>
      <div className="space-y-2">
        <Skeleton className="h-3.5 w-1/3" />
        <Skeleton className="h-12 w-full" />
      </div>
      <Skeleton className="h-[52px] w-full !rounded-full" />
      <span className="sr-only">Chargement…</span>
    </div>
  );
}

function loginErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.status === 429) {
    return "Trop de tentatives de connexion. Patientez quelques instants puis réessayez.";
  }
  if (err instanceof ApiError && err.status >= 500) {
    return "Le service est momentanément indisponible. Réessayez dans un instant.";
  }
  if (err instanceof TypeError) {
    return "Impossible de joindre le service. Vérifiez votre connexion puis réessayez.";
  }
  return "Téléphone ou mot de passe incorrect.";
}

function LoginForm() {
  const { login, user, loading } = useAuth();
  const params = useSearchParams();
  const rawNext = params.get("next");
  const next = isSafeInternalPath(rawNext) ? rawNext : null;
  const isBooking = Boolean(next?.startsWith("/dashboard/services/"));
  const uid = useId();
  const errorId = `${uid}-error`;

  const [username, setUsername] = useState("");
  // Connexion par téléphone (pays + numéro national) ; « identifiant ou e-mail » reste possible pour les anciens comptes.
  const [byPhone, setByPhone] = useState(true);
  const [phone, setPhone] = useState<PhoneValue>({ country: DEFAULT_COUNTRY, national: "" });
  const [phoneErr, setPhoneErr] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // Blocage après trop de tentatives : fin (horloge locale) et adresse du support ; le serveur reste l'autorité à la fin du décompte.
  const [lock, setLock] = useState<{ endMs: number; supportEmail: string } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const left = lock ? secondsLeft(lock.endMs, now) : 0;
  const locked = left > 0;

  useEffect(() => {
    if (!lock) return;
    const tick = () => setNow(Date.now());
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [lock]);
  useEffect(() => {
    if (lock && left === 0) setLock(null);
  }, [lock, left]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (locked) return;
    setError("");
    let identifier = username.trim();
    if (byPhone) {
      const found = lookupE164(phone);       // tolérant : un ancien numéro hors norme est retrouvé par le serveur
      if (!found) {
        setPhoneErr(phoneError(phone) ?? "Saisissez votre numéro de téléphone.");
        return;
      }
      identifier = found;
    }
    setPhoneErr("");
    setBusy(true);
    try {
      await login(identifier, password, next);
      // Succès : la redirection est en cours, le bouton reste désactivé.
    } catch (err) {
      const blocked = parseLoginLock(err);
      if (blocked) {                                   // bloqué : jamais « mot de passe incorrect » ; temps restant donné par le serveur
        setLock({ endMs: Date.now() + blocked.seconds * 1000, supportEmail: blocked.supportEmail });
        setNow(Date.now());
      } else {
        setError(loginErrorMessage(err));
      }
      setBusy(false);
    }
  }

  const home = spaceHref(user);

  return (
    <>
      {params.get("reset") === "1" ? (
        <Alert tone="success" title="Mot de passe mis à jour" className="mb-5">
          Connectez-vous avec votre numéro et votre nouveau mot de passe.
        </Alert>
      ) : null}

      {isBooking ? (
        <Alert
          tone="brand"
          icon={<CalendarCheck />}
          title="Connectez-vous pour finaliser votre réservation."
          className="mb-5"
        >
          Vous retrouverez la prestation choisie juste après.
        </Alert>
      ) : next && isProtectedPath(next) ? (
        <Alert tone="brand" icon={<LockKeyhole />} className="mb-5">
          Connectez-vous pour accéder à cette page.
        </Alert>
      ) : null}

      {!loading && user && home ? (
        <Alert
          tone="success"
          className="mb-5"
          action={
            <ButtonLink href={home} size="sm" rightIcon={<ArrowRight aria-hidden className="h-4 w-4" />}>
              Accéder à mon espace
            </ButtonLink>
          }
        >
          Vous êtes déjà connecté(e) en tant que <strong>{user.first_name || user.phone || "membre"}</strong>.
        </Alert>
      ) : null}

      <form onSubmit={submit} className="space-y-5">
        {byPhone ? (
          <PhoneField
            name="username"
            autoComplete="username"
            value={phone}
            onChange={(v) => {
              setPhone(v);
              if (phoneErr) setPhoneErr("");
            }}
            error={phoneErr || undefined}
          />
        ) : (
          <Field label="Identifiant ou e-mail" required>
            {(c) => (
              <Input
                {...c}
                name="username"
                type="text"
                required
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? errorId : undefined}
              />
            )}
          </Field>
        )}
        <button
          type="button"
          onClick={() => {
            setByPhone((v) => !v);
            setPhoneErr("");
            setError("");
          }}
          className="-mt-3 text-sm font-semibold text-primaryDark underline-offset-2 hover:underline"
        >
          {byPhone ? "Ancien compte : se connecter avec un identifiant ou un e-mail" : "Se connecter avec mon numéro de téléphone"}
        </button>

        <Field label="Mot de passe">
          {(c) => (
            <PasswordInput
              {...c}
              name="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? errorId : undefined}
            />
          )}
        </Field>

        <div className="-mt-2 text-right">
          <Link href="/forgot-password" className="text-sm font-semibold text-primaryDark underline-offset-2 hover:underline">
            Mot de passe oublié ?
          </Link>
        </div>

        {/* Blocage : annoncé UNE fois (role="alert") ; le décompte est un « timer » non annoncé à chaque seconde. */}
        {locked && lock ? (
          <Alert
            tone="warning"
            icon={<TimerReset />}
            title="Connexion bloquée"
            action={
              <a
                href={`mailto:${lock.supportEmail}?subject=${encodeURIComponent("Connexion bloquée")}`}
                className="inline-flex min-h-[40px] items-center gap-2 rounded-full border border-line bg-white px-4 text-sm font-semibold text-ink hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <Mail aria-hidden className="h-4 w-4" />
                Contacter le support
              </a>
            }
          >
            Trop de tentatives de connexion. Consultez le support ou patientez :{" "}
            <span role="timer" aria-live="off" className="font-display text-xl font-extrabold tabular-nums">
              {formatCountdown(left)}
            </span>
          </Alert>
        ) : null}

        {/* role="alert" (Alert danger) : l'erreur est annoncée dès son apparition. */}
        {error ? (
          <div id={errorId}>
            <Alert tone="danger">{error}</Alert>
          </div>
        ) : null}

        <Button
          type="submit"
          size="lg"
          block
          loading={busy}
          disabled={locked}
          rightIcon={<ArrowRight aria-hidden className="h-5 w-5" />}
        >
          {locked ? `Réessayer dans ${formatCountdown(left)}` : busy ? "Connexion…" : "Se connecter"}
        </Button>
      </form>

      <div className="mt-8 border-t border-lineSoft pt-6 text-center">
        <p className="text-sm text-ash">Pas encore de compte ?</p>
        <ButtonLink
          href={registerHref(isBooking ? "client" : undefined, next)}
          variant="outline"
          size="lg"
          block
          className="mt-3"
        >
          Créer un compte
        </ButtonLink>
        <ButtonLink
          href="/search"
          variant="ghost"
          className="mt-3"
          leftIcon={<Search aria-hidden className="h-4 w-4" />}
        >
          Parcourir les prestations
        </ButtonLink>
      </div>
    </>
  );
}

export default function LoginPage() {
  return (
    <AuthFrame
      eyebrow="Mon espace"
      title="Connexion"
      subtitle="Accédez à votre espace Tratra."
      lead="Retrouvez vos réservations, vos missions et votre profil."
    >
      {/* useSearchParams (?next=) exige une frontière Suspense. */}
      <Suspense fallback={<FormFallback />}>
        <LoginForm />
      </Suspense>
    </AuthFrame>
  );
}
