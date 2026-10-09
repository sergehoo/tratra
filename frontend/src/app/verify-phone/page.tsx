"use client";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { MessageSquareText } from "lucide-react";
import { AuthFrame } from "@/components/auth/AuthFrame";
import { Alert, Button, ButtonLink, OtpInput, Skeleton } from "@/components/ds";
import { RoleGuard } from "@/components/RoleGuard";
import { apiErrorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { homeFor, isSafeInternalPath } from "@/lib/links";
import { maskPhone, OTP_LENGTH, OTP_RESEND_SECONDS, requestOtp, verifyOtp } from "@/lib/otp";

/** 9 → « 0:09 », 600 → « 10:00 ». */
function clock(seconds: number): string {
  const s = Math.max(0, seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Compte à rebours en secondes, rafraîchi chaque seconde ; `start(n)` le (re)lance. */
function useCountdown() {
  const [left, setLeft] = useState(0);
  const timer = useRef<number | null>(null);
  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
  }, []);
  const start = useCallback((seconds: number) => {
    if (timer.current) window.clearInterval(timer.current);
    setLeft(seconds);
    timer.current = window.setInterval(() => {
      setLeft((c) => {
        if (c <= 1 && timer.current) window.clearInterval(timer.current);
        return Math.max(0, c - 1);
      });
    }, 1000);
  }, []);
  return [left, start] as const;
}

function VerifyPhone() {
  const { user, refreshUser } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const rawNext = params.get("next");
  const next = isSafeInternalPath(rawNext) ? rawNext : homeFor(user?.user_type);
  const auto = params.get("auto") === "1";

  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [resendIn, startResend] = useCountdown();
  const [expiresIn, startExpiry] = useCountdown();
  const autoSent = useRef(false);

  async function send() {
    setBusy(true);
    setError("");
    try {
      const r = await requestOtp();
      setSent(true);
      setCode("");
      startResend(r.resend_in ?? OTP_RESEND_SECONDS);
      startExpiry(r.expires_in ?? 600);
    } catch (e) {
      // 503 : SMS indisponible ; 502 : envoi refusé ; 429 : délai / quota — message de l'API, jamais un faux succès.
      setError(apiErrorMessage(e, "L’envoi du code a échoué. Réessayez dans un instant."));
    } finally {
      setBusy(false);
    }
  }

  // Après l'inscription (?auto=1) : le code est envoyé une seule fois, à l'arrivée sur l'écran.
  useEffect(() => {
    if (auto && user?.phone && !user.is_verified && !autoSent.current) {
      autoSent.current = true;
      void send();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, user?.phone, user?.is_verified]);

  async function verify(value = code) {
    if (value.length !== OTP_LENGTH || busy || expiresIn === 0) return;
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
  const expired = sent && expiresIn === 0;

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
            <>
              <OtpInput
                value={code}
                onChange={(v) => {
                  setCode(v);
                  if (error) setError("");
                }}
                onComplete={(v) => void verify(v)}
                disabled={busy || expired}
                invalid={Boolean(error)}
                autoFocus
                describedBy={error ? "otp-error" : undefined}
              />
              <p className="text-center text-xs text-ash" aria-live="off">
                {expired ? "Ce code a expiré." : `Le code expire dans ${clock(expiresIn)}.`}
              </p>
            </>
          ) : null}

          <div id="otp-error" aria-live="polite">
            {error ? <Alert tone="danger">{error}</Alert> : null}
            {expired && !error ? <Alert tone="warning">Le code a expiré : demandez-en un nouveau.</Alert> : null}
          </div>

          {sent ? (
            <>
              <Button type="submit" size="lg" block loading={busy} disabled={code.length !== OTP_LENGTH || expired}>
                Vérifier
              </Button>
              <Button type="button" variant="ghost" block disabled={busy || resendIn > 0} onClick={() => void send()}>
                {resendIn > 0 ? `Renvoyer le code (${resendIn} s)` : "Renvoyer le code"}
              </Button>
            </>
          ) : (
            <Button type="submit" size="lg" block loading={busy} leftIcon={<MessageSquareText aria-hidden className="h-4 w-4" />}>
              {error ? "Réessayer l’envoi" : "Recevoir le code"}
            </Button>
          )}

          <Button type="button" variant="ghost" block disabled={busy} onClick={() => router.push(next)}>
            Plus tard
          </Button>
          <p className="text-center text-xs text-ash">
            Tant que le code n’est pas validé, votre numéro n’est pas considéré comme vérifié.
          </p>
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
