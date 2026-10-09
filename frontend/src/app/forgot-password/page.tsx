"use client";
import { Suspense, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, MessageSquareText } from "lucide-react";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { PHONE_INITIAL, PhoneField } from "@/components/auth/PhoneField";
import { Alert, Button, ButtonLink, Field, OtpInput, PasswordInput } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api";
import { normalizePhone } from "@/lib/phone";
import { confirmPasswordReset, maskPhone, OTP_LENGTH, OTP_RESEND_SECONDS, requestPasswordReset } from "@/lib/otp";

function useCountdown() {
  const [left, setLeft] = useState(0);
  function start(seconds: number) {
    setLeft(seconds);
    const id = window.setInterval(() => {
      setLeft((c) => {
        if (c <= 1) window.clearInterval(id);
        return Math.max(0, c - 1);
      });
    }, 1000);
  }
  return [left, start] as const;
}

function ForgotPassword() {
  const router = useRouter();
  const [phoneInput, setPhoneInput] = useState(PHONE_INITIAL);
  const [phone, setPhone] = useState<string | null>(null); // E.164 une fois le code demandé
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState("");
  const [resendIn, startResend] = useCountdown();

  async function sendCode(e?: React.FormEvent) {
    e?.preventDefault();
    const normalized = normalizePhone(phone ?? phoneInput);
    if (!normalized) {
      setFieldError("Numéro invalide. Exemple : +225 07 00 00 00 00.");
      return;
    }
    setFieldError("");
    setError("");
    setBusy(true);
    try {
      const r = await requestPasswordReset(normalized);
      setPhone(normalized);
      setCode("");
      startResend(r.resend_in ?? OTP_RESEND_SECONDS);
    } catch (err) {
      setError(apiErrorMessage(err, "L’envoi du code a échoué. Réessayez dans un instant."));
    } finally {
      setBusy(false);
    }
  }

  async function reset(e: React.FormEvent) {
    e.preventDefault();
    if (!phone) return;
    if (code.length !== OTP_LENGTH) return;
    if (password.length < 8) {
      setError("Le mot de passe doit contenir au moins 8 caractères.");
      return;
    }
    if (password !== confirm) {
      setError("Les mots de passe ne correspondent pas.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await confirmPasswordReset({ phone, code, password });
      router.push("/login?reset=1");
    } catch (err) {
      setError(apiErrorMessage(err, "La réinitialisation a échoué. Réessayez dans un instant."));
      setCode("");
      setBusy(false);
    }
  }

  return phone === null ? (
    <form onSubmit={sendCode} className="space-y-5" noValidate>
      <p className="text-sm leading-relaxed text-inkSoft">
        Saisissez le numéro de votre compte : nous vous enverrons un code par SMS pour définir un nouveau mot de passe.
      </p>
      <PhoneField value={phoneInput} onChange={setPhoneInput} error={fieldError} autoFocus />
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button type="submit" size="lg" block loading={busy} leftIcon={<MessageSquareText aria-hidden className="h-4 w-4" />}>
        Recevoir le code
      </Button>
      <ButtonLink href="/login" variant="ghost" block>
        Retour à la connexion
      </ButtonLink>
    </form>
  ) : (
    <form onSubmit={reset} className="space-y-5" noValidate>
      <p className="text-sm leading-relaxed text-inkSoft">
        Si ce numéro correspond à un compte, un code à {OTP_LENGTH} chiffres vient d’être envoyé au {maskPhone(phone)}. Saisissez-le puis
        choisissez un nouveau mot de passe.
      </p>
      <OtpInput value={code} onChange={(v) => { setCode(v); if (error) setError(""); }} disabled={busy} invalid={Boolean(error)} autoFocus />
      <Field label="Nouveau mot de passe" required hint="Au moins 8 caractères.">
        {(c) => (
          <PasswordInput {...c} name="password" required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        )}
      </Field>
      <Field label="Confirmer le mot de passe" required>
        {(c) => (
          <PasswordInput {...c} name="confirm" required autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        )}
      </Field>
      <div aria-live="polite">{error ? <Alert tone="danger">{error}</Alert> : null}</div>
      <Button
        type="submit"
        size="lg"
        block
        loading={busy}
        disabled={code.length !== OTP_LENGTH || !password || !confirm}
        rightIcon={<ArrowRight aria-hidden className="h-5 w-5" />}
      >
        Définir le nouveau mot de passe
      </Button>
      <Button type="button" variant="ghost" block disabled={busy || resendIn > 0} onClick={() => void sendCode()}>
        {resendIn > 0 ? `Renvoyer le code (${resendIn} s)` : "Renvoyer le code"}
      </Button>
      <Button type="button" variant="ghost" block disabled={busy} onClick={() => { setPhone(null); setError(""); }}>
        Changer de numéro
      </Button>
    </form>
  );
}

export default function ForgotPasswordPage() {
  return (
    <AuthFrame
      eyebrow="Sécurité du compte"
      title="Mot de passe oublié"
      subtitle="Récupérez votre compte avec un code reçu par SMS."
      lead="Votre numéro de téléphone est la clé de votre compte Tratra."
    >
      <Suspense fallback={null}>
        <ForgotPassword />
      </Suspense>
    </AuthFrame>
  );
}
