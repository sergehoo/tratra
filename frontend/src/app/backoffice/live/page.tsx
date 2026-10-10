"use client";
import { useState } from "react";
import { Alert, Badge, Button, Modal, PageHeader, type Column } from "@/components/ds";
import { bo } from "@/lib/bo";
import { useBo } from "@/lib/BoProvider";
import { useBoList } from "@/lib/useBoList";
import { FilterBar, FilterSelect, ListView, ReasonModal, STATUS_FR, Tag, dt } from "../_components/ui";

interface Row {
  booking_id: number;
  status: string;
  phase: string;
  artisan: string;
  client: string;
  artisan_sharing: boolean;
  client_sharing: boolean;
  en_route_at: string | null;
  arrived_at: string | null;
  arrival_distance_m: number | null;
  last_position_age_s: number | null;
  flags: string[];
  updated_at: string;
}
interface Position { booking_id: number; lat: number; lng: number; precision_m: number; age_seconds: number }

const PHASE_FR: Record<string, string> = { confirmed: "Confirmée", en_route: "En route", arrived: "Arrivé", in_progress: "En cours", completed: "Terminée", cancelled: "Annulée", pending: "En attente" };
const FLAG_FR: Record<string, string> = { arrival_far: "Arrivée déclarée loin du lieu", position_stale: "Position perdue" };

const ageLabel = (s: number | null) => (s === null ? "aucune position" : s < 90 ? `il y a ${s} s` : `il y a ${Math.round(s / 60)} min`);

export default function LivePage() {
  const { can } = useBo();
  const [scope, setScope] = useState("");
  const list = useBoList<Row>("/live/", { all: scope });
  const [target, setTarget] = useState<Row | null>(null);
  const [position, setPosition] = useState<Position | null>(null);

  const columns: Column<Row>[] = [
    { key: "id", header: "Mission", primary: true, cell: (r) => <span className="font-semibold text-ink">#{r.booking_id}</span> },
    { key: "phase", header: "Phase", cell: (r) => <Tag value={r.status} label={PHASE_FR[r.phase] ?? STATUS_FR[r.status]} /> },
    { key: "who", header: "Artisan → client", hideOnMobile: true, cell: (r) => `${r.artisan} → ${r.client}` },
    { key: "share", header: "Partage", cell: (r) => <span className="flex flex-wrap gap-1.5"><Badge tone={r.artisan_sharing ? "success" : "gray"}>Artisan {r.artisan_sharing ? "actif" : "inactif"}</Badge><Badge tone={r.client_sharing ? "success" : "gray"}>Client {r.client_sharing ? "actif" : "inactif"}</Badge></span> },
    { key: "age", header: "Dernière position", cell: (r) => ageLabel(r.last_position_age_s) },
    { key: "flags", header: "Alertes", cell: (r) => (r.flags.length ? <span className="flex flex-wrap gap-1.5">{r.flags.map((f) => <Badge key={f} tone="danger">{FLAG_FR[f] ?? f}{f === "arrival_far" && r.arrival_distance_m ? ` (${r.arrival_distance_m} m)` : ""}</Badge>)}</span> : <span className="text-ash">—</span>) },
    { key: "act", header: "", align: "right", cell: (r) => (can("live.view") && r.artisan_sharing ? <Button size="sm" variant="outline" onClick={() => setTarget(r)}>Position approximative</Button> : null) },
  ];

  return (
    <>
      <PageHeader title="Suivi en direct" description="État du partage de position des interventions. Aucune coordonnée n’est affichée ici : l’accès à une position exige un motif, est limité à une mission active dont l’artisan partage, arrondi à environ 100 m et journalisé." />
      <FilterBar>
        <FilterSelect label="Portée" value={scope} onChange={setScope} options={[["", "Interventions actives"], ["true", "Toutes les sessions"]]} />
        <Button variant="outline" onClick={() => void list.reload()}>Actualiser</Button>
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.booking_id} caption="Suivi des interventions" empty="Aucune intervention active en ce moment." />

      <ReasonModal
        open={Boolean(target)}
        title={`Position approximative — mission #${target?.booking_id ?? ""}`}
        description="Cette consultation est journalisée avec votre motif. Elle n’est possible que pour une mission active dont l’artisan partage sa position."
        confirmLabel="Consulter"
        reasonLabel="Motif de la consultation"
        onClose={() => setTarget(null)}
        request={async (b) => { setPosition(await bo.post<Position>(`/live/${target?.booking_id}/position/`, { reason: b.reason })); }}
        onDone={() => setTarget(null)}
      />
      <Modal open={Boolean(position)} onClose={() => setPosition(null)} title="Position approximative" description="Valeur arrondie : ne la recopiez pas hors du traitement de l’incident.">
        {position ? (
          <div className="space-y-3 text-sm">
            <p className="font-mono text-lg font-semibold text-ink">{position.lat.toFixed(3)}, {position.lng.toFixed(3)}</p>
            <p className="text-inkSoft">Précision ≈ {position.precision_m} m · mesurée {ageLabel(position.age_seconds)} (mission #{position.booking_id}).</p>
            <Alert tone="warning">Cette consultation a été enregistrée dans le journal d’audit.</Alert>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
