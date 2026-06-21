"use client";
import { useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Card, Input, Button, Badge } from "@/components/ui";

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
  current_period_end?: string;
}

export default function CompanyHome() {
  const [c, setC] = useState<Company>({});
  const [sub, setSub] = useState<Sub | null>(null);
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState(false);
  const set = (k: keyof Company) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setC((s) => ({ ...s, [k]: e.target.value }));

  useEffect(() => {
    Promise.all([
      get<Company>("/companies/me/").then((d) => setC(d || {})).catch(() => {}),
      get<Sub>("/subscriptions/current/").then(setSub).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaved(false);
    const updated = await post<Company>("/companies/me/", c);
    setC(updated);
    setSaved(true);
  }

  if (loading) return <p className="text-ash">Chargement…</p>;

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <div className="mb-4 flex items-center gap-3">
          <h2 className="text-xl font-bold">Profil entreprise</h2>
          <Badge tone={c.verified ? "primary" : "gray"}>{c.verified ? "Vérifié" : "Non vérifié"}</Badge>
        </div>
        <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
          <Input placeholder="Raison sociale" value={c.company_name ?? ""} onChange={set("company_name")} />
          <Input placeholder="N° RCCM" value={c.registration_number ?? ""} onChange={set("registration_number")} />
          <Input placeholder="Secteur" value={c.industry ?? ""} onChange={set("industry")} />
          <Input placeholder="Ville" value={c.city ?? ""} onChange={set("city")} />
          <Input placeholder="Personne de contact" value={c.contact_person ?? ""} onChange={set("contact_person")} />
          <Input placeholder="Téléphone" value={c.phone ?? ""} onChange={set("phone")} />
          <Input placeholder="Site web" value={c.website ?? ""} onChange={set("website")} className="sm:col-span-2" />
          <div className="sm:col-span-2 flex items-center gap-3">
            <Button type="submit">Enregistrer</Button>
            {saved && <span className="text-sm text-primary">Enregistré ✓</span>}
          </div>
        </form>
      </Card>

      <Card>
        <h2 className="mb-3 text-xl font-bold">Abonnement</h2>
        {sub && sub.active !== false ? (
          <>
            <p className="text-lg font-semibold">{sub.plan_detail?.name ?? sub.status}</p>
            <Badge tone="primary">{sub.status}</Badge>
            {sub.current_period_end && (
              <p className="mt-2 text-sm text-ash">
                Jusqu'au {new Date(sub.current_period_end).toLocaleDateString("fr-FR")}
              </p>
            )}
          </>
        ) : (
          <p className="text-ash">Aucun abonnement actif. Souscrivez à une offre B2B pour débloquer la facturation centralisée et les missions en volume.</p>
        )}
      </Card>
    </div>
  );
}
