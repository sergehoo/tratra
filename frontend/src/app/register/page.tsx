"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ArrowRight,
  Building2,
  CalendarCheck,
  Check,
  HardHat,
  ShieldCheck,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { Alert, Button, ButtonLink, Field, PasswordInput, Skeleton, TextField, cx } from "@/components/ds";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { isSafeInternalPath, loginHref, spaceHref, type SignupType } from "@/lib/links";

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
  if (value && typeof value === "object") {
    return Object.entries(value)
      .filter(([key, v]) => !(key === "code" && typeof v === "string"))
      .flatMap(([, v]) => messagesOf(v));
  }
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
        // Erreur codée {code, detail} : le code n'est pas un message à afficher.
        if (key === "code" && typeof value === "string") continue;
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

function FormFallback() {
  return (
    <div role="status" aria-busy="true" aria-label="Chargement du formulaire" className="space-y-5">
      <div className="grid grid-cols-3 gap-2">
        <Skeleton className="h-[96px] !rounded-panel" />
        <Skeleton className="h-[96px] !rounded-panel" />
        <Skeleton className="h-[96px] !rounded-panel" />
      </div>
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-[52px] w-full !rounded-full" />
      <span className="sr-only">Chargement…</span>
    </div>
  );
}

/** Choix du profil (radio natifs : navigation clavier, lecteurs d'écran, focus visible). */
function RolePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  const role = parseType(value) ?? "client";
  const context = ROLE_CONTEXT[role];
  const ContextIcon = context.icon;

  return (
    <fieldset>
      <legend className="mb-2 text-sm font-semibold text-ink">Je m’inscris en tant que</legend>
      <div className="grid grid-cols-3 gap-2">
        {ROLES.map((r) => {
          const Icon = r.icon;
          const checked = value === r.value;
          return (
            <label
              key={r.value}
              className={cx(
                "relative flex min-h-[96px] cursor-pointer flex-col items-center justify-center gap-1.5 rounded-panel border-2 px-2 py-3 text-center transition duration-200 ease-emphasized",
                "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-primary has-[:focus-visible]:ring-offset-2",
                checked
                  ? "border-primaryDark bg-primarySoft text-primaryDark shadow-soft"
                  : "border-line bg-white text-ink hover:-translate-y-0.5 hover:border-primary/50",
              )}
            >
              <input
                type="radio"
                name="user_type"
                value={r.value}
                checked={checked}
                onChange={onChange}
                className="sr-only"
              />
              {checked ? (
                <span
                  aria-hidden
                  className="absolute right-2 top-2 grid h-5 w-5 animate-scaleIn place-items-center rounded-full bg-accent text-ink"
                >
                  <Check className="h-3 w-3" strokeWidth={3} />
                </span>
              ) : null}
              <span
                aria-hidden
                className={cx(
                  "grid h-10 w-10 place-items-center rounded-control transition-colors duration-200",
                  checked ? "bg-primaryDark text-white" : "bg-lineSoft text-primary",
                )}
              >
                <Icon className="h-5 w-5" />
              </span>
              <span className="text-sm font-bold leading-tight">{r.label}</span>
              <span className="hidden text-caption text-inkSoft sm:block">{r.detail}</span>
            </label>
          );
        })}
      </div>
      <Alert tone="brand" icon={<ContextIcon />} className="mt-3 !p-3">
        {context.text}
      </Alert>
    </fieldset>
  );
}

function RegisterForm() {
  const { register, user, loading } = useAuth();
  const params = useSearchParams();
  const typeParam = parseType(params.get("type"));
  const rawNext = params.get("next");
  const next = isSafeInternalPath(rawNext) ? rawNext : null;
  const isBooking = Boolean(next?.startsWith("/dashboard/services/"));

  const [f, setF] = useState<FormState>(() => ({ ...EMPTY_FORM, user_type: typeParam ?? EMPTY_FORM.user_type }));
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FieldKey, string>>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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

  const home = spaceHref(user);

  return (
    <>
      {isBooking ? (
        <Alert
          tone="brand"
          icon={<CalendarCheck />}
          title="Créez votre compte pour finaliser votre réservation."
          className="mb-5"
        >
          Vous retrouverez la prestation choisie juste après.
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
          Vous êtes déjà connecté(e) en tant que <strong>{user.first_name || user.username}</strong>.
        </Alert>
      ) : null}

      <form onSubmit={submit} className="space-y-5">
        <RolePicker value={f.user_type} onChange={set("user_type")} />

        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Prénom"
            optional
            name="first_name"
            autoComplete="given-name"
            value={f.first_name}
            onChange={set("first_name")}
            error={fieldErrors.first_name}
          />
          <TextField
            label="Nom"
            optional
            name="last_name"
            autoComplete="family-name"
            value={f.last_name}
            onChange={set("last_name")}
            error={fieldErrors.last_name}
          />
        </div>

        <TextField
          label="Nom d’utilisateur"
          required
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          value={f.username}
          onChange={set("username")}
          error={fieldErrors.username}
        />

        <TextField
          label="Email"
          required
          name="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          autoCapitalize="none"
          spellCheck={false}
          value={f.email}
          onChange={set("email")}
          error={fieldErrors.email}
        />

        <TextField
          label="Téléphone"
          optional
          name="phone"
          type="tel"
          autoComplete="tel"
          inputMode="tel"
          value={f.phone}
          onChange={set("phone")}
          error={fieldErrors.phone}
        />

        <Field label="Mot de passe" required error={fieldErrors.password}>
          {(c) => (
            <PasswordInput
              {...c}
              name="password"
              required
              autoComplete="new-password"
              value={f.password}
              onChange={set("password")}
            />
          )}
        </Field>

        {/* role="alert" (Alert danger) : l'erreur est annoncée dès son apparition. */}
        {error ? <Alert tone="danger">{error}</Alert> : null}

        <Button
          type="submit"
          size="lg"
          block
          loading={busy}
          rightIcon={<ArrowRight aria-hidden className="h-5 w-5" />}
        >
          {busy ? "Création…" : "Créer mon compte"}
        </Button>
      </form>

      <div className="mt-8 border-t border-lineSoft pt-6 text-center">
        <p className="text-sm text-ash">Déjà inscrit ?</p>
        <ButtonLink href={loginHref(next)} variant="outline" size="lg" block className="mt-3">
          Se connecter
        </ButtonLink>
      </div>
    </>
  );
}

export default function RegisterPage() {
  return (
    <AuthFrame
      eyebrow="Nouveau compte"
      title="Créer un compte"
      subtitle="Choisissez votre profil pour commencer."
      lead="Réservez un artisan près de chez vous et suivez vos interventions, ou proposez vos services d’artisan."
      width="lg"
    >
      {/* useSearchParams (?type=, ?next=) exige une frontière Suspense. */}
      <Suspense fallback={<FormFallback />}>
        <RegisterForm />
      </Suspense>
    </AuthFrame>
  );
}
