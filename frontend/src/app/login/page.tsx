"use client";
import { Suspense, useId, useState, type ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, ArrowRight, CalendarCheck, Eye, EyeOff, Loader2, LockKeyhole, Search } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { isProtectedPath, isSafeInternalPath, registerHref, spaceHref } from "@/lib/links";

const RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";
const INPUT =
  "min-h-[48px] w-full rounded-xl border border-slate-200 bg-white px-4 text-[15px] text-ink outline-none transition placeholder:text-slate-400 focus:border-primary focus:ring-4 focus:ring-primary/15 aria-[invalid=true]:border-red-400";

/** Cadre commun des pages d'authentification (logo, retour à l'accueil). */
function AuthFrame({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-slate-50">
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-80 bg-gradient-to-b from-primarySoft to-transparent" />
      <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/20 blur-3xl" />
      <header className="relative mx-auto flex w-full max-w-md items-center justify-between px-4 pt-6">
        <Link href="/" className={`flex items-center gap-2.5 rounded-2xl ${RING}`} aria-label="Tratra — accueil">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-white shadow-sm ring-1 ring-black/5">
            <Image src="/tratra_logo.webp" alt="" width={30} height={30} priority className="h-[30px] w-[30px]" />
          </span>
          <span aria-hidden className="font-display text-[1.35rem] font-extrabold tracking-tight text-ink">
            Tra<span className="text-primary">tra</span>
          </span>
        </Link>
        <Link
          href="/"
          className={`inline-flex min-h-[44px] items-center gap-1.5 rounded-xl px-2 text-sm font-semibold text-ash transition hover:text-ink ${RING}`}
        >
          <ArrowLeft aria-hidden className="h-4 w-4" />
          Accueil
        </Link>
      </header>
      <main id="contenu" className="relative mx-auto w-full max-w-md px-4 pb-12 pt-8">
        <div className="rounded-3xl border border-slate-100 bg-white p-6 shadow-strong sm:p-8">
          <h1 className="font-display text-2xl font-extrabold tracking-tight text-ink">{title}</h1>
          <p className="mt-1 text-sm text-ash">{subtitle}</p>
          <div className="mt-6">{children}</div>
        </div>
      </main>
    </div>
  );
}

function FormFallback() {
  return (
    <div aria-busy="true" className="space-y-4">
      <div className="skeleton h-12 w-full" />
      <div className="skeleton h-12 w-full" />
      <div className="skeleton h-12 w-full !rounded-2xl" />
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
  return "Identifiants invalides.";
}

function LoginForm() {
  const { login, user, loading } = useAuth();
  const params = useSearchParams();
  const rawNext = params.get("next");
  const next = isSafeInternalPath(rawNext) ? rawNext : null;
  const isBooking = Boolean(next?.startsWith("/client/services/"));
  const uid = useId();
  const ids = { user: `${uid}-user`, password: `${uid}-password`, error: `${uid}-error` };

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username, password, next);
      // Succès : la redirection est en cours, le bouton reste désactivé.
    } catch (err) {
      setError(loginErrorMessage(err));
      setBusy(false);
    }
  }

  const home = spaceHref(user);

  return (
    <>
      {isBooking ? (
        <div className="mb-5 flex items-start gap-3 rounded-2xl border border-accent/50 bg-accentSoft p-4 text-sm text-ink">
          <CalendarCheck aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-primaryDark" />
          <p>
            <strong className="font-semibold">Connectez-vous pour finaliser votre réservation.</strong> Vous
            retrouverez la prestation choisie juste après.
          </p>
        </div>
      ) : next && isProtectedPath(next) ? (
        <div className="mb-5 flex items-start gap-3 rounded-2xl border border-primary/15 bg-primarySoft p-4 text-sm text-primaryDark">
          <LockKeyhole aria-hidden className="mt-0.5 h-5 w-5 shrink-0" />
          <p>Connectez-vous pour accéder à cette page.</p>
        </div>
      ) : null}

      {!loading && user && home ? (
        <div className="mb-5 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-ink">
          Vous êtes déjà connecté(e) en tant que <strong>{user.first_name || user.username}</strong>.{" "}
          <Link href={home} className={`font-semibold text-primaryDark underline underline-offset-2 ${RING}`}>
            Accéder à mon espace
          </Link>
        </div>
      ) : null}

      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor={ids.user} className="mb-1.5 block text-sm font-semibold text-ink">
            Email ou nom d&apos;utilisateur
          </label>
          <input
            id={ids.user}
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
            aria-describedby={error ? ids.error : undefined}
            className={INPUT}
          />
        </div>

        <div>
          <label htmlFor={ids.password} className="mb-1.5 block text-sm font-semibold text-ink">
            Mot de passe
          </label>
          <div className="relative">
            <input
              id={ids.password}
              name="password"
              type={showPassword ? "text" : "password"}
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? ids.error : undefined}
              className={`${INPUT} pr-12`}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-pressed={showPassword}
              aria-label="Afficher le mot de passe"
              className={`absolute inset-y-0 right-0 grid w-12 place-items-center rounded-r-xl text-ash transition hover:text-ink ${RING}`}
            >
              {showPassword ? <EyeOff aria-hidden className="h-5 w-5" /> : <Eye aria-hidden className="h-5 w-5" />}
            </button>
          </div>
        </div>

        {error ? (
          <p id={ids.error} role="alert" className="rounded-xl bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={busy}
          className={`inline-flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl bg-primary px-5 text-[15px] font-bold text-white shadow-glow transition hover:bg-primaryDark disabled:cursor-wait disabled:opacity-70 ${RING}`}
        >
          {busy ? (
            <>
              <Loader2 aria-hidden className="h-5 w-5 animate-spin" />
              Connexion…
            </>
          ) : (
            <>
              Se connecter
              <ArrowRight aria-hidden className="h-5 w-5" />
            </>
          )}
        </button>
      </form>

      <div className="mt-6 border-t border-slate-100 pt-6 text-center">
        <p className="text-sm text-ash">Pas encore de compte ?</p>
        <Link
          href={registerHref(isBooking ? "client" : undefined, next)}
          className={`mt-3 inline-flex min-h-[48px] w-full items-center justify-center rounded-2xl border-2 border-primary/20 px-5 text-sm font-bold text-primaryDark transition hover:border-primary hover:bg-primarySoft ${RING}`}
        >
          Créer un compte
        </Link>
        <Link
          href="/search"
          className={`mt-4 inline-flex min-h-[44px] items-center gap-1.5 rounded-xl px-2 text-sm font-semibold text-ash transition hover:text-ink ${RING}`}
        >
          <Search aria-hidden className="h-4 w-4" />
          Parcourir les prestations
        </Link>
      </div>
    </>
  );
}

export default function LoginPage() {
  return (
    <AuthFrame title="Connexion" subtitle="Accédez à votre espace Tratra.">
      {/* useSearchParams (?next=) exige une frontière Suspense. */}
      <Suspense fallback={<FormFallback />}>
        <LoginForm />
      </Suspense>
    </AuthFrame>
  );
}
