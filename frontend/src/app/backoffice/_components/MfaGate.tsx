"use client";
import { useState } from "react";
import { KeyRound, ShieldCheck } from "lucide-react";
import { Alert, Button, Card, Checkbox, TextField } from "@/components/ds";
import { apiErrorMessage, tokens } from "@/lib/api";
import { bo, type BoMe } from "@/lib/bo";

interface Setup { secret: string; otpauth_uri: string; qr: string; issuer: string }
interface Tokens { access: string; refresh: string }

/**
 * Double authentification du personnel : aucun module du Back-Office ne s'ouvre avant la vérification. Activation (mot de passe,
 * QR, premier code, codes de secours affichés UNE fois) ou vérification (code à 6 chiffres / code de secours). La preuve voyage
 * dans le jeton renvoyé par le serveur ; l'interface ne décide de rien.
 */
export function MfaGate({ mfa, onVerified }: { mfa: BoMe["mfa"]; onVerified: () => void }) {
  const enrolled = mfa.enrolled;
  const [step, setStep] = useState<"password" | "scan" | "backup" | "verify">(enrolled ? "verify" : "password");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [useBackup, setUseBackup] = useState(false);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [backup, setBackup] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run<T>(fn: () => Promise<T>, then: (r: T) => void) {
    setBusy(true);
    setError("");
    try {
      then(await fn());
    } catch (e) {
      setError(apiErrorMessage(e, "Opération impossible. Réessayez."));
    } finally {
      setBusy(false);
    }
  }
  const adopt = (t: Tokens) => tokens.set(t.access, t.refresh);

  return (
    <div className="mx-auto max-w-md px-4 py-10">
      <Card padding="lg">
        <div className="mb-4 flex items-center gap-3">
          <span aria-hidden className="grid h-11 w-11 place-items-center rounded-2xl bg-primarySoft text-primary">{step === "verify" ? <KeyRound className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />}</span>
          <h1 className="font-display text-xl font-extrabold text-ink">{step === "verify" ? "Vérification en deux étapes" : "Activer la double authentification"}</h1>
        </div>
        {mfa.locked_until ? <Alert tone="warning" className="mb-4">Vérification verrouillée quelques minutes après trop d’essais.</Alert> : null}
        {step === "password" ? (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void run(() => bo.post<Setup>("/mfa/setup/", { password }), (r) => { setSetup(r); setPassword(""); setStep("scan"); }); }}>
            <p className="text-sm text-inkSoft">Les comptes d’administration Tratra exigent une double authentification. Confirmez votre mot de passe pour commencer.</p>
            <TextField label="Mot de passe" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            {error ? <Alert tone="danger">{error}</Alert> : null}
            <Button type="submit" block loading={busy} disabled={!password}>Commencer</Button>
          </form>
        ) : null}
        {step === "scan" && setup ? (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void run(() => bo.post<Tokens & { backup_codes: string[] }>("/mfa/confirm/", { code }), (r) => { adopt(r); setBackup(r.backup_codes); setCode(""); setStep("backup"); }); }}>
            <p className="text-sm text-inkSoft">Scannez ce QR avec une application d’authentification (Google Authenticator, Microsoft Authenticator, 1Password…), puis saisissez le code à 6 chiffres affiché.</p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={setup.qr} alt="QR code d’activation de la double authentification" className="mx-auto h-48 w-48 rounded-panel border border-lineSoft bg-white p-2" />
            <p className="break-all text-center text-xs text-ash">Saisie manuelle : <code className="rounded bg-canvas px-1.5 py-0.5 text-inkSoft">{setup.secret}</code></p>
            <TextField label="Code à 6 chiffres" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            {error ? <Alert tone="danger">{error}</Alert> : null}
            <Button type="submit" block loading={busy} disabled={code.length !== 6}>Confirmer l’activation</Button>
          </form>
        ) : null}
        {step === "backup" ? (
          <div className="space-y-4">
            <Alert tone="warning" title="Codes de secours">Conservez-les dans un endroit sûr (gestionnaire de mots de passe). Chacun ne sert qu’une fois et ils ne seront <strong>plus jamais affichés</strong>.</Alert>
            <ul className="grid grid-cols-2 gap-2 font-mono text-sm text-ink">{backup.map((c) => <li key={c} className="rounded-lg bg-canvas px-3 py-1.5">{c}</li>)}</ul>
            <Checkbox label="J’ai enregistré mes codes de secours." checked={saved} onChange={(e) => setSaved(e.target.checked)} />
            <Button block disabled={!saved} onClick={onVerified}>Ouvrir le Back-Office</Button>
          </div>
        ) : null}
        {step === "verify" ? (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void run(() => bo.post<Tokens>("/mfa/verify/", useBackup ? { backup_code: code } : { code }), (r) => { adopt(r); setCode(""); onVerified(); }); }}>
            <p className="text-sm text-inkSoft">{useBackup ? "Saisissez l’un de vos codes de secours (usage unique)." : "Saisissez le code à 6 chiffres de votre application d’authentification."}</p>
            <TextField label={useBackup ? "Code de secours" : "Code à 6 chiffres"} inputMode={useBackup ? "text" : "numeric"} autoComplete="one-time-code" maxLength={useBackup ? 14 : 6} required value={code} onChange={(e) => setCode(useBackup ? e.target.value : e.target.value.replace(/\D/g, ""))} />
            {error ? <Alert tone="danger">{error}</Alert> : null}
            <Button type="submit" block loading={busy} disabled={useBackup ? code.length < 6 : code.length !== 6}>Vérifier</Button>
            <button type="button" className="block w-full text-center text-sm font-semibold text-primaryDark underline underline-offset-2" onClick={() => { setUseBackup((v) => !v); setCode(""); setError(""); }}>
              {useBackup ? "Utiliser mon application d’authentification" : "Utiliser un code de secours"}
            </button>
          </form>
        ) : null}
      </Card>
    </div>
  );
}
