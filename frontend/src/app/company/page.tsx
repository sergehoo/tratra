"use client";
import { useCallback, useEffect, useState } from "react";
import { m } from "framer-motion";
import { ArrowRight, BadgeCheck, BadgeDollarSign, Save } from "lucide-react";
import { ApiError, apiErrorMessage, get, post } from "@/lib/api";
import { statusView } from "@/lib/status";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Skeleton,
  StatusBadge,
  TextField,
  fadeUp,
} from "@/components/ds";
import { intervalView, longDate, planPrice, stagger } from "./_lib/format";

interface Company {
  company_name?: string;
  registration_number?: string;
  industry?: string;
  city?: string;
  contact_person?: string;
  phone?: string;
  website?: string;
  verified?: boolean;
}
interface Sub {
  active?: boolean;
  status?: string;
  plan_detail?: { name: string; price: string; interval: string };
  started_at?: string;
  current_period_end?: string;
}

/** Champs du formulaire (ceux que l'API valide et renvoie champ par champ). */
const FORM_FIELDS = [
  "company_name",
  "registration_number",
  "industry",
  "city",
  "contact_person",
  "phone",
  "website",
] as const;
type FormField = (typeof FORM_FIELDS)[number];
type FieldErrors = Partial<Record<FormField, string>>;

/** Rattache les erreurs de validation de l'API (400) au champ concerné ; sinon message général. */
function readSaveError(err: unknown): { fields: FieldErrors; message: string } {
  if (err instanceof ApiError && err.status === 400 && err.data && typeof err.data === "object" && !Array.isArray(err.data)) {
    const data = err.data as Record<string, unknown>;
    const fields: FieldErrors = {};
    for (const key of FORM_FIELDS) {
      const raw = data[key];
      const text = Array.isArray(raw)
        ? raw.filter((x): x is string => typeof x === "string").join(" ")
        : typeof raw === "string"
          ? raw
          : "";
      if (text) fields[key] = text;
    }
    if (Object.keys(fields).length > 0) {
      return {
        fields,
        message: "Certaines informations sont invalides. Corrigez les champs signalés puis enregistrez à nouveau.",
      };
    }
  }
  return {
    fields: {},
    message: apiErrorMessage(err, "Impossible d’enregistrer le profil pour le moment. Réessayez dans un instant."),
  };
}

