"use client";
import { Suspense, useEffect, useId, useState, type ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  CalendarCheck,
  Eye,
  EyeOff,
  HardHat,
  Info,
  Loader2,
  ShieldCheck,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { isSafeInternalPath, loginHref, spaceHref, type SignupType } from "@/lib/links";

const RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";
const INPUT =
  "min-h-[48px] w-full rounded-xl border border-slate-200 bg-white px-4 text-[15px] text-ink outline-none transition placeholder:text-slate-400 focus:border-primary focus:ring-4 focus:ring-primary/15 aria-[invalid=true]:border-red-400";

const ROLES: { value: SignupType; label: string; detail: string; icon: LucideIcon }[] = [
  { value: "client", label: "Client", detail: "Particulier", icon: UserRound },
  { value: "handyman", label: "Artisan", detail: "Ouvrier, technicien", icon: HardHat },
  { value: "entreprise", label: "Entreprise", detail: "Compte B2B", icon: Building2 },
];

const ROLE_CONTEXT: Record<SignupType, { icon: LucideIcon; text: string }> = {
  client: { icon: CalendarCheck, text: "Réservez des artisans et suivez vos interventions depuis votre espace." },
  handyman: {
    icon: ShieldCheck,
    text: "Après inscription, complétez votre vérification (KYC) pour recevoir des missions.",
  },
  entreprise: { icon: Building2, text: "Vous pourrez compléter votre profil entreprise et choisir une offre." },
};

function parseType(value: string | null): SignupType | null {
  return ROLES.some((r) => r.value === value) ? (value as SignupType) : null;
}

const EMPTY_FORM = {
  username: "",
  email: "",
  password: "",
  user_type: "client",
  first_name: "",
  last_name: "",
  phone: "",
};
type FormState = typeof EMPTY_FORM;
type FieldKey = keyof FormState;

function messagesOf(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(messagesOf);
  if (value && typeof value === "object") return Object.values(value).flatMap(messagesOf);
  return [];
}

/** Erreurs API : messages par champ quand l'API les rattache à un champ, sinon message général. */
function registerErrors(err: unknown): { general: string; fields: Partial<Record<FieldKey, string>> } {
  if (err instanceof ApiError) {
    const data = err.data;
    if (data && typeof data === "object" && !Array.isArray(data)) {
      const fields: Partial<Record<FieldKey, string>> = {};
      const others: string[] = [];
      for (const [key, value] of Object.entries(data)) {
        const message = messagesOf(value).join(" ");
        if (!message) continue;
        if (key in EMPTY_FORM) fields[key as FieldKey] = message;
        else others.push(message);
      }
      const general =
        others.join(" ") || (Object.keys(fields).length ? "Veuillez corriger les champs indiqués." : "Inscription impossible.");
      return { general, fields };
    }
    if (Array.isArray(data)) return { general: messagesOf(data).join(" ") || "Inscription impossible.", fields: {} };
    if (err.status === 429) {
      return { general: "Trop de tentatives. Patientez quelques instants puis réessayez.", fields: {} };
    }
    return { general: "Inscription impossible.", fields: {} };
  }
  if (err instanceof TypeError) {
    return { general: "Impossible de joindre le service. Vérifiez votre connexion puis réessayez.", fields: {} };
  }
  return { general: "Inscription impossible.", fields: {} };
}

/** Cadre commun des pages d'authentification (logo, retour à l'accueil). */
function AuthFrame({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-slate-50">
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-80 bg-gradient-to-b from-primarySoft to-transparent" />
      <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/20 blur-3xl" />
      <header className="relative mx-auto flex w-full max-w-lg items-center justify-between px-4 pt-6">
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
      <main id="contenu" className="relative mx-auto w-full max-w-lg px-4 pb-12 pt-8">
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
      <div className="grid grid-cols-3 gap-2">
        <div className="skeleton h-24" />
        <div className="skeleton h-24" />
        <div className="skeleton h-24" />
      </div>
      <div className="skeleton h-12 w-full" />
      <div className="skeleton h-12 w-full" />
      <div className="skeleton h-12 w-full" />
      <span className="sr-only">Chargement…</span>
    </div>
  );
}

function Field({
  id,
  label,
  error,
  optional,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  optional?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1.5 flex items-baseline justify-between gap-2 text-sm font-semibold text-ink">
        {label}
        {optional ? <span className="text-xs font-normal text-ash">facultatif</span> : null}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-xs font-medium text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function RegisterForm() {
  const { register, user, loading } = useAuth();
  const params = useSearchParams();
  const typeParam = parseType(params.get("type"));
  const rawNext = params.get("next");
  const next = isSafeInternalPath(rawNext) ? rawNext : null;
  const isBooking = Boolean(next?.startsWith("/client/services/"));
  const uid = useId();
  const id = (k: string) => `${uid}-${k}`;

  const [f, setF] = useState<FormState>(() => ({ ...EMPTY_FORM, user_type: typeParam ?? EMPTY_FORM.user_type }));
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FieldKey, string>>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // Un lien « /register?type=… » suivi depuis la page elle-même met à jour le profil choisi.
  useEffect(() => {
    if (typeParam) setF((s) => ({ ...s, user_type: typeParam }));
  }, [typeParam]);

  const set = (k: FieldKey) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const value = e.target.value;
    setF((s) => ({ ...s, [k]: value }));
    if (fieldErrors[k]) setFieldErrors((errs) => ({ ...errs, [k]: undefined }));
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setFieldErrors({});
    setBusy(true);
    try {
      // Téléphone facultatif : un champ vide n'est pas envoyé (le backend le
      // stocke alors à NULL ; une chaîne vide entrerait en conflit avec
      // l'unicité du numéro dès le 2e compte sans téléphone).
      const phone = f.phone.trim();
      await register({ ...f, phone: phone || undefined }, next);
      // Succès : la redirection est en cours, le bouton reste désactivé.
    } catch (err) {
      const { general, fields } = registerErrors(err);
      setFieldErrors(fields);
      setError(general);
      setBusy(false);
    }
  }

  const describe = (k: FieldKey) => (fieldErrors[k] ? `${id(k)}-error` : undefined);
  const role = parseType(f.user_type) ?? "client";
  const context = ROLE_CONTEXT[role];
  const ContextIcon = context.icon;
  const home = spaceHref(user);

  return (
    <>
      {isBooking ? (
        <div className="mb-5 flex items-start gap-3 rounded-2xl border border-accent/50 bg-accentSoft p-4 text-sm text-ink">
          <CalendarCheck aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-primaryDark" />
          <p>
            <strong className="font-semibold">Créez votre compte pour finaliser votre réservation.</strong> Vous
            retrouverez la prestation choisie juste après.
          </p>
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
        <fieldset>
          <legend className="mb-2 text-sm font-semibold text-ink">Je m&apos;inscris en tant que</legend>
          <div className="grid grid-cols-3 gap-2">
            {ROLES.map((r) => {
              const Icon = r.icon;
              const checked = f.user_type === r.value;
              return (
                <label
                  key={r.value}
                  className={`relative flex min-h-[88px] cursor-pointer flex-col items-center justify-center gap-1.5 rounded-2xl border-2 px-2 py-3 text-center transition has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-primary has-[:focus-visible]:ring-offset-2 ${
                    checked
                      ? "border-primary bg-primarySoft text-primaryDark"
                      : "border-slate-200 bg-white text-ink hover:border-primary/40"
                  }`}
                >
                  <input
                    type="radio"
                    name="user_type"
                    value={r.value}
                    checked={checked}
                    onChange={set("user_type")}
                    className="sr-only"
                  />
                  <span
                    aria-hidden
                    className={`grid h-9 w-9 place-items-center rounded-xl ${checked ? "bg-primary text-white" : "bg-slate-100 text-primary"}`}
                  >
                    <Icon className="h-5 w-5" />
                  </span>
                  <span className="text-sm font-bold leading-tight">{r.label}</span>
                  <span className="hidden text-[11px] leading-tight text-ash sm:block">{r.detail}</span>
                </label>
              );
            })}
          </div>
          <p aria-live="polite" className="mt-3 flex items-start gap-2 rounded-xl bg-slate-50 px-3 py-2.5 text-xs leading-relaxed text-ink">
            <ContextIcon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            {context.text}
          </p>
        </fieldset>

        <div className="grid grid-cols-2 gap-3">
          <Field id={id("first_name")} label="Prénom" error={fieldErrors.first_name}>
            <input
              id={id("first_name")}
              autoComplete="given-name"
              value={f.first_name}
              onChange={set("first_name")}
              aria-invalid={fieldErrors.first_name ? true : undefined}
              aria-describedby={describe("first_name")}
              className={INPUT}
            />
          </Field>
          <Field id={id("last_name")} label="Nom" error={fieldErrors.last_name}>
            <input
              id={id("last_name")}
              autoComplete="family-name"
              value={f.last_name}
              onChange={set("last_name")}
              aria-invalid={fieldErrors.last_name ? true : undefined}
              aria-describedby={describe("last_name")}
              className={INPUT}
            />
          </Field>
        </div>

        <Field id={id("username")} label="Nom d'utilisateur" error={fieldErrors.username}>
          <input
            id={id("username")}
            required
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            value={f.username}
            onChange={set("username")}
            aria-invalid={fieldErrors.username ? true : undefined}
            aria-describedby={describe("username")}
            className={INPUT}
          />
        </Field>

        <Field id={id("email")} label="Email" error={fieldErrors.email}>
          <input
            id={id("email")}
            type="email"
            required
            autoComplete="email"
            inputMode="email"
            autoCapitalize="none"
            spellCheck={false}
            value={f.email}
            onChange={set("email")}
            aria-invalid={fieldErrors.email ? true : undefined}
            aria-describedby={describe("email")}
            className={INPUT}
          />
        </Field>

        <Field id={id("phone")} label="Téléphone" error={fieldErrors.phone} optional>
          <input
            id={id("phone")}
            type="tel"
            autoComplete="tel"
            inputMode="tel"
            value={f.phone}
            onChange={set("phone")}
            aria-invalid={fieldErrors.phone ? true : undefined}
            aria-describedby={describe("phone")}
            className={INPUT}
          />
        </Field>

        <Field id={id("password")} label="Mot de passe" error={fieldErrors.password}>
          <div className="relative">
            <input
              id={id("password")}
              type={showPassword ? "text" : "password"}
              required
              autoComplete="new-password"
              value={f.password}
              onChange={set("password")}
              aria-invalid={fieldErrors.password ? true : undefined}
              aria-describedby={describe("password")}
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
        </Field>

        {error ? (
          <p role="alert" className="flex items-start gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
            <Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
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
              Création…
            </>
          ) : (
            <>
              Créer mon compte
              <ArrowRight aria-hidden className="h-5 w-5" />
            </>
          )}
        </button>
      </form>

      <p className="mt-6 border-t border-slate-100 pt-6 text-center text-sm text-ash">
        Déjà inscrit ?{" "}
        <Link
          href={loginHref(next)}
          className={`inline-flex min-h-[44px] items-center rounded-lg px-1 font-bold text-primaryDark hover:underline ${RING}`}
        >
          Se connecter
        </Link>
      </p>
    </>
  );
}

export default function RegisterPage() {
  return (
    <AuthFrame title="Créer un compte" subtitle="Choisissez votre profil pour commencer.">
      {/* useSearchParams (?type=, ?next=) exige une frontière Suspense. */}
      <Suspense fallback={<FormFallback />}>
        <RegisterForm />
      </Suspense>
    </AuthFrame>
  );
}
