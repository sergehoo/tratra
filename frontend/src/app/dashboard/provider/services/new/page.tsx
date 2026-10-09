"use client";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { apiErrorMessage, post } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard";
import { useData } from "@/lib/useData";
import type { Category, Paginated } from "@/lib/types";
import { Alert, Button, Card, PageHeader, SelectField, Skeleton, TextField, TextareaField } from "@/components/ds";

export default function NewServicePage() {
  const router = useRouter();
  const dash = useDashboard();
  const cats = useData<Paginated<Category>>("/categories/?page_size=100&ordering=name");
  const [f, setF] = useState({ title: "", description: "", category: "", price_type: "fixed", price: "", duration: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  const noProfile = !dash.loading && dash.data !== null && !dash.data.capabilities.provider;
  useEffect(() => {
    if (noProfile) router.replace("/dashboard/provide");
  }, [noProfile, router]);

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!f.title.trim()) next.title = "Donnez un titre à votre service.";
    if (!f.category) next.category = "Choisissez un métier.";
    if (!f.description.trim()) next.description = "Décrivez le service proposé.";
    if (f.price_type !== "quote" && !(Number(f.price) > 0)) next.price = "Indiquez un tarif supérieur à 0.";
    setErrors(next);
    if (Object.keys(next).length) return;
    setBusy(true);
    setFailure("");
    try {
      await post("/services/", {
        title: f.title.trim(),
        description: f.description.trim(),
        category: Number(f.category),
        price_type: f.price_type,
        ...(f.price_type !== "quote" ? { price: f.price } : {}),
        ...(Number(f.duration) > 0 ? { duration: Number(f.duration) } : {}),
      });
      router.push("/dashboard/provider");
    } catch (err) {
      setFailure(apiErrorMessage(err, "Le service n’a pas pu être créé. Vérifiez les informations saisies."));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Ajouter un service"
        description="Il sera visible des clients dès que votre profil est complet et validé."
        back={{ href: "/dashboard/provider", label: "Mes prestations" }}
      />
      {cats.loading ? (
        <Skeleton className="h-96 !rounded-card" />
      ) : (
        <Card className="max-w-2xl">
          <form onSubmit={submit} noValidate className="space-y-5">
            {failure ? <Alert tone="danger">{failure}</Alert> : null}
            <TextField label="Titre du service" required value={f.title} onChange={set("title")} error={errors.title} maxLength={120}
              placeholder="Ex. Dépannage de fuite d’eau" />
            <SelectField label="Métier" required value={f.category} onChange={set("category")} error={errors.category}>
              <option value="" disabled>Choisir un métier…</option>
              {(cats.data?.results ?? []).filter((c) => c.is_active !== false).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </SelectField>
            <TextareaField label="Description" required rows={5} value={f.description} onChange={set("description")} error={errors.description}
              hint="Ce que vous faites, le matériel fourni, vos conditions." />
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              <SelectField label="Type de tarif" value={f.price_type} onChange={set("price_type")}>
                <option value="fixed">Tarif fixe</option>
                <option value="hourly">À l’heure</option>
                <option value="quote">Sur devis</option>
              </SelectField>
              {f.price_type !== "quote" ? (
                <TextField label={f.price_type === "hourly" ? "Tarif horaire (FCFA)" : "Tarif (FCFA)"} required inputMode="numeric"
                  value={f.price} onChange={set("price")} error={errors.price} placeholder="15000" />
              ) : null}
            </div>
            <TextField label="Durée estimée (minutes)" optional inputMode="numeric" value={f.duration} onChange={set("duration")} placeholder="90" />
            <div className="flex flex-wrap gap-3 pt-1">
              <Button type="submit" size="lg" loading={busy}>Enregistrer le service</Button>
              <Button type="button" variant="outline" size="lg" onClick={() => router.push("/dashboard/provider")}>Annuler</Button>
            </div>
          </form>
        </Card>
      )}
    </>
  );
}