function SubscriptionPanel({ sub, failed, onRetry }: { sub: Sub | null; failed: boolean; onRetry: () => void }) {
  if (failed && !sub) {
    return (
      <Card>
        <CardHeader title="Abonnement" />
        <Alert
          tone="warning"
          title="Abonnement indisponible"
          action={
            <Button size="sm" variant="outline" onClick={onRetry}>
              Réessayer
            </Button>
          }
        >
          Impossible de récupérer l’état de votre abonnement pour le moment.
        </Alert>
      </Card>
    );
  }

  if (!(sub && sub.active !== false)) {
    return (
      <Card>
        <CardHeader title="Abonnement" />
        <EmptyState
          compact
          icon={<BadgeDollarSign aria-hidden />}
          title="Aucun abonnement actif"
          description="Votre entreprise n’a pas d’abonnement en cours. Consultez les offres B2B disponibles."
          actions={
            <ButtonLink href="/company/plans" rightIcon={<ArrowRight aria-hidden className="h-4 w-4" />}>
              Voir les offres B2B
            </ButtonLink>
          }
        />
      </Card>
    );
  }

  const plan = sub.plan_detail;
  const interval = intervalView(plan?.interval);
  const price = planPrice(plan?.price);
  const started = longDate(sub.started_at);
  const until = longDate(sub.current_period_end);

  return (
    <Card variant="night" className="relative isolate overflow-hidden">
      <div aria-hidden className="absolute -right-16 -top-16 -z-10 h-48 w-48 rounded-full bg-accent/15 blur-3xl" />
      <CardHeader title="Abonnement" action={<StatusBadge kind="subscription" status={sub.status} />} />
      <p className="font-display text-2xl font-extrabold leading-tight tracking-tight">
        {plan?.name ?? statusView("subscription", sub.status).label}
      </p>
      {price ? (
        <p className="mt-1.5 text-sm text-white/70">
          <span className="font-semibold text-accent">{price}</span>
          {interval && Number(plan?.price) > 0 ? ` ${interval.per}` : null}
        </p>
      ) : null}
      {started || until ? (
        <dl className="mt-5 space-y-3 border-t border-white/10 pt-5 text-sm">
          {started ? (
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-white/70">Souscrit le</dt>
              <dd className="text-right font-semibold">
                <time dateTime={sub.started_at}>{started}</time>
              </dd>
            </div>
          ) : null}
          {until ? (
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-white/70">Valable jusqu’au</dt>
              <dd className="text-right font-semibold">
                <time dateTime={sub.current_period_end}>{until}</time>
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </Card>
  );
}

export default function CompanyHome() {
  const [c, setC] = useState<Company>({});
  const [sub, setSub] = useState<Sub | null>(null);
  const [loading, setLoading] = useState(true);
  const [profileError, setProfileError] = useState(false);
  const [subError, setSubError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  const set = (k: FormField) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setC((s) => ({ ...s, [k]: value }));
    setFieldErrors((s) => (s[k] ? { ...s, [k]: undefined } : s));
  };

  const loadProfile = useCallback(
    () =>
      get<Company>("/companies/me/")
        .then((d) => {
          setC(d || {});
          setProfileError(false);
        })
        .catch(() => setProfileError(true)),
    [],
  );
  const loadSub = useCallback(
    () =>
      get<Sub>("/subscriptions/current/")
        .then((d) => {
          setSub(d);
          setSubError(false);
        })
        .catch(() => setSubError(true)),
    [],
  );

  useEffect(() => {
    Promise.all([loadProfile(), loadSub()]).finally(() => setLoading(false));
  }, [loadProfile, loadSub]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaved(false);
    setSaveError(null);
    setFieldErrors({});
    setSaving(true);
    try {
      const updated = await post<Company>("/companies/me/", c);
      setC(updated);
      setSaved(true);
    } catch (err) {
      const { fields, message } = readSaveError(err);
      setFieldErrors(fields);
      setSaveError(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Espace entreprise"
        title="Profil & abonnement"
        description="Renseignez les informations de votre entreprise et suivez votre abonnement B2B."
      />

      {loading ? (
        <div role="status" aria-label="Chargement en cours" className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Skeleton className="h-[30rem] !rounded-card lg:col-span-2" />
          <Skeleton className="h-64 !rounded-card" />
          <span className="sr-only">Chargement…</span>
        </div>
      ) : (
        <m.div variants={stagger} initial="hidden" animate="show" className="grid grid-cols-1 items-start gap-6 lg:grid-cols-3">
          <m.div variants={fadeUp} className="lg:col-span-2">
            <Card>
              <CardHeader
                title="Informations de l’entreprise"
                description="Le statut de vérification est attribué par l’équipe Tratra ; il ne se modifie pas ici."
                action={
                  // Statut inconnu si le profil n'a pas pu être chargé : aucun badge plutôt qu'un faux « Non vérifié ».
                  profileError ? undefined : c.verified ? (
                    <Badge tone="success" icon={<BadgeCheck />}>
                      Vérifié
                    </Badge>
                  ) : (
                    <Badge tone="gray">Non vérifié</Badge>
                  )
                }
              />

              {profileError ? (
                <Alert
                  tone="danger"
                  title="Profil indisponible"
                  className="mb-5"
                  action={
                    <Button size="sm" variant="outline" onClick={() => void loadProfile()}>
                      Réessayer
                    </Button>
                  }
                >
                  Impossible de charger les informations enregistrées. Réessayez avant d’enregistrer, pour ne pas
                  remplacer vos données par un formulaire vide.
                </Alert>
              ) : null}

              <form onSubmit={save} className="grid gap-x-4 gap-y-5 sm:grid-cols-2">
                {/* Champ obligatoire côté API : signalé (astérisque + aria-required) sans `required` natif,
                    pour que la validation reste celle de l'API (même comportement qu'avant). */}
                <Field label="Raison sociale" required error={fieldErrors.company_name}>
                  {(f) => (
                    <Input {...f} value={c.company_name ?? ""} onChange={set("company_name")} autoComplete="organization" />
                  )}
                </Field>
                <TextField
                  label="N° RCCM"
                  hint="Registre du commerce et du crédit mobilier"
                  value={c.registration_number ?? ""}
                  onChange={set("registration_number")}
                  error={fieldErrors.registration_number}
                />
                <TextField
                  label="Secteur d’activité"
                  value={c.industry ?? ""}
                  onChange={set("industry")}
                  error={fieldErrors.industry}
                />
                <TextField
                  label="Ville"
                  value={c.city ?? ""}
                  onChange={set("city")}
                  error={fieldErrors.city}
                  autoComplete="address-level2"
                />
                <TextField
                  label="Personne de contact"
                  value={c.contact_person ?? ""}
                  onChange={set("contact_person")}
                  error={fieldErrors.contact_person}
                  autoComplete="name"
                />
                <TextField
                  label="Téléphone"
                  type="tel"
                  inputMode="tel"
                  value={c.phone ?? ""}
                  onChange={set("phone")}
                  error={fieldErrors.phone}
                  autoComplete="tel"
                />
                <TextField
                  label="Site web"
                  hint="Adresse complète du site, en commençant par https://"
                  inputMode="url"
                  value={c.website ?? ""}
                  onChange={set("website")}
                  error={fieldErrors.website}
                  autoComplete="url"
                  fieldClassName="sm:col-span-2"
                />

                <div className="space-y-4 sm:col-span-2">
                  <Button type="submit" loading={saving} leftIcon={<Save aria-hidden className="h-4 w-4" />} className="w-full sm:w-auto">
                    Enregistrer
                  </Button>
                  {saved ? (
                    <Alert tone="success" title="Profil enregistré" onDismiss={() => setSaved(false)}>
                      Les informations de votre entreprise sont enregistrées.
                    </Alert>
                  ) : null}
                  {saveError ? (
                    <Alert tone="danger" title="Enregistrement impossible" onDismiss={() => setSaveError(null)}>
                      {saveError}
                    </Alert>
                  ) : null}
                </div>
              </form>
            </Card>
          </m.div>

          <m.div variants={fadeUp}>
            <SubscriptionPanel sub={sub} failed={subError} onRetry={() => void loadSub()} />
          </m.div>
        </m.div>
      )}
    </>
  );
}
