"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CircleCheck, Circle } from "lucide-react";
import { Alert, Badge, Button, PageHeader, SkeletonPage } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { KV, Section, dt } from "../../_components/ui";

interface Criterion { key: string; label: string; current: unknown; required: unknown; met: boolean; unit?: string }
interface Component { key: string; label: string; weight: number; available: boolean; detail: string; points: number | null; max_points: number | null }
interface Detail {
  profile_id: number;
  name: string;
  trust_score: number | null;
  badges: string[];
  evaluated_at: string | null;
  score: { score: number | null; confidence: string | null; reason: string; components: Component[]; note: string };
  criteria: { expert: Criterion[]; sure: Criterion[] };
  awards: { code: string; label: string; started_at: string; ended_at: string | null; start_reason: string; end_reason: string }[];
  history: { action: string; at: string; by: string }[];
}

function Criteria({ title, items }: { title: string; items: Criterion[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-bold text-ink">{title}</h3>
      <ul className="space-y-2">
        {items.map((c) => (
          <li key={c.key} className="flex items-start gap-2.5 text-sm">
            {c.met ? <CircleCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <Circle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-fog" />}
            <span>{c.label} — <strong>{String(c.current ?? "—")}</strong> / {String(c.required)}{c.unit ?? ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TrustDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useBo();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      setD(await bo.get<Detail>(`/trust/${id}/`));
    } catch (e) {
      setError(boError(e, "Ce profil n’a pas pu être chargé."));
    }
  }, [id]);
  useEffect(() => void load(), [load]);

  async function reevaluate() {
    setBusy(true);
    setNotice("");
    try {
      const r = await bo.post<{ awarded: string[]; revoked: string[]; score: number | null }>(`/trust/${id}/reevaluate/`, {});
      setNotice(r.awarded.length || r.revoked.length ? `Réévaluation : ${r.awarded.length} badge(s) attribué(s), ${r.revoked.length} retiré(s).` : "Réévaluation effectuée : aucun changement.");
      await load();
    } catch (e) {
      setError(boError(e, "La réévaluation a échoué."));
    } finally {
      setBusy(false);
    }
  }

  if (error && !d) {
    return (
      <>
        <PageHeader title="Confiance" back={{ href: "/backoffice/trust", label: "Tratra Trust" }} />
        <Alert tone="danger" title="Profil indisponible" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert>
      </>
    );
  }
  if (!d) return <SkeletonPage />;
  return (
    <>
      <PageHeader
        title={d.name}
        eyebrow={`Profil #${d.profile_id}`}
        back={{ href: "/backoffice/trust", label: "Tratra Trust" }}
        description="Lecture seule des mesures. La réévaluation applique la règle ; elle n’accorde ni ne retire rien à la main."
        actions={can("trust.manage") ? <Button size="sm" loading={busy} onClick={() => void reevaluate()}>Réévaluer par la règle</Button> : null}
      />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      {error ? <Alert tone="danger" className="mb-4">{error}</Alert> : null}
      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Score de confiance">
          <p className="font-display text-4xl font-extrabold text-ink">{d.score.score ?? "—"}<span className="text-lg font-semibold text-ash"> / 100</span></p>
          <p className="mt-1 text-sm text-inkSoft">{d.score.score === null ? d.score.reason : `Confiance de la mesure : ${d.score.confidence}`}</p>
          <ul className="mt-4 space-y-2">
            {d.score.components.map((c) => (
              <li key={c.key} className="rounded-panel border border-lineSoft px-3 py-2 text-sm">
                <span className="flex items-center justify-between gap-2"><strong>{c.label}</strong><span className="text-ash">{c.available && c.points !== null ? `${c.points} / ${c.max_points} pts` : "non mesuré"}</span></span>
                <span className="text-xs text-inkSoft">{c.detail}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-ash">{d.score.note}</p>
        </Section>
        <Section title="Badges">
          <p className="mb-3 flex flex-wrap gap-2">{d.badges.length ? d.badges.map((b) => <Badge key={b} tone="success">{b}</Badge>) : <span className="text-sm text-inkSoft">Aucun badge actif.</span>}</p>
          <KV items={[["Dernière évaluation", dt(d.evaluated_at)]]} />
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <Criteria title="Expert" items={d.criteria.expert} />
            <Criteria title="Sûr" items={d.criteria.sure} />
          </div>
        </Section>
        <Section title="Historique des badges" className="lg:col-span-2">
          {d.awards.length ? (
            <ul className="divide-y divide-lineSoft text-sm">
              {d.awards.map((a, i) => (
                <li key={i} className="py-2">
                  <strong>{a.label}</strong> — du {dt(a.started_at)}{a.ended_at ? ` au ${dt(a.ended_at)}` : " (actif)"}
                  <span className="block text-inkSoft">{a.ended_at ? a.end_reason : a.start_reason}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-inkSoft">Aucun badge attribué jusqu’ici.</p>}
        </Section>
      </div>
    </>
  );
}
