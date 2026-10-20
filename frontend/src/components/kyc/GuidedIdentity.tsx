"use client";
/**
 * Vérification d'identité guidée (web), alignée sur l'application : choix CNI/passeport, photos guidées avec contrôle qualité,
 * lecture du recto qui PROPOSE nom, prénoms et date de naissance (confirmés par l'utilisateur), envoi, suivi de la revue humaine.
 * Mêmes API et mêmes contrôles serveur que l'application (handy/kyc_flow.py) ; la vérification faciale n'est jamais imposée ici.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Camera, CheckCircle2, CreditCard, Hourglass, RefreshCw, ShieldCheck } from "lucide-react";
import { ApiError, apiErrorMessage, get, patch, post, uploadWithProgress } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CAPTURE_TIPS, captureVerdict, guidedKycView, prefill, type GuidedKycView, type KycFlowState } from "@/lib/kycFlow";
import { Alert, Badge, Button, Skeleton, TextField, cx } from "@/components/ds";

const KIND_HINT: Record<string, { icon: typeof CreditCard; text: string }> = {
  cni: { icon: CreditCard, text: "Recto et verso — 2 photos" },
  passport: { icon: BookOpen, text: "Page avec votre photo — 1 photo" },
};

const date = (iso: string | null) => (iso ? new Intl.DateTimeFormat("fr-FR", { dateStyle: "long" }).format(new Date(iso)) : "");

export function GuidedIdentity({ onFinished, onLater }: { onFinished: () => void; onLater?: () => void }) {
  const { user } = useAuth();
  const [s, setS] = useState<KycFlowState | null>(null);
  const [override, setOverride] = useState<GuidedKycView | null>(null);
  const [kind, setKind] = useState<"cni" | "passport" | null>(null);
  const [form, setForm] = useState({ first_name: "", last_name: "", birth_date: "" });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [read, setRead] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const busyRef = useRef(false);

  const adopt = useCallback(
    (next: KycFlowState) => {
      setS(next);
      setKind(next.document.kind);
      setForm((f) => ({
        first_name: f.first_name || next.personal.first_name || user?.first_name || "",
        last_name: f.last_name || next.personal.last_name || user?.last_name || "",
        birth_date: f.birth_date || next.personal.birth_date || "",
      }));
    },
    [user?.first_name, user?.last_name],
  );

  const load = useCallback(async () => {
    setError("");
    try {
      adopt(await get<KycFlowState>("/me/kyc/"));
    } catch (e) {
      setError(apiErrorMessage(e, "La vérification n’a pas pu être chargée. Vérifiez votre connexion puis réessayez."));
    }
  }, [adopt]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => () => Object.values(previews).forEach((u) => URL.revokeObjectURL(u)), [previews]);

  async function run(action: () => Promise<void>) {
    if (busyRef.current) return;                   // réseau lent : un seul envoi à la fois
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      if (e instanceof ApiError && e.data && typeof e.data === "object" && "fields" in e.data) {
        setFieldErrors((e.data as { fields: Record<string, string> }).fields ?? {});
      }
      setError(apiErrorMessage(e, "Une erreur est survenue. Vérifiez votre connexion puis réessayez."));
    } finally {
      busyRef.current = false;
      setBusy(false);
      setProgress(null);
    }
  }

  const chooseKind = () =>
    run(async () => {
      if (!kind) return;
      adopt(await patch<KycFlowState>("/me/kyc/", { document_kind: kind }));
      setOverride(null);
    });

  const capture = (side: string, file: File) =>
    run(async () => {
      const body = new FormData();
      body.append("side", side);
      body.append("file", file);
      setProgress(0);
      const next = await uploadWithProgress<KycFlowState>("/me/kyc/capture/", body, setProgress);
      setPreviews((p) => {
        if (p[side]) URL.revokeObjectURL(p[side]);
        return { ...p, [side]: URL.createObjectURL(file) };
      });
      adopt(next);
      if (side === "front" && next.suggestions) {
        const { values, filled } = prefill(form, next.suggestions);
        setForm(values);
        setRead(filled);
      }
    });

  const savePersonal = () =>
    run(async () => {
      setFieldErrors({});
      adopt(await patch<KycFlowState>("/me/kyc/", { personal: form }));
      setOverride(null);
    });

  const send = () => run(async () => adopt(await post<KycFlowState>("/me/kyc/send/")));

  if (!s) {
    return error ? (
      <Alert tone="danger" title="Vérification indisponible">
        {error}{" "}
        <Button variant="ghost" size="sm" onClick={() => void load()}>
          Réessayer
        </Button>
      </Alert>
    ) : (
      <Skeleton className="h-64 !rounded-card" />
    );
  }

  const view = override ?? guidedKycView(s);
  const kindLabel = s.document.kinds.find((k) => k.value === s.document.kind)?.label ?? "";

  return (
    <div className="space-y-4" aria-busy={busy}>
      <p className="flex items-center gap-2 text-sm font-semibold text-inkSoft">
        <ShieldCheck aria-hidden className="h-4 w-4 text-primary" /> Vérification d’identité · {s.status_label}
      </p>

      {view === "document" ? (
        <>
          <h2 className="font-display text-xl font-extrabold text-ink">Quelle pièce allez-vous photographier ?</h2>
          <div className="space-y-2.5" role="radiogroup" aria-label="Type de pièce">
            {s.document.kinds.map((k) => {
              const Icon = KIND_HINT[k.value]?.icon ?? CreditCard;
              const selected = kind === k.value;
              return (
                <button
                  key={k.value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => setKind(k.value)}
                  className={cx(
                    "flex min-h-[64px] w-full items-center gap-3 rounded-panel border bg-white px-4 py-3 text-left transition",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
                    selected ? "border-2 border-primary bg-primarySoft" : "border-line hover:border-primary/50",
                  )}
                >
                  <Icon aria-hidden className="h-7 w-7 text-primary" />
                  <span className="flex-1">
                    <span className="block text-lg font-semibold text-ink">{k.label}</span>
                    <span className="block text-sm text-ash">{KIND_HINT[k.value]?.text}</span>
                  </span>
                  {selected ? <CheckCircle2 aria-hidden className="h-7 w-7 text-primary" /> : null}
                </button>
              );
            })}
          </div>
          <Button size="lg" block loading={busy} disabled={!kind} onClick={() => void chooseKind()}>
            Continuer
          </Button>
        </>
      ) : null}

      {view === "capture" ? (
        <>
          <h2 className="font-display text-xl font-extrabold text-ink">Photographiez votre {kindLabel.toLowerCase() || "pièce"}</h2>
          {s.review.state === "rejected" && s.review.reason ? (
            <Alert tone="danger" title="Nouvelle pièce demandée">{s.review.reason}</Alert>
          ) : s.review.previous_reason ? (
            <Alert tone="warning" title="Motif du refus précédent">{s.review.previous_reason}</Alert>
          ) : null}
          <Alert tone="info" title="Pour une photo acceptée du premier coup">{CAPTURE_TIPS}</Alert>
          <ul className="space-y-3">
            {s.document.captures.map((c) => {
              const verdict = captureVerdict(c);
              return (
                <li key={c.side} className="rounded-panel border border-line bg-white p-4">
                  <div className="flex items-center gap-3">
                    {previews[c.side] && c.present ? (
                      // Aperçu LOCAL de la photo qui vient d'être prise (jamais rechargée depuis le serveur).
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={previews[c.side]} alt={`Aperçu : ${c.label}`} className="h-16 w-24 rounded-lg object-cover" />
                    ) : (
                      <span aria-hidden className="grid h-16 w-24 place-items-center rounded-lg bg-primarySoft text-primary">
                        <Camera className="h-7 w-7" />
                      </span>
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="font-bold text-ink">{c.label}</p>
                      <Badge tone={verdict.tone === "neutral" ? "gray" : verdict.tone} className="mt-1 whitespace-normal">
                        {verdict.text}
                      </Badge>
                    </div>
                  </div>
                  {(c.reading?.notes ?? []).map((n) => (
                    <Alert key={n} tone="warning" className="mt-3">{n}</Alert>
                  ))}
                  <input
                    ref={(el) => {
                      inputs.current[c.side] = el;
                    }}
                    type="file"
                    accept="image/jpeg,image/png"
                    capture="environment"
                    className="sr-only"
                    aria-label={`Photo : ${c.label}`}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void capture(c.side, f);
                      e.target.value = "";
                    }}
                  />
                  <Button
                    variant={c.present && c.quality !== "fail" ? "outline" : "primary"}
                    size="lg"
                    block
                    className="mt-3"
                    disabled={busy}
                    leftIcon={<Camera aria-hidden className="h-5 w-5" />}
                    onClick={() => inputs.current[c.side]?.click()}
                  >
                    {c.present ? `Reprendre : ${c.label.toLowerCase()}` : `Photographier : ${c.label.toLowerCase()}`}
                  </Button>
                </li>
              );
            })}
          </ul>
          {progress !== null ? (
            <div aria-live="polite">
              <p className="text-sm text-inkSoft">Envoi et contrôle de la photo… {Math.round(progress * 100)} %</p>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-lineSoft">
                <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
            </div>
          ) : null}
          <Button variant="ghost" disabled={busy} onClick={() => setOverride("document")}>
            Changer de pièce
          </Button>
        </>
      ) : null}

      {view === "personal" ? (
        <>
          <h2 className="font-display text-xl font-extrabold text-ink">Vos informations</h2>
          {read ? (
            <Alert tone="info" title="Lu sur votre pièce">
              Nous avons rempli ces informations à partir de votre pièce. Vérifiez-les et corrigez si besoin.
            </Alert>
          ) : null}
          <p className="text-sm text-inkSoft">Saisissez vos nom et prénoms exactement comme sur votre pièce d’identité.</p>
          <TextField label="Prénoms" required value={form.first_name} error={fieldErrors.first_name}
            onChange={(e) => setForm({ ...form, first_name: e.target.value })} autoComplete="given-name" />
          <TextField label="Nom" required value={form.last_name} error={fieldErrors.last_name}
            onChange={(e) => setForm({ ...form, last_name: e.target.value })} autoComplete="family-name" />
          <TextField label="Date de naissance" type="date" required value={form.birth_date} error={fieldErrors.birth_date}
            onChange={(e) => setForm({ ...form, birth_date: e.target.value })} autoComplete="bday" />
          <p className="text-xs text-ash">Ces informations servent uniquement à comparer votre pièce : votre nom public reste celui de votre compte.</p>
          <Button size="lg" block loading={busy} onClick={() => void savePersonal()}>
            Confirmer mes informations
          </Button>
        </>
      ) : null}

      {view === "send" ? (
        <>
          <h2 className="font-display text-xl font-extrabold text-ink">Vérifiez avant d’envoyer</h2>
          <dl className="space-y-1.5 rounded-panel border border-line bg-white p-4 text-sm">
            <div className="flex justify-between gap-3"><dt className="text-ash">Pièce</dt><dd className="font-semibold text-ink">{kindLabel}</dd></div>
            {s.document.captures.map((c) => (
              <div key={c.side} className="flex justify-between gap-3"><dt className="text-ash">{c.label}</dt><dd className="font-semibold text-ink">{captureVerdict(c).text}</dd></div>
            ))}
            <div className="flex justify-between gap-3"><dt className="text-ash">Nom</dt><dd className="font-semibold text-ink">{s.personal.first_name} {s.personal.last_name}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ash">Naissance</dt><dd className="font-semibold text-ink">{date(s.personal.birth_date)}</dd></div>
          </dl>
          <p className="text-xs text-ash">
            En envoyant, vous acceptez que l’équipe Tratra examine ces photos pour vérifier votre identité. Elles sont stockées en privé.
          </p>
          <Button size="lg" block loading={busy} onClick={() => void send()}>
            Envoyer à l’équipe Tratra
          </Button>
          <Button variant="ghost" block disabled={busy} onClick={() => setOverride("personal")}>
            Modifier mes informations
          </Button>
        </>
      ) : null}

      {view === "review" ? (
        <>
          <Alert tone="info" title="Votre pièce est en cours de revue">
            {s.review.sent_at ? `Transmise le ${date(s.review.sent_at)}. ` : ""}Un membre de l’équipe Tratra l’examine. Vous serez
            prévenu(e) de la décision. Vous pouvez fermer cette page : votre progression est enregistrée.
          </Alert>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" leftIcon={<RefreshCw aria-hidden className="h-4 w-4" />} disabled={busy} onClick={() => void run(load)}>
              Actualiser
            </Button>
            <Button leftIcon={<Hourglass aria-hidden className="h-4 w-4" />} onClick={onFinished}>
              Continuer
            </Button>
          </div>
        </>
      ) : null}

      {view === "verified" ? (
        <>
          <Alert tone="success" title="Identité vérifiée">Votre pièce a été validée par l’équipe Tratra.</Alert>
          <Button size="lg" block onClick={onFinished}>
            Continuer
          </Button>
        </>
      ) : null}

      {error ? <Alert tone="danger">{error}</Alert> : null}
      {onLater && (view === "document" || view === "capture" || view === "personal" || view === "send") ? (
        <Button variant="ghost" size="lg" block disabled={busy} onClick={onLater}>
          Plus tard
        </Button>
      ) : null}
    </div>
  );
}
