"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { BadgeCheck, CircleCheck, Circle, FileCheck2, Smartphone } from "lucide-react";
import { apiErrorMessage, patch } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDashboard } from "@/lib/dashboard";
import { useData } from "@/lib/useData";
import { patchForm } from "@/lib/uploadPatch";
import type { Category, Paginated } from "@/lib/types";
import {
  Alert, Avatar, Badge, Button, ButtonLink, Card, CardHeader, PageHeader, Skeleton, TextField, TextareaField, cx,
} from "@/components/ds";

interface ProProfile {
  id: number;
  bio: string | null;
  skills: number[];
  experience_years: number;
  commune: string | null;
  quartier: string | null;
  hourly_rate: string | null;
  photo: string | null;
}

const KYC = {
  none: { label: "Aucun document déposé", tone: "gray" },
  pending: { label: "En cours de vérification", tone: "accent" },
  approved: { label: "Identité vérifiée", tone: "success" },
  rejected: { label: "Document refusé", tone: "danger" },
} as const;

function ProForm({ profileId }: { profileId: number }) {
  const { reload } = useDashboard();
  const profile = useData<ProProfile>(`/handymen/${profileId}/`, "Votre profil professionnel ne peut pas être chargé.");
  const cats = useData<Paginated<Category>>("/categories/?page_size=100&ordering=name");
  const [f, setF] = useState({ bio: "", experience_years: "", commune: "", quartier: "", hourly_rate: "" });
  const [skills, setSkills] = useState<number[]>([]);
  const [photo, setPhoto] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [saved, setSaved] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const p = profile.data;
    if (!p) return;
    setF({
      bio: p.bio ?? "",
      experience_years: p.experience_years ? String(p.experience_years) : "",
      commune: p.commune ?? "",
      quartier: p.quartier ?? "",
      hourly_rate: p.hourly_rate && Number(p.hourly_rate) > 0 ? String(Number(p.hourly_rate)) : "",
    });
    setSkills(p.skills ?? []);
  }, [profile.data]);

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    setSaved(false);
    setF((s) => ({ ...s, [k]: e.target.value }));
  };

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFailure("");
    setSaved(false);
    try {
      await patch(`/handymen/${profileId}/`, {
        bio: f.bio.trim(),
        experience_years: Number(f.experience_years) || 0,
        commune: f.commune.trim(),
        quartier: f.quartier.trim(),
        hourly_rate: f.hourly_rate ? f.hourly_rate : 0,
        skills,
      });
      if (photo) {
        const form = new FormData();
        form.append("photo", photo);
        await patchForm(`/handymen/${profileId}/`, form);
        setPhoto(null);
        if (fileRef.current) fileRef.current.value = "";
      }
      await Promise.all([reload(), profile.reload()]);
      setSaved(true);
    } catch (err) {
      setFailure(apiErrorMessage(err, "L’enregistrement a échoué. Vérifiez les champs et réessayez."));
    } finally {
      setBusy(false);
    }
  }

  if (profile.loading || cats.loading) return <Skeleton className="h-96 !rounded-card" />;
  if (profile.error) return <Alert tone="danger" title="Profil indisponible" action={<Button size="sm" variant="outline" onClick={() => void profile.reload()}>Réessayer</Button>}>{profile.error}</Alert>;

  return (
    <Card>
      <CardHeader title="Profil professionnel" description="Ces informations sont visibles des clients." />
      <form onSubmit={save} noValidate className="space-y-5">
        <div className="flex items-center gap-4">
          <Avatar name="Photo" photo={profile.data?.photo} size={64} />
          <div className="min-w-0">
            <label htmlFor="photo" className="block text-sm font-semibold text-ink">Photo de profil</label>
            <input
              id="photo" ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp"
              onChange={(e) => { setPhoto(e.target.files?.[0] ?? null); setSaved(false); }}
              className="mt-1 block w-full max-w-xs text-sm text-inkSoft file:mr-3 file:rounded-full file:border-0 file:bg-primarySoft file:px-4 file:py-2 file:text-sm file:font-semibold file:text-primaryDark"
            />
          </div>
        </div>
        <TextareaField label="Présentation" rows={4} value={f.bio} onChange={set("bio")} hint="Votre activité, votre expérience, ce qui vous distingue." />
        <fieldset>
          <legend className="mb-2 text-sm font-semibold text-ink">Spécialités</legend>
          <div className="flex flex-wrap gap-2">
            {(cats.data?.results ?? []).filter((c) => c.is_active !== false).map((c) => {
              const on = skills.includes(c.id);
              return (
                <button
                  key={c.id} type="button" aria-pressed={on}
                  onClick={() => { setSaved(false); setSkills((s) => (on ? s.filter((x) => x !== c.id) : [...s, c.id])); }}
                  className={cx(
                    "min-h-[40px] rounded-full border px-3.5 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                    on ? "border-primary/50 bg-primarySoft text-primaryDark" : "border-line bg-white text-inkSoft hover:border-fog",
                  )}
                >
                  {c.name}
                </button>
              );
            })}
          </div>
        </fieldset>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <TextField label="Années d’expérience" inputMode="numeric" value={f.experience_years} onChange={set("experience_years")} />
          <TextField label="Tarif horaire indicatif (FCFA)" optional inputMode="numeric" value={f.hourly_rate} onChange={set("hourly_rate")} />
          <TextField label="Commune" value={f.commune} onChange={set("commune")} placeholder="Ex. Cocody" />
          <TextField label="Quartier" optional value={f.quartier} onChange={set("quartier")} />
        </div>
        {failure ? <Alert tone="danger">{failure}</Alert> : null}
        {saved ? <Alert tone="success">Profil enregistré.</Alert> : null}
        <Button type="submit" size="lg" loading={busy}>Enregistrer</Button>
      </form>
    </Card>
  );
}

