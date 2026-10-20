"use client";
/**
 * « Inscription accompagnée » (web) : une question par écran, gros boutons, voix du navigateur (synthèse vocale locale, aucun
 * fournisseur en ligne ni IA), progression enregistrée sur le serveur à chaque réponse et reprise à l'écran atteint. Mêmes données et
 * mêmes règles que l'application et que le formulaire classique (handy/onboarding.py) : rien n'est publié avant la vérification.
 */
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, BadgeCheck, Camera, CheckCircle2, Circle, LockKeyhole, PartyPopper, RotateCcw, ShieldCheck, Smartphone, Volume2, VolumeX } from "lucide-react";
import { GuidedIdentity } from "@/components/kyc/GuidedIdentity";
import { ApiError, apiErrorMessage, apiJson, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDashboard } from "@/lib/dashboard";
import { deleteLocal, readLocal, writeLocal } from "@/lib/localVault";
import {
  GUIDED_PATH, PENDING_NAME, answered, declaredExperience, draftFromState, emptyDraft, keepPending, minimumFor, nextStep, previousStep,
  progressOf, remainingAtEnd, resumeStep, stepsFor, takePending, toggleAnswer,
  type OnbConfig, type OnbDraft, type OnbQuestion, type OnbState, type Vault,
} from "@/lib/onboarding";
import { featuredTrades, resolveTrades, type ResolvedTrade } from "@/lib/trades";
import type { Category, Paginated } from "@/lib/types";
import { patchForm } from "@/lib/uploadPatch";
import { Alert, Badge, Button, ButtonLink, Card, Skeleton, TextField, cx } from "@/components/ds";

const VOICE_KEY = "tratra.voice.autoplay";

/** Coffre local cloisonné par compte : effacé à la déconnexion volontaire, gardé si la session expire. */
const vault: Vault = { read: readLocal, write: writeLocal, del: deleteLocal };

/** Voix du navigateur en français (si une voix française est installée) ; « Réécouter » et lecture automatique désactivable. */
function useVoice() {
  const [available, setAvailable] = useState(false);
  const [autoplay, setAutoplayState] = useState(true);
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    try {
      if (window.localStorage.getItem(VOICE_KEY) === "0") setAutoplayState(false);
    } catch {
      /* stockage indisponible : lecture automatique par défaut */
    }
    const synth = window.speechSynthesis;
    const check = () => setAvailable(synth.getVoices().some((v) => v.lang.toLowerCase().startsWith("fr")));
    check();
    synth.addEventListener?.("voiceschanged", check);
    return () => {
      synth.removeEventListener?.("voiceschanged", check);
      synth.cancel();
    };
  }, []);

  const say = useCallback(
    (text: string) => {
      if (!available || !text.trim()) return;
      const synth = window.speechSynthesis;
      synth.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "fr-FR";
      const fr = synth.getVoices().find((v) => v.lang.toLowerCase().startsWith("fr"));
      if (fr) u.voice = fr;
      u.rate = 0.95;
      u.onstart = () => setSpeaking(true);
      u.onend = () => setSpeaking(false);
      u.onerror = () => setSpeaking(false);
      synth.speak(u);
    },
    [available],
  );

  const stop = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  const setAutoplay = useCallback(
    (value: boolean) => {
      setAutoplayState(value);
      if (!value) stop();
      try {
        window.localStorage.setItem(VOICE_KEY, value ? "1" : "0");
      } catch {
        /* préférence non gardée : sans conséquence */
      }
    },
    [stop],
  );

  return { available, autoplay, speaking, say, stop, setAutoplay };
}

function Title({ children, help }: { children: ReactNode; help?: ReactNode }) {
  return (
    <div className="mb-5">
      <h1 className="font-display text-2xl font-extrabold leading-tight text-ink sm:text-[1.7rem]">{children}</h1>
      {help ? <p className="mt-2 text-base leading-relaxed text-inkSoft sm:text-[17px]">{help}</p> : null}
    </div>
  );
}

