"use client";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Building2 } from "lucide-react";
import { ApiError, apiErrorMessage, post } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard";
import { Alert, BackLink, Button, Card, PageHeader, TextField } from "@/components/ds";

const FIELDS = ["company_name", "industry", "city", "contact_person", "registration_number"] as const;
type Field = (typeof FIELDS)[number];

/** Créer un espace entreprise = une organisation liée au compte courant (aucun second compte). */
export default function NewCompanyPage() {
  const { data, reload } = useDashboard();
  const router = useRouter();
  const [f, setF] = useState<Record<Field, string>>({ company_name: "", industry: "", city: "", contact_person: "", registration_number: "" });
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  // Une organisation existe déjà pour ce compte : on ouvre directement son espace.
  useEffect(() => {
    if (data?.capabilities.company) router.replace("/company");
  }, [data, router]);

  const set = (k: Field) => (e: { target: { value: string } }) => {
    setF((s) => ({ ...s, [k]: e.target.value }));
    setErrors((x) => ({ ...x, [k]: undefined }));
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setFailure("");
    if (!f.company_name.trim()) {
      setErrors({ company_name: "Indiquez le nom de l’entreprise." });
      return;
    }
    setBusy(true);
    try {
      await post("/companies/me/", Object.fromEntries(FIELDS.map((k) => [k, f[k].trim()]).filter(([, v]) => v)));
      await reload();
      router.push("/company");
    } catch (err) {
      if (err instanceof ApiError && err.status === 400 && err.data && typeof err.data === "object") {
        const next: Partial<Record<Field, string>> = {};
        for (const k of FIELDS) {
          const raw = (err.data as Record<string, unknown>)[k];
          const text = Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string").join(" ") : typeof raw === "string" ? raw : "";
          if (text) next[k] = text;
        }
        setErrors(next);
      }
      setFailure(apiErrorMessage(err, "L’espace entreprise n’a pas pu être créé. Réessayez dans un instant."));
      setBusy(false);
    }
  }

  return (
    <>
      <BackLink href="/dashboard">Tableau de bord</BackLink>
      <PageHeader title="Créer un espace entreprise" description="Une organisation rattachée à votre compte actuel : vous gardez vos réservations, vos messages et votre portefeuille." />
      <Card className="max-w-2xl">
        <form onSubmit={submit} className="space-y-5" noValidate>
          <TextField label="Nom de l’entreprise" required name="company_name" autoComplete="organization" value={f.company_name} onChange={set("company_name")} error={errors.company_name} />
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="Secteur d’activité" optional name="industry" value={f.industry} onChange={set("industry")} error={errors.industry} />
            <TextField label="Ville" optional name="city" autoComplete="address-level2" value={f.city} onChange={set("city")} error={errors.city} />
            <TextField label="Personne à contacter" optional name="contact_person" value={f.contact_person} onChange={set("contact_person")} error={errors.contact_person} />
            <TextField label="N° d’immatriculation" optional name="registration_number" value={f.registration_number} onChange={set("registration_number")} error={errors.registration_number} />
          </div>
          {failure ? <Alert tone="danger">{failure}</Alert> : null}
          <Button type="submit" size="lg" loading={busy} leftIcon={<Building2 aria-hidden className="h-5 w-5" />}>
            Créer l’espace entreprise
          </Button>
        </form>
      </Card>
    </>
  );
}
