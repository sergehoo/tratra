"use client";
import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowRight, CalendarCheck } from "lucide-react";
import { Alert, Button, ButtonLink, Checkbox, Field, PasswordInput, Skeleton, TextField } from "@/components/ds";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { PHONE_INITIAL, PhoneField } from "@/components/auth/PhoneField";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { isSafeInternalPath, loginHref, spaceHref } from "@/lib/links";
import { normalizePhone } from "@/lib/phone";

const EMPTY_FORM = {
  first_name: "",
  last_name: "",
  phone: PHONE_INITIAL,
  password: "",
  confirm: "",
  accept_terms: false,
};
type FormState = typeof EMPTY_FORM;
type FieldKey = keyof FormState;
type FieldErrors = Partial<Record<FieldKey, string>>;

const MIN_PASSWORD = 8;

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
function registerErrors(err: unknown): { general: string; fields: FieldErrors } {
  if (err instanceof ApiError) {
    const data = err.data;
    if (err.status === 429) {
      return { general: "Trop de tentatives. Patientez quelques instants puis réessayez.", fields: {} };
    }
    if (err.status >= 500) {
      return { general: "Le service est momentanément indisponible. Réessayez dans un instant.", fields: {} };
    }
    if (data && typeof data === "object" && !Array.isArray(data)) {
      const fields: FieldErrors = {};
      const others: string[] = [];
      for (const [key, value] of Object.entries(data)) {
        if (key === "code" && typeof value === "string") continue; // code technique, pas un message
        const message = messagesOf(value).join(" ");
        if (!message) continue;
        if (key in EMPTY_FORM) fields[key as FieldKey] = message;
        else others.push(message);
      }
      const general =
        others.join(" ") || (Object.keys(fields).length ? "Veuillez corriger les champs indiqués." : "Inscription impossible.");
      return { general, fields };
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
      <div className="grid grid-cols-2 gap-3">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
      </div>
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-[52px] w-full !rounded-full" />
      <span className="sr-only">Chargement…</span>
    </div>
  );
}

function validate(f: FormState): FieldErrors {
  const errors: FieldErrors = {};
  if (!f.first_name.trim()) errors.first_name = "Indiquez votre prénom.";
  if (!f.last_name.trim()) errors.last_name = "Indiquez votre nom.";
  if (!normalizePhone(f.phone)) errors.phone = "Numéro invalide. Exemple : +225 07 00 00 00 00.";
  if (f.password.length < MIN_PASSWORD) errors.password = `Au moins ${MIN_PASSWORD} caractères.`;
  if (f.confirm !== f.password) errors.confirm = "Les mots de passe ne correspondent pas.";
  if (!f.accept_terms) errors.accept_terms = "Acceptez les conditions et la politique de confidentialité pour continuer.";
  return errors;
}

function RegisterForm() {
  const { register, user, loading } = useAuth();
  const params = useSearchParams();
  const rawNext = params.get("next");
  const next = isSafeInternalPath(rawNext) ? rawNext : null;
  const isBooking = Boolean(next?.startsWith("/dashboard/services/"));

  const [f, setF] = useState<FormState>(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = <K extends FieldKey>(k: K, value: FormState[K]) => {
    setF((s) => ({ ...s, [k]: value }));
    if (fieldErrors[k]) setFieldErrors((errs) => ({ ...errs, [k]: undefined }));
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const local = validate(f);
    setFieldErrors(local);
    if (Object.keys(local).length) {
      setError("Veuillez corriger les champs indiqués.");
      return;
    }
    setBusy(true);
    try {
      await register(
        {
          first_name: f.first_name.trim(),
          last_name: f.last_name.trim(),
          phone: normalizePhone(f.phone) as string,
          password: f.password,
          accept_terms: f.accept_terms,
        },
        next,
      );
      // Succès : redirection vers la vérification du téléphone, le bouton reste désactivé.
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
        <Alert tone="brand" icon={<CalendarCheck />} title="Créez votre compte pour finaliser votre réservation." className="mb-5">
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
          Vous êtes déjà connecté(e) en tant que <strong>{user.first_name || user.phone || "membre"}</strong>.
        </Alert>
      ) : null}

      <form onSubmit={submit} className="space-y-5" noValidate>
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Prénom"
            required
            name="first_name"
            autoComplete="given-name"
            value={f.first_name}
            onChange={(e) => set("first_name", e.target.value)}
            error={fieldErrors.first_name}
          />
          <TextField
            label="Nom"
            required
            name="last_name"
            autoComplete="family-name"
            value={f.last_name}
            onChange={(e) => set("last_name", e.target.value)}
            error={fieldErrors.last_name}
          />
        </div>

        <PhoneField value={f.phone} onChange={(v) => set("phone", v)} error={fieldErrors.phone} />

        <Field label="Mot de passe" required error={fieldErrors.password} hint={`Au moins ${MIN_PASSWORD} caractères.`}>
          {(c) => (
            <PasswordInput
              {...c}
              name="password"
              required
              autoComplete="new-password"
              value={f.password}
              onChange={(e) => set("password", e.target.value)}
            />
          )}
        </Field>

        <Field label="Confirmer le mot de passe" required error={fieldErrors.confirm}>
          {(c) => (
            <PasswordInput
              {...c}
              name="confirm"
              required
              autoComplete="new-password"
              value={f.confirm}
              onChange={(e) => set("confirm", e.target.value)}
            />
          )}
        </Field>

        <div>
          <Checkbox
            name="accept_terms"
            checked={f.accept_terms}
            onChange={(e) => set("accept_terms", e.target.checked)}
            aria-invalid={Boolean(fieldErrors.accept_terms)}
            label={
              <>
                J’accepte les{" "}
                <Link href="/conditions" target="_blank" className="font-semibold text-primaryDark underline underline-offset-2">
                  conditions d’utilisation
                </Link>{" "}
                et la{" "}
                <Link href="/confidentialite" target="_blank" className="font-semibold text-primaryDark underline underline-offset-2">
                  politique de confidentialité
                </Link>
                .
              </>
            }
          />
          {fieldErrors.accept_terms ? (
            <p role="alert" className="mt-1.5 text-xs font-medium text-dangerInk">
              {fieldErrors.accept_terms}
            </p>
          ) : null}
        </div>

        {/* role="alert" (Alert danger) : l'erreur est annoncée dès son apparition. */}
        {error ? <Alert tone="danger">{error}</Alert> : null}

        <Button type="submit" size="lg" block loading={busy} rightIcon={<ArrowRight aria-hidden className="h-5 w-5" />}>
          {busy ? "Création…" : "Créer mon compte"}
        </Button>
        <p className="text-center text-xs text-ash">
          Un code vous sera envoyé par SMS pour confirmer votre numéro. Vous pourrez renseigner votre e-mail plus tard.
        </p>
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
      subtitle="Un seul compte pour réserver des artisans et proposer vos services."
      lead="Réservez un artisan près de chez vous et suivez vos interventions, ou proposez vos services : tout se gère depuis le même compte."
      width="lg"
    >
      {/* useSearchParams (?next=) exige une frontière Suspense. */}
      <Suspense fallback={<FormFallback />}>
        <RegisterForm />
      </Suspense>
    </AuthFrame>
  );
}
