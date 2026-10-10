"use client";
import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, PageHeader, SkeletonStats, Stat, type Column } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { FilterBar, FilterSelect, ListView, ReasonModal, SearchBox, Section, dt, postTo } from "../_components/ui";

interface Row { id: number; code: string; profile_id: number; name: string; valid: boolean; issued_at: string; checks: number; last_check_at: string | null }
interface Stats { ids_issued: number; ids_valid: number; mission_qr_issued: number; mission_qr_used: number; mission_qr_revoked: number; checks_total: number }

export default function TratraIdPage() {
  const { can } = useBo();
  const [q, setQ] = useState("");
  const [valid, setValid] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsError, setStatsError] = useState("");
  const [suspend, setSuspend] = useState<Row | null>(null);
  const [qrOpen, setQrOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const list = useBoList<Row>("/tratra-id/", { q: useDebounced(q), valid });

  const loadStats = useCallback(() => {
    setStatsError("");
    void bo.get<Stats>("/tratra-id/stats/").then(setStats).catch((e) => { setStats(null); setStatsError(boError(e, "Les indicateurs n’ont pas pu être chargés.")); });
  }, []);
  useEffect(loadStats, [loadStats]);

  const columns: Column<Row>[] = [
    { key: "code", header: "Tratra ID", primary: true, cell: (r) => <span className="font-mono font-semibold text-ink">{r.code}</span> },
    { key: "name", header: "Titulaire", cell: (r) => r.name },
    { key: "valid", header: "Validité", cell: (r) => <Badge tone={r.valid ? "success" : "danger"}>{r.valid ? "Valide" : "Révoqué / non éligible"}</Badge> },
    { key: "checks", header: "Vérifications", align: "right", hideOnMobile: true, cell: (r) => `${r.checks}${r.last_check_at ? ` · dernière ${dt(r.last_check_at)}` : ""}` },
    { key: "issued", header: "Émis le", hideOnMobile: true, cell: (r) => dt(r.issued_at) },
    { key: "act", header: "", align: "right", cell: (r) => (can("tratra_id.manage") && r.valid ? <Button size="sm" variant="danger" onClick={() => setSuspend(r)}>Révoquer</Button> : null) },
  ];

  return (
    <>
      <PageHeader title="Tratra ID" description="Identifiants professionnels. La validité est recalculée à chaque vérification : révoquer un Tratra ID revient à suspendre le dossier de l’artisan." />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}
      {stats ? (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Identifiants émis" value={stats.ids_issued} hint={`${stats.ids_valid} valides aujourd’hui`} />
          <Stat label="QR de mission émis" value={stats.mission_qr_issued} hint={`${stats.mission_qr_used} utilisés · ${stats.mission_qr_revoked} révoqués`} tone="accent" />
          <Stat label="Vérifications réussies" value={stats.checks_total} hint="Identité confirmée à l’arrivée" tone="night" />
        </div>
      ) : statsError ? <Alert tone="danger" className="mb-6" action={<Button size="sm" variant="outline" onClick={loadStats}>Réessayer</Button>}>{statsError}</Alert> : <SkeletonStats count={3} className="mb-6 sm:grid-cols-3" />}
      <FilterBar>
        <SearchBox value={q} onChange={setQ} placeholder="Code TR-… ou nom" />
        <FilterSelect label="Validité" value={valid} onChange={setValid} options={[["", "Tous"], ["true", "Valides"], ["false", "Révoqués"]]} />
        {can("tratra_id.manage") ? <Button variant="outline" onClick={() => setQrOpen(true)}>Invalider les QR d’une mission</Button> : null}
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} caption="Tratra ID" empty="Aucun Tratra ID ne correspond." />

      <ReasonModal
        open={Boolean(suspend)}
        title={`Révoquer ${suspend?.code ?? ""} ?`}
        description="Le dossier de l’artisan est suspendu : il n’est plus publié ni éligible aux missions et son badge d’identité n’est plus valide immédiatement."
        confirmLabel="Révoquer"
        tone="danger"
        onClose={() => setSuspend(null)}
        request={postTo(`/tratra-id/${suspend?.id}/suspend/`)}
        onDone={() => { setSuspend(null); setNotice("Tratra ID révoqué."); list.reload(); loadStats(); }}
      />
      <ReasonModal
        open={qrOpen}
        title="Invalider les QR de mission"
        description="À utiliser si un QR a été divulgué ou en cas de doute sur l’identité. L’artisan en affichera un nouveau."
        confirmLabel="Invalider"
        tone="danger"
        fields={[{ key: "booking", label: "Numéro de réservation", hint: "Chiffres uniquement, ex. 128", required: true, type: "number" }]}
        onClose={() => setQrOpen(false)}
        request={(b) => {
          if (!/^\d+$/.test((b.booking ?? "").trim())) return Promise.reject(new Error("Numéro de réservation invalide."));
          return bo.post(`/tratra-id/passes/${b.booking.trim()}/revoke/`, { reason: b.reason });
        }}
        onDone={() => { setQrOpen(false); setNotice("QR de mission invalidés."); loadStats(); }}
      />
    </>
  );
}