/** E-mail FACULTATIF du compte (la connexion se fait par téléphone) : ajouté ou modifié après connexion. */
function EmailForm() {
  const { user, refreshUser } = useAuth();
  const [email, setEmail] = useState(user?.email ?? "");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState("");

  useEffect(() => setEmail(user?.email ?? ""), [user?.email]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    setBusy(true);
    setFailure("");
    setSaved(false);
    try {
      await patch(`/users/${user.id}/`, { email: email.trim() || null });
      await refreshUser();
      setSaved(true);
    } catch (err) {
      setFailure(apiErrorMessage(err, "L’adresse e-mail n’a pas pu être enregistrée. Vérifiez-la puis réessayez."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="mt-5 space-y-3" noValidate>
      <TextField
        label="Adresse e-mail"
        optional
        type="email"
        name="email"
        autoComplete="email"
        inputMode="email"
        value={email}
        onChange={(e) => { setEmail(e.target.value); setSaved(false); }}
        hint="Facultative : vous vous connectez avec votre numéro de téléphone."
      />
      {failure ? <Alert tone="danger">{failure}</Alert> : null}
      {saved ? <Alert tone="success">Adresse e-mail enregistrée.</Alert> : null}
      <Button type="submit" variant="outline" loading={busy} disabled={(user?.email ?? "") === email.trim()}>
        Enregistrer l’e-mail
      </Button>
    </form>
  );
}

export default function ProfilePage() {
  const { user } = useAuth();
  const { data, loading, error, reload } = useDashboard();
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.phone || "Mon compte";
  const provider = data?.provider ?? null;
  const kyc = provider ? KYC[provider.kyc.status] : null;

  return (
    <>
      <PageHeader title="Mon profil et KYC" description="Votre compte, votre profil professionnel et la vérification de votre identité." />
      {loading ? (
        <Skeleton className="h-96 !rounded-card" />
      ) : error || !data ? (
        <Alert tone="danger" title="Profil indisponible" action={<Button size="sm" variant="outline" onClick={() => void reload()}>Réessayer</Button>}>{error}</Alert>
      ) : (
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-3">
          <div className="min-w-0 space-y-6 lg:col-span-2">
            <Card>
              <div className="flex items-center gap-4">
                <Avatar name={name} size={64} />
                <div className="min-w-0">
                  <p className="truncate font-display text-xl font-extrabold text-ink">{name}</p>
                  {user?.email ? <p className="truncate text-sm text-ash">{user.email}</p> : user?.phone ? <p className="truncate text-sm text-ash">{user.phone}</p> : null}
                </div>
              </div>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-panel bg-canvas px-4 py-3">
                <span className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <Smartphone aria-hidden className="h-4 w-4 text-primary" />
                  {user?.phone ? user.phone : "Aucun numéro enregistré"}
                </span>
                {user?.phone ? (
                  data.user.is_verified ? (
                    <Badge tone="success" icon={<BadgeCheck />}>Vérifié</Badge>
                  ) : (
                    <ButtonLink href="/verify-phone?next=/dashboard/profile" size="sm" variant="outline">Vérifier mon numéro</ButtonLink>
                  )
                ) : null}
              </div>
              <EmailForm />
            </Card>
            {provider ? (
              <ProForm profileId={provider.profile_id} />
            ) : (
              <Card variant="soft">
                <h2 className="font-display text-lg font-extrabold text-ink">Vous n’avez pas de profil professionnel</h2>
                <p className="mt-1.5 text-sm text-inkSoft">Créez-le avec ce même compte pour proposer vos services.</p>
                <ButtonLink href="/dashboard/provide" className="mt-4">Proposer mes services</ButtonLink>
              </Card>
            )}
          </div>

          <div className="min-w-0 space-y-6">
            {provider && kyc ? (
              <>
                <Card>
                  <CardHeader title="Vérification d’identité" icon={<FileCheck2 className="h-5 w-5" />} />
                  <Badge tone={kyc.tone} dot>{kyc.label}</Badge>
                  {provider.kyc.status === "rejected" && provider.kyc.rejection_reason ? (
                    <Alert tone="danger" className="mt-3">{provider.kyc.rejection_reason}</Alert>
                  ) : null}
                  <p className="mt-3 text-sm text-ash">
                    {provider.kyc.status === "approved"
                      ? "Votre pièce d’identité est vérifiée."
                      : "Votre badge « Vérifié » n’apparaît qu’après validation effective par l’équipe Tratra."}
                  </p>
                  <ButtonLink href="/dashboard/profile/kyc" className="mt-4" variant={provider.kyc.status === "approved" ? "outline" : "primary"} block>
                    {provider.kyc.status === "approved" ? "Voir mes documents" : "Gérer mes documents"}
                  </ButtonLink>
                </Card>
                <Card>
                  <CardHeader title="Progression du dossier" description={`${provider.completion.done} / ${provider.completion.total} étapes`} />
                  <ul className="space-y-2.5">
                    {provider.completion.items.map((i) => (
                      <li key={i.key} className="flex items-start gap-2.5 text-sm">
                        {i.done ? (
                          <CircleCheck aria-hidden className="mt-0.5 h-[18px] w-[18px] shrink-0 text-success" />
                        ) : (
                          <Circle aria-hidden className="mt-0.5 h-[18px] w-[18px] shrink-0 text-fog" />
                        )}
                        <span>
                          <span className={cx("font-semibold", i.done ? "text-ink" : "text-inkSoft")}>{i.label}</span>
                          {!i.done ? <span className="block text-xs text-ash">{i.hint}</span> : null}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Card>
              </>
            ) : null}
          </div>
        </div>
      )}
    </>
  );
}
