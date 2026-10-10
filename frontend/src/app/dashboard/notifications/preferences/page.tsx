"use client";
import { useState } from "react";
import { apiErrorMessage, apiJson } from "@/lib/api";
import { useData } from "@/lib/useData";
import type { PreferencesResponse } from "@/lib/notifications";
import { Alert, BackLink, Button, Card, Checkbox, PageHeader, SkeletonList } from "@/components/ds";

/** Préférences par catégorie (push mobile) et consentement aux communications promotionnelles. */
export default function NotificationPreferencesPage() {
  const { data, loading, error, reload } = useData<PreferencesResponse>("/me/notification-preferences/", "Vos préférences ne peuvent pas être chargées.");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");

  async function save(request: () => Promise<unknown>, fallback: string) {
    setBusy(true);
    setFailure("");
    try {
      await request();
      await reload();
    } catch (e) {
      setFailure(apiErrorMessage(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <BackLink href="/dashboard/notifications">Notifications</BackLink>
      <PageHeader title="Préférences de notification" description="Choisissez les alertes reçues sur vos appareils. L’historique reste toujours disponible ici." />
      {failure ? <Alert tone="danger" className="mb-4">{failure}</Alert> : null}
      {loading ? (
        <SkeletonList count={5} />
      ) : error || !data ? (
        <Alert tone="danger" title="Préférences indisponibles" action={<Button size="sm" variant="outline" onClick={() => void reload()}>Réessayer</Button>}>{error}</Alert>
      ) : (
        <div className="grid max-w-2xl gap-5">
          <Card padding="md" radius="panel">
            <ul className="divide-y divide-line">
              {data.preferences.map((p) => (
                <li key={p.category} className="py-3 first:pt-0 last:pb-0">
                  <Checkbox
                    label={
                      <span>
                        <span className="font-semibold text-ink">{p.label}</span>
                        {p.locked ? <span className="block text-xs text-ash">Toujours actif : sécurité et vérification de votre compte</span> : null}
                      </span>
                    }
                    checked={p.push_enabled}
                    disabled={p.locked || busy}
                    onChange={(e) => void save(() => apiJson("/me/notification-preferences/", { method: "PUT", body: JSON.stringify({ preferences: { [p.category]: e.target.checked } }) }), "Le réglage n’a pas pu être enregistré.")}
                  />
                </li>
              ))}
            </ul>
          </Card>
          <Card padding="md" radius="panel">
            <h2 className="font-display text-base font-bold text-ink">Offres et annonces promotionnelles</h2>
            <p className="mt-1 text-sm text-inkSoft">
              Tratra n’envoie aucune communication promotionnelle sans votre accord. Les informations de service (réservations, sécurité, changements
              importants) ne dépendent pas de ce choix. Vous pouvez retirer votre accord à tout moment.
            </p>
            <div className="mt-3">
              <Checkbox
                label="J’accepte de recevoir des offres et annonces promotionnelles"
                checked={data.marketing_consent.granted}
                disabled={busy}
                onChange={(e) => void save(() => apiJson("/me/marketing-consent/", { method: "PUT", body: JSON.stringify({ granted: e.target.checked, source: "web" }) }), "Le choix n’a pas pu être enregistré.")}
              />
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