/** Réponse en GROS bouton (64 px minimum), avec illustration et coche. */
function Choice({ label, emoji, selected, multi, onClick }: { label: string; emoji?: string; selected: boolean; multi?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      role={multi ? "checkbox" : "radio"}
      aria-checked={selected}
      onClick={onClick}
      className={cx(
        "flex min-h-[64px] w-full items-center gap-3 rounded-panel border bg-white px-4 py-2.5 text-left transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
        selected ? "border-2 border-primary bg-primarySoft" : "border-line hover:border-primary/50",
      )}
    >
      {emoji ? <span aria-hidden className="text-[28px] leading-none">{emoji}</span> : null}
      <span className="flex-1 text-lg font-semibold text-ink">{label}</span>
      {selected ? <CheckCircle2 aria-hidden className="h-7 w-7 text-primary" /> : <Circle aria-hidden className="h-7 w-7 text-fog" />}
    </button>
  );
}

function Pill({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cx(
        "min-h-[52px] min-w-[96px] rounded-full border bg-white px-5 text-[17px] font-semibold text-ink transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
        selected ? "border-2 border-primary bg-primarySoft" : "border-line hover:border-primary/50",
      )}
    >
      {label}
    </button>
  );
}

function Illustration({ icon: Icon }: { icon: typeof Camera }) {
  return (
    <div aria-hidden className="mx-auto my-4 grid h-28 w-28 place-items-center rounded-full bg-primarySoft text-primary">
      <Icon className="h-14 w-14" />
    </div>
  );
}

function Reassurance({ children }: { children: ReactNode }) {
  return (
    <p className="mt-3 flex items-start gap-2 text-[15px] text-inkSoft">
      <ShieldCheck aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
      <span>{children}</span>
    </p>
  );
}

