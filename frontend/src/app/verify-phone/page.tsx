"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { MessageSquareText } from "lucide-react";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { Alert, Button, ButtonLink, OtpInput, Skeleton } from "@/components/ds";
import { RoleGuard } from "@/components/RoleGuard";
import { apiErrorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { homeFor, isSafeInternalPath } from "@/lib/links";
import { maskPhone, OTP_LENGTH, OTP_RESEND_SECONDS, requestOtp, verifyOtp } from "@/lib/otp";

function VerifyPhone() {
  const { user, refreshUser } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const rawNext = params.get("next");
  const next = isSafeInternalPath(rawNext) ? rawNext : homeFor(user?.user_type);

  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
  }, []);

  function startCooldown() {
    if (timer.current) window.clearInterval(timer.current);
    setCooldown(OTP_RESEND_SECONDS);
    timer.current = window.setInterval(() => {
      setCooldown((c) => {
        if (c <= 1 && timer.current) window.clearInterval(timer.current);
        return Math.max(0, c - 1);
      });
    }, 1000);
  }

  async function send() {
    setBusy(true);
    setError("");
    try {
      await requestOtp();
      setSent(true);
      setCode("");
      startCooldown();
    } catch (e) {
      setError(apiErrorMessage(e, "L’envoi du code a échoué. Réessayez dans un instant."));
    } finally {
      setBusy(false);
    }
  }

  async function verify(value = code) {
    if (value.length !== OTP_LENGTH || busy) return;
    setBusy(true);
    setError("");
    try {
      await verifyOtp(value);
      await refreshUser();
      setDone(true);
    } catch (e) {
      setError(apiErrorMessage(e, "La vérification a échoué. Réessayez dans un instant."));
      setCode(""); // on repart d'une saisie vide (le message d'erreur reste jusqu'à la prochaine frappe)
    } finally {
      setBusy(false);
    }
  }

  const phone = user?.phone;
  const verified = done || user?.is_verified === true;

  return (
    <AuthFrame
      eyebrow="Sécurité du compte"
      title="Vérifiez votre téléphone"
      subtitle="Confirmez votre numéro pour sécuriser votre compte Tratra."
      lead="Un numéro confirmé protège votre compte et vos réservations."
    >
      {verified ? (
        <div className="space-y-5">
          <Alert tone="success" title="Téléphone vérifié">
            Votre numéro est confirmé. Merci !
          </Alert>
          <ButtonLink href={next} size="lg" block>
            Continuer
          </ButtonLink>
        </div>
      ) : !phone ? (
        <div className="space-y-5">
          <Alert tone="warning" title="Aucun numéro enregistré">
            Aucun numéro de téléphone n’est associé à votre compte : il n’y a rien à vérifier pour le moment.
          </Alert>
          <ButtonLink href={next} variant="outline" size="lg" block>
            Retour
          </ButtonLink>
        </div>
      ) : (
        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (sent) void verify();
            else void send();
          }}
          noValidate
        >
          <p className="text-sm leading-relaxed text-inkSoft">
            {sent
              ? `Saisissez le code à ${OTP_LENGTH} chiffres reçu au ${maskPhone(phone)}.`
              : `Nous enverrons un code à ${OTP_LENGTH} chiffres par SMS au ${maskPhone(phone)}.`}
          </p>

          {sent ? (
            <OtpInput
              value={code}
              onChange={(v) => {
                setCode(v);
                if (error) setError("");
              }}
              onComplete={(v) => void verify(v)}
              disabled={busy}
              invalid={Boolean(error)}
              autoFocus
              describedBy={error ? "otp-error" : undefined}
            />
          ) : null}

          <div id="otp-error" aria-live="polite">
            {error ? <Alert tone="danger">{error}</Alert> : null}
          </div>

          {sent ? (
            <>
              <Button type="submit" size="lg" block loading={busy} disabled={code.length !== OTP_LENGTH}>
                Vérifier
              </Button>
              <Button type="button" variant="ghost" block disabled={busy || cooldown > 0} onClick={() => void send()}>
                {cooldown > 0 ? `Renvoyer le code (${cooldown} s)` : "Renvoyer le code"}
              </Button>
            </>
          ) : (
            <Button type="submit" size="lg" block loading={busy} leftIcon={<MessageSquareText aria-hidden className="h-4 w-4" />}>
              Recevoir le code
            </Button>
          )}

          <Button type="button" variant="ghost" block disabled={busy} onClick={() => router.push(next)}>
            Plus tard
          </Button>
        </form>
      )}
    </AuthFrame>
  );
}

export default function VerifyPhonePage() {
  return (
    <RoleGuard>
      <Suspense fallback={<div className="mx-auto max-w-md p-6"><Skeleton className="h-64 w-full !rounded-card" /></div>}>
        <VerifyPhone />
      </Suspense>
    </RoleGuard>
  );
}
