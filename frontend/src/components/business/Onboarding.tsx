"use client";
import { useState, type FormEvent } from "react";
import { Building2, KeyRound } from "lucide-react";
import { Alert, Button, Card, CardHeader, PageHeader, TextField } from "@/components/ds";
import { apiErrorMessage, post } from "@/lib/api";
import { useBusiness } from "@/lib/business";

/** Aucune organisation : en créer une (on en devient propriétaire) ou rejoindre celle d'un collègue avec son code. */
export function Onboarding() {
  const { reload } = useBusiness();
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState<"create" | "join" | null>(null);
  const [error, setError] = useState("");

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy("create");
    setError("");
    try {
      await post("/business/orgs/", { name: name.trim(), city: city.trim() });
      await reload();
    } catch (err) {
      setError(apiErrorMessage(err, "L’organisation n’a pas pu être créée."));
    } finally {
      setBusy(null);
    }
  }

  async function join(e: FormEvent) {
    e.preventDefault();
    setBusy("join");
    setError("");
    try {
      await post("/business/join/", { code: code.trim() });
      await reload();
    } catch (err) {
      setError(apiErrorMessage(err, "Code invalide ou expiré."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader eyebrow="Tratra Business" title="Gérez la maintenance de vos sites" description="Sites, équipements, demandes d’intervention validées, contrats, budgets et facturation consolidée — avec des artisans vérifiés." />
      {error ? <Alert tone="danger" className="mb-4">{error}</Alert> : null}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card as="section" aria-label="Créer une organisation">
          <CardHeader icon={<Building2 className="h-5 w-5" />} title="Créer mon organisation" description="Vous en devenez le propriétaire et invitez ensuite votre équipe." />
          <form onSubmit={create} className="space-y-4" noValidate>
            <TextField label="Nom de l’organisation" required value={name} onChange={(e) => setName(e.target.value)} maxLength={150} />
            <TextField label="Ville" optional value={city} onChange={(e) => setCity(e.target.value)} maxLength={100} />
            <Button type="submit" block size="lg" loading={busy === "create"} disabled={!name.trim()}>Créer l’organisation</Button>
          </form>
        </Card>
        <Card as="section" aria-label="Rejoindre une organisation">
          <CardHeader icon={<KeyRound className="h-5 w-5" />} title="Rejoindre avec un code" description="Votre administrateur vous a remis un code d’invitation à usage unique." />
          <form onSubmit={join} className="space-y-4" noValidate>
            <TextField label="Code d’invitation" required value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="ABCD-EFGH-JKMN" autoComplete="off" />
            <Button type="submit" block size="lg" variant="outline" loading={busy === "join"} disabled={!code.trim()}>Rejoindre</Button>
          </form>
        </Card>
      </div>
    </>
  );
}