function GuidedFlow() {
  const router = useRouter();
  const params = useSearchParams();
  const { user, refreshUser } = useAuth();
  const { data: dash, reload: reloadDashboard } = useDashboard();
  const voice = useVoice();

  const [loading, setLoading] = useState(true);
  const [trades, setTrades] = useState<ResolvedTrade[]>([]);
  const [allTrades, setAllTrades] = useState(false);
  const [config, setConfig] = useState<OnbConfig | null>(null);
  const [draft, setDraft] = useState<OnbDraft>(emptyDraft());
  const [server, setServer] = useState<OnbState | null>(null);
  const [step, setStep] = useState("intro");
  const [otherCity, setOtherCity] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  /** Dernier enregistrement impossible : réponses gardées sur cet appareil (réseau coupé) ou session expirée. */
  const [kept, setKept] = useState<"" | "offline" | "expired">("");
  const [sessionChanged, setSessionChanged] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const photoRef = useRef<HTMLInputElement>(null);
  const ownerRef = useRef<number | null>(null);          // compte propriétaire de ce parcours
  const draftRef = useRef<OnbDraft>(draft);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const busyRef = useRef(false);
  const stoppedRef = useRef(false);
  draftRef.current = draft;

  const verify = !(user?.is_verified ?? false);
  const steps = useMemo(() => stepsFor(config, { verify }), [config, verify]);

  // ------------------------------------------------------------------ chargement et reprise
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [catalog, state, fresh] = await Promise.all([
          get<Paginated<Category> | Category[]>("/catalog/").catch(() => [] as Category[]),
          get<OnbState>("/me/onboarding/"),
          refreshUser().catch(() => null),
        ]);
        const account = fresh ?? user;
        if (!alive) return;
        setTrades(resolveTrades(Array.isArray(catalog) ? catalog : catalog.results ?? []));
        const me = account?.id ?? null;
        ownerRef.current = me;
        // Réponses gardées sur cet appareil pour CE compte (réseau coupé, session expirée) : plus récentes que le serveur, renvoyées.
        const pending = me !== null ? takePending(vault, me) : null;
        const d = pending ?? draftFromState(state);
        if (pending) void save(pending).catch(() => undefined);
        const cfg = d.trade ? await get<OnbConfig>(`/onboarding/config/?trade=${d.trade}`).catch(() => null) : null;
        if (!alive) return;
        setServer(state);
        setDraft(d);
        setConfig(cfg);
        setOtherCity(Boolean(d.commune) && Boolean(cfg) && !cfg!.communes.includes(d.commune));
        setStep(resumeStep(cfg, params.get("step") || d.step, { verify: !(account?.is_verified ?? false) }));
      } catch (e) {
        if (alive) setError(apiErrorMessage(e, "Votre inscription n’a pas pu être chargée. Vérifiez votre connexion puis rechargez la page."));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
    // Chargement unique à l'ouverture (la reprise lit l'écran demandé dans l'adresse).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ------------------------------------------------------------------ sauvegarde (à chaque réponse)
  // Enregistrements UN PAR UN, dans l'ordre (réseau lent : une ancienne réponse n'écrase jamais une plus récente), toujours pour le
  // compte propriétaire. Échec : les réponses restent sur cet appareil, rattachées à ce compte, et repartent au prochain envoi réussi.
  const save = useCallback((d: OnbDraft): Promise<OnbState> => {
    const owner = ownerRef.current;
    const body = JSON.stringify({ ...d, path: "guided" });
    const run = chain.current.catch(() => undefined).then(async () => {
      if (owner === null || stoppedRef.current) throw new Error("Session terminée : vos réponses sont gardées sur cet appareil.");
      try {
        const s = await apiJson<OnbState>("/me/onboarding/", { method: "PUT", body });
        vault.del(owner, PENDING_NAME);
        setKept("");
        setServer(s);
        return s;
      } catch (e) {
        keepPending(vault, owner, d);
        setKept(e instanceof ApiError && e.status === 401 ? "expired" : "offline");
        throw e;
      }
    });
    chain.current = run;
    return run;
  }, []);

  const persist = useCallback(
    (d: OnbDraft) => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      if (stoppedRef.current) return;
      saveTimer.current = setTimeout(() => void save(d).catch(() => undefined), 500);
    },
    [save],
  );

  useEffect(() => () => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
  }, []);

  // Retour du réseau : les réponses gardées repartent sans attendre une nouvelle réponse.
  useEffect(() => {
    const retry = () => {
      if (ownerRef.current !== null && !stoppedRef.current) void save(draftRef.current).catch(() => undefined);
    };
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [save]);

  // Autre compte ou déconnexion pendant le parcours : plus rien n'est envoyé ; les réponses restent pour LEUR compte, sur cet appareil.
  useEffect(() => {
    if (loading || ownerRef.current === null || stoppedRef.current) return;
    if ((user?.id ?? null) === ownerRef.current) return;
    stoppedRef.current = true;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    keepPending(vault, ownerRef.current, draftRef.current);
    voice.stop();
    setSessionChanged(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, loading]);

  const update = (patchDraft: Partial<OnbDraft>) => {
    const d = { ...draft, ...patchDraft, step };
    setDraft(d);
    persist(d);
  };

  // ------------------------------------------------------------------ voix
  const question = (s: string): OnbQuestion | undefined => (s.startsWith("q:") ? config?.questions.find((q) => `q:${q.key}` === s) : undefined);

  const speech = (s: string): string => {
    const q = question(s);
    if (q) return `${q.text} ${q.help} ${q.options.length <= 7 ? `Les réponses possibles : ${q.options.map((o) => o.label).join(", ")}.` : ""}`;
    const offer = server?.offer;
    const left = remainingAtEnd(server);
    return {
      intro: "Bienvenue ! Nous allons créer votre annonce ensemble, pas à pas. Cliquez sur les gros boutons pour répondre. Le bouton haut-parleur relit la question.",
      trade: "Quel est votre métier ? Cliquez sur la carte de votre métier.",
      prestations: "Que proposez-vous exactement ? Choisissez une ou plusieurs réponses.",
      commune: "Dans quelle commune travaillez-vous ?",
      quartier: "Dans quel quartier ? Vous pouvez aussi passer cette question.",
      preview: offer ? `Voici votre annonce. ${offer.title}. ${offer.description} Si elle vous convient, cliquez sur « Mon annonce me convient ».` : "Voici votre annonce.",
      verify: "Confirmez votre numéro de téléphone : nous vous envoyons un code par SMS.",
      photo: "Ajoutez une photo de votre visage, bien éclairée. Les clients aiment voir à qui ils confient leur maison.",
      identity: "Dernière étape : photographiez votre carte d’identité ou votre passeport. L’équipe Tratra la vérifie.",
      done: left.length ? `Votre annonce est enregistrée. Il vous reste à ${left.join(" et ")}.` : "Bravo ! Votre annonce sera visible dès que l’équipe Tratra aura vérifié votre dossier.",
    }[s] ?? "";
  };

  const lastSpoken = useRef("");
  useEffect(() => {
    if (loading || !voice.autoplay || lastSpoken.current === step) return;
    lastSpoken.current = step;
    voice.say(speech(step));
    // La voix suit l'écran affiché ; `speech` dépend de l'état courant.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, loading, voice.autoplay, voice.available]);

  // ------------------------------------------------------------------ navigation
  const go = (s: string) => {
    voice.stop();
    setError("");
    setStep(s);
    const d = { ...draft, step: s };
    setDraft(d);
    persist(d);
    window.history.replaceState(null, "", `${GUIDED_PATH}?step=${encodeURIComponent(s)}`); // un rechargement rouvre CET écran
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (s === "done") void get<OnbState>("/me/onboarding/").then(setServer).catch(() => undefined);
  };

  const back = () => {
    const prev = previousStep(config, step, { verify });
    if (prev) go(prev);
    else router.push("/dashboard/provide");
  };

  async function run(action: () => Promise<void>) {
    if (busyRef.current || stoppedRef.current) return;      // réseau lent : un seul envoi pour plusieurs clics
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? "Votre session a expiré. Vos réponses sont gardées sur cet appareil : reconnectez-vous pour continuer."
          : apiErrorMessage(e, "Une erreur est survenue. Vérifiez votre connexion puis réessayez. Vos réponses sont gardées."),
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function pickTrade(t: ResolvedTrade) {
    if (draft.trade === t.id && config) return;
    await run(async () => {
      const cfg = await get<OnbConfig>(`/onboarding/config/?trade=${t.id}`);
      setConfig(cfg);
      update({ trade: t.id, prestations: [], answers: {} });
    });
  }

  async function next() {
    await run(async () => {
      if (step === "preview") {
        if (saveTimer.current) clearTimeout(saveTimer.current);
        await save({ ...draft, step });
        setServer(await post<OnbState>("/me/onboarding/apply/"));   // profil et annonce créés par le serveur, jamais publiés avant la vérification
        await reloadDashboard();
      }
      if (step === "quartier" || step === "trade" || step.startsWith("q:")) {
        if (saveTimer.current) clearTimeout(saveTimer.current);
        const s = await save({ ...draft, step });
        if (nextStep(config, step, { verify }) === "preview") setServer(s);
      }
      go(nextStep(config, step, { verify }));
    });
  }

  async function uploadPhoto(file: File) {
    await run(async () => {
      const id = dash?.provider?.profile_id;
      if (!id) throw new Error("Créez d’abord votre annonce.");
      const form = new FormData();
      form.append("photo", file);
      await patchForm(`/handymen/${id}/`, form);
      await reloadDashboard();
      go("identity");
    });
  }

  async function toClassic() {
    voice.stop();
    await run(async () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      if (draft.trade) await save({ ...draft, step });
      try {
        await post("/me/onboarding/apply/");                       // réponses déjà données : reprises dans le profil
      } catch {
        await post("/me/handyman-profile/");                       // parcours à peine commencé : profil vide, comme l'inscription classique
      }
      await reloadDashboard();
      router.push("/dashboard/profile");
    });
  }

  const canContinue = (() => {
    const q = question(step);
    if (q) return answered(q, draft.answers);
    if (step === "trade") return Boolean(draft.trade && config);
    if (step === "prestations") return draft.prestations.length > 0;
    if (step === "commune") return draft.commune.trim().length > 1;
    return true;
  })();

  if (loading) return <Skeleton className="h-[28rem] !rounded-card" />;

  // ------------------------------------------------------------------ écrans
  const q = question(step);
  const shown = allTrades ? trades : featuredTrades(trades, 8);
  const left = remainingAtEnd(server);
  const minimum = minimumFor(config, draft.prestations);
  const declared = declaredExperience(config, draft.answers);
  const blocked = server?.experience?.ok === false;
  const progress = progressOf(steps, step);

  if (sessionChanged) {
    return (
      <Card className="mx-auto max-w-2xl" padding="lg">
        <Illustration icon={LockKeyhole} />
        <Title help="Vos réponses sont gardées sur cet appareil pour le compte avec lequel vous aviez commencé. Elles ne sont ni montrées ni envoyées à un autre compte. Reconnectez-vous avec ce compte pour continuer.">
          Votre session a changé
        </Title>
        <ButtonLink href={user ? "/dashboard" : `/login?next=${encodeURIComponent(GUIDED_PATH)}`} size="lg" block>
          {user ? "Aller à mon espace" : "Me reconnecter"}
        </ButtonLink>
      </Card>
    );
  }

  let content: ReactNode;
  if (q) {
    content = (
      <>
        <Title help={q.help || (q.kind === "multi" ? "Vous pouvez en choisir plusieurs." : undefined)}>{q.text}</Title>
        {q.target === "experience" ? (
          // La réponse est enregistrée telle quelle (jamais arrondie) ; le minimum du métier est annoncé AVANT de répondre.
          <Alert tone="info" className="mb-4">
            {minimum.years > 0
              ? `Pour ${minimum.name}, Tratra demande au moins ${minimum.years} an${minimum.years > 1 ? "s" : ""} d’expérience pour publier une offre. Répondez selon la vérité : votre réponse est enregistrée telle quelle.`
              : "Vous débutez ? C’est accepté pour ce métier. Répondez selon la vérité : votre réponse est enregistrée telle quelle."}
          </Alert>
        ) : null}
        <div className="space-y-2.5" role={q.kind === "multi" ? "group" : "radiogroup"} aria-label={q.text}>
          {q.options.map((o) => (
            <Choice
              key={o.value}
              label={o.label}
              emoji={o.emoji}
              multi={q.kind === "multi"}
              selected={q.kind === "multi" ? ((draft.answers[q.key] as string[] | undefined) ?? []).includes(o.value) : draft.answers[q.key] === o.value}
              onClick={() => update({ answers: toggleAnswer(q, draft.answers, o.value) })}
            />
          ))}
        </div>
      </>
    );
  } else if (step === "intro") {
    content = (
      <>
        <Title help="Quelques questions simples, une à la fois. Il suffit de cliquer sur les gros boutons. Votre progression est enregistrée : vous pourrez continuer plus tard, ici ou dans l’application.">
          Proposez vos services, pas à pas
        </Title>
        <Illustration icon={BadgeCheck} />
        {voice.available ? <Reassurance>Une voix lit chaque question. Le bouton haut-parleur la relit.</Reassurance> : null}
        <Reassurance>Rien n’est publié avant que l’équipe Tratra ait vérifié votre identité.</Reassurance>
      </>
    );
  } else if (step === "trade") {
    content = (
      <>
        <Title help="Cliquez sur la carte de votre métier.">Quel est votre métier ?</Title>
        {trades.length === 0 ? (
          <Alert tone="warning">Le catalogue des métiers n’a pas pu être chargé. Vérifiez votre connexion.</Alert>
        ) : (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {shown.map((t) => (
              <button
                key={t.id}
                type="button"
                aria-pressed={draft.trade === t.id}
                onClick={() => void pickTrade(t)}
                className={cx(
                  "flex min-h-[112px] flex-col items-center justify-center gap-2 rounded-panel border bg-white p-3 text-center transition",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
                  draft.trade === t.id ? "border-2 border-primary bg-primarySoft" : "border-line hover:border-primary/50",
                )}
              >
                <t.icon aria-hidden className="h-8 w-8 text-primary" />
                <span className="line-clamp-2 font-bold text-ink">{t.label}</span>
              </button>
            ))}
          </div>
        )}
        {!allTrades && trades.length > shown.length ? (
          <Button variant="ghost" className="mt-3" onClick={() => setAllTrades(true)}>
            Mon métier n’est pas dans la liste
          </Button>
        ) : null}
      </>
    );
  } else if (step === "prestations" && config) {
    content = (
      <>
        <Title help="Choisissez une ou plusieurs réponses.">Que proposez-vous exactement ?</Title>
        <div className="space-y-2.5" role="group" aria-label="Prestations">
          {config.prestations.map((p) => (
            <Choice
              key={p.id}
              label={p.name}
              multi
              selected={draft.prestations.includes(p.id)}
              onClick={() =>
                update({ prestations: draft.prestations.includes(p.id) ? draft.prestations.filter((x) => x !== p.id) : [...draft.prestations, p.id] })
              }
            />
          ))}
        </div>
      </>
    );
  } else if (step === "commune") {
    content = (
      <>
        <Title>Dans quelle commune travaillez-vous ?</Title>
        <div className="flex flex-wrap gap-2.5">
          {(config?.communes ?? []).map((c) => (
            <Pill
              key={c}
              label={c}
              selected={!otherCity && draft.commune === c}
              onClick={() => {
                setOtherCity(false);
                update({ commune: c });
              }}
            />
          ))}
          <Pill label="Autre ville" selected={otherCity} onClick={() => setOtherCity(true)} />
        </div>
        {otherCity ? (
          <TextField
            fieldClassName="mt-4"
            label="Ville ou commune"
            value={draft.commune}
            autoCapitalize="words"
            onChange={(e) => update({ commune: e.target.value })}
          />
        ) : null}
      </>
    );
  } else if (step === "quartier") {
    content = (
      <>
        <Title help="Facultatif : cela aide les clients proches à vous trouver.">Dans quel quartier ?</Title>
        <TextField label="Quartier" placeholder="Ex. Riviera 2" value={draft.quartier} autoCapitalize="words" onChange={(e) => update({ quartier: e.target.value })} />
      </>
    );
  } else if (step === "preview") {
    content = (
      <>
        <Title help="Écrite à partir de vos réponses. Vous pourrez la modifier plus tard.">Votre annonce</Title>
        {server?.offer ? (
          <Card>
            <h2 className="font-display text-xl font-extrabold text-ink">{server.offer.title}</h2>
            {server.offer.price && server.offer.price_type !== "quote" ? (
              <Badge tone="primary" className="mt-2">
                {new Intl.NumberFormat("fr-FR").format(server.offer.price)} FCFA {server.offer.price_type === "hourly" ? "de l’heure" : "par intervention"}
              </Badge>
            ) : null}
            <p className="mt-3 whitespace-pre-line text-base leading-relaxed text-inkSoft">{server.offer.description.replace(/\. /g, ".\n")}</p>
          </Card>
        ) : (
          <Skeleton className="h-40 !rounded-card" />
        )}
        {declared && declared.years < minimum.years ? (
          <Alert tone="warning" className="mt-4">
            Avec « {declared.label} », votre annonce ne pourra pas être publiée : {minimum.name} demande au moins {minimum.years} an
            {minimum.years > 1 ? "s" : ""} d’expérience. Vos réponses sont gardées telles quelles ; vous pourrez la publier quand vous aurez
            l’expérience requise.
          </Alert>
        ) : null}
        <Reassurance>Elle sera visible des clients après la vérification de votre identité par l’équipe Tratra.</Reassurance>
        <Button variant="ghost" className="mt-2" onClick={() => go(resumeStep(config, "questions", { verify }))}>
          Changer mes réponses
        </Button>
      </>
    );
  } else if (step === "verify") {
    content = (
      <>
        <Title help="Nous vous envoyons un code par SMS. Saisissez-le sur la page suivante : vous revenez ensuite ici.">Confirmez votre numéro</Title>
        <Illustration icon={Smartphone} />
      </>
    );
  } else if (step === "photo") {
    content = (
      <>
        <Title help="Visage bien éclairé, sans lunettes de soleil. Les clients aiment savoir à qui ils ouvrent leur porte.">Votre photo</Title>
        <Illustration icon={Camera} />
        <input
          ref={photoRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="user"
          className="sr-only"
          aria-label="Choisir une photo"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void uploadPhoto(f);
            e.target.value = "";
          }}
        />
      </>
    );
  } else if (step === "identity") {
    content = (
      <>
        <Title help="Photographiez votre carte d’identité (recto et verso) ou votre passeport. L’équipe Tratra la vérifie : votre annonce devient visible après sa validation.">
          Vérifier votre identité
        </Title>
        <GuidedIdentity onFinished={() => go("done")} onLater={() => go("done")} />
        <Reassurance>Vos papiers restent privés : seuls vous et l’équipe Tratra les voyez.</Reassurance>
      </>
    );
  } else {
    content = (
      <>
        <Title
          help={
            left.length
              ? `Il vous reste à ${left.join(" et ")}. Votre annonce ne sera visible qu’après la vérification de votre identité. Vous pourrez continuer depuis votre espace avec le bouton « Continuer ».`
              : blocked
                ? "Elle ne pourra pas être publiée tant que votre expérience n’atteint pas le minimum demandé pour ce métier. Votre réponse est gardée telle quelle ; le détail est dans votre espace."
                : "Votre annonce est prête. Elle sera visible dès que l’équipe Tratra aura vérifié votre dossier. Vous recevrez une notification."
          }
        >
          {left.length || blocked ? "Votre annonce est enregistrée" : "Bravo, c’est presque fini !"}
        </Title>
        <Illustration icon={left.length || blocked ? BadgeCheck : PartyPopper} />
      </>
    );
  }

  const primary: { label: string; onClick?: () => void; href?: string } | null = (() => {
    switch (step) {
      case "intro":
        return { label: "Commencer", onClick: () => go(nextStep(config, step, { verify })) };
      case "preview":
        return { label: "Mon annonce me convient", onClick: () => void next() };
      case "verify":
        return { label: "Recevoir le code", href: `/verify-phone?auto=1&next=${encodeURIComponent(`${GUIDED_PATH}?step=photo`)}` };
      case "photo":
        return { label: "Ajouter ma photo", onClick: () => photoRef.current?.click() };
      case "identity":
        return null;                                                  // boutons propres à la vérification guidée
      case "done":
        return { label: "Aller à mon espace", href: "/dashboard" };
      default:
        return { label: "Continuer", onClick: () => void next() };
    }
  })();

  const secondary: { label: string; onClick: () => void } | null =
    step === "quartier"
      ? { label: "Passer", onClick: () => void next() }
      : step === "verify" || step === "photo"
        ? { label: "Plus tard", onClick: () => go(nextStep(config, step, { verify })) }
        : null;                                                       // identité : « Plus tard » est dans la vérification guidée

  return (
    <div className="mx-auto w-full max-w-2xl">
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" aria-label="Retour" disabled={busy} onClick={back}>
          <ArrowLeft aria-hidden className="h-5 w-5" />
        </Button>
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-inkSoft" aria-live="polite" title={progress.title}>
          {progress.title}
        </p>
        {voice.available ? (
          <>
            <Button variant="ghost" size="sm" aria-label="Réécouter" onClick={() => voice.say(speech(step))}>
              {voice.speaking ? <Volume2 aria-hidden className="h-5 w-5 text-primary" /> : <RotateCcw aria-hidden className="h-5 w-5 text-primary" />}
            </Button>
            <Button variant="ghost" size="sm" aria-label={voice.autoplay ? "Couper la voix" : "Activer la voix"} onClick={() => voice.setAutoplay(!voice.autoplay)}>
              {voice.autoplay ? <Volume2 aria-hidden className="h-5 w-5" /> : <VolumeX aria-hidden className="h-5 w-5" />}
            </Button>
          </>
        ) : null}
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-lineSoft" role="progressbar" aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={Math.round(progress.ratio * 100)} aria-valuetext={progress.title} aria-label="Progression">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progress.ratio * 100}%` }} />
      </div>

      <Card className="mt-5" padding="lg">
        {kept ? (
          <Alert tone="warning" className="mb-4">
            {kept === "expired"
              ? "Votre session a expiré : vos réponses sont gardées sur cet appareil. Reconnectez-vous pour continuer."
              : "Pas de connexion pour l’instant : vos réponses sont gardées sur cet appareil et seront envoyées dès le retour du réseau."}
          </Alert>
        ) : null}
        {content}
        {error ? (
          <Alert tone="danger" className="mt-4">
            {error}
          </Alert>
        ) : null}
        <div className="mt-6 space-y-2">
          {primary === null ? null : primary.href ? (
            <ButtonLink href={primary.href} size="lg" block>
              {primary.label}
            </ButtonLink>
          ) : (
            <Button size="lg" block loading={busy} disabled={!canContinue} onClick={primary.onClick}>
              {primary.label}
            </Button>
          )}
          {secondary ? (
            <Button variant="ghost" size="lg" block disabled={busy} onClick={secondary.onClick}>
              {secondary.label}
            </Button>
          ) : null}
        </div>
      </Card>
      {step !== "done" ? (
        <p className="mt-4 text-center">
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void toClassic()}>
            Passer au formulaire classique
          </Button>
        </p>
      ) : null}
    </div>
  );
}

export default function GuidedOnboardingPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[28rem] !rounded-card" />}>
      <GuidedFlow />
    </Suspense>
  );
}
