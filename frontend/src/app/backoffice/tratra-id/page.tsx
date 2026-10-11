"use client";
import { useCallback, useEffect, useState } from "react";
import { BadgeCheck, QrCode, ShieldCheck, ShieldX } from "lucide-react";
import { Alert, Badge, Button, PageHeader, SkeletonStats } from "@/components/ds";
import { bo, boError } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useManagedList } from "@/lib/useBoList";
import { FilterBar, FilterSelect, Kpi, KpiGrid, ListView, ReasonModal, SearchBox, dd, postTo, type BoColumn, type RowAction } from "../_components/ui";

interface Row { id: number; code: string; profile_id: number; name: string; valid: boolean; issued_at: string; checks: number; last_check_at: string | null }
interface Stats { ids_issued: number; ids_valid: number; mission_qr_issued: number; mission_qr_used: number; mission_qr_revoked: number; checks_total: number }

export default function TratraIdPage() {
  const { can } = useBo();
  const m = useManagedList<Row, { valid: string }>("/tratra-id/", { valid: "" });
  const { values: f, list } = m;
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsError, setStatsError] = useState("");
  const [suspend, setSuspend] = useState<Row | null>(null);
  const [qrOpen, setQrOpen] = useState(false);
  const [notice, setNotice] = useState("");

  const loadStats = useCallback(() => {
    setStatsError("");
    void bo.get<Stats>("/tratra-id/stats/").then(setStats).catch((e) => { setStats(null); setStatsError(boError(e, "Les indicateurs n’ont pas pu être chargés.")); });
  }, []);
  useEffect(loadStats, [loadStats]);

  const columns: BoColumn<Row>[] = [
    { key: "code", header: "Tratra ID", primary: true, cell: (r) => <span className="font-mono font-semibold text-ink">{r.code}</span> },
    { key: "name", header: "Titulaire", cell: (r) => r.name },
    { key: "valid", header: "Validité", cell: (r) => <Badge tone={r.valid ? "success" : "danger"}>{r.valid ? "Valide" : "Révoqué / non éligible"}</Badge> },
    { key: "checks", header: "Vérifications", align: "right", hideOnMobile: true, cell: (r) => `${r.checks}${r.last_check_at ? ` · dernière ${dd(r.last_check_at) as string}` : ""}` },
    { key: "issued", header: "Émis le", from: "xl", hideOnMobile: true, cell: (r) => dd(r.issued_at) },
  ];
  const rowActions = (r: Row): RowAction[] => [
    { label: "Dossier KYC de l’artisan", icon: ShieldCheck, href: `/backoffice/kyc/${r.profile_id}`, hidden: !can("kyc.review") },
    { label: "Révoquer ce Tratra ID", icon: ShieldX, tone: "danger", onClick: () => setSuspend(r), hidden: !(can("tratra_id.manage") && r.valid) },
  ];

  return (
    <>
      <PageHeader title="Tratra ID" description="Identifiants professionnels. La validité est recalculée à chaque vérification : révoquer un Tratra ID revient à suspendre le dossier de l’artisan." />
      {notice ? <p role="status" className="mb-4 rounded-xl bg-successSoft px-4 py-3 text-sm font-semibold text-successInk">{notice}</p> : null}
      {stats ? (
        <KpiGrid className="mb-5">
          <Kpi icon={<BadgeCheck className="h-5 w-5" />} label="Identifiants émis" value={stats.ids_issued} hint={`${stats.ids_valid} valides aujourd’hui`} />
          <Kpi icon={<QrCode className="h-5 w-5" />} tone="accent" label="QR de mission émis" value={stats.mission_qr_issued} hint={`${stats.mission_qr_used} utilisés · ${stats.mission_qr_revoked} révoqués`} />
          <Kpi icon={<ShieldCheck className="h-5 w-5" />} tone="night" label="Vérifications réussies" value={stats.checks_total} hint="Identité confirmée à l’arrivée" />
        </KpiGrid>
      ) : statsError ? <Alert tone="danger" className="mb-5" action={<Button size="sm" variant="outline" onClick={loadStats}>Réessayer</Button>}>{statsError}</Alert> : <SkeletonStats count={3} className="mb-5 sm:grid-cols-3" />}
      <FilterBar
        search={<SearchBox value={f.q} onChange={(v) => m.set({ q: v })} placeholder="Code TR-… ou nom" />}
        activeCount={m.activeCount}
        onReset={m.reset}
        onRefresh={() => { void list.reload(); loadStats(); }}
        refreshing={list.loading}
        actions={can("tratra_id.manage") ? <Button size="sm" variant="outline" leftIcon={<QrCode aria-hidden className="h-4 w-4" />} onClick={() => setQrOpen(true)}>Invalider des QR de mission</Button> : undefined}
      >
        <FilterSelect label="Validité" value={f.valid} onChange={(v) => m.set({ valid: v })} options={[["", "Tous"], ["true", "Valides"], ["false", "Révoqués"]]} />
      </FilterBar>
      <ListView
        list={list}
        columns={columns}
        rowKey={(r) => r.id}
        rowLabel={(r) => r.code}
        caption="Tratra ID"
        empty="Aucun Tratra ID ne correspond."
        emptyHint={m.activeCount ? "Modifiez ou réinitialisez les filtres." : undefined}
        rowActions={rowActions}
        pageSize={m.pageSize}
        onPageSize={(n) => m.set({ size: String(n) })}
      />

      <ReasonModal
        open={Boolean(suspend)}
        title={`Révoquer ${suspend?.code ?? ""} ?`}
        description="Le dossier de l’artisan est suspendu : il n’est plus publié ni éligible aux missions et son badge d’identité n’est plus valide immédiatement."
        confirmLabel="Révoquer"
        tone="danger"
        onClose={() => setSuspend(null)}
        request={postTo(`/tratra-id/${suspend?.id}/suspend/`)}
        onDone={() => { setSuspend(null); setNotice("Tratra ID révoqué."); void list.reload(); loadStats(); }}
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
