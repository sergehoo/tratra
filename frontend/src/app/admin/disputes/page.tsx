"use client";
import { useCallback, useEffect, useState } from "react";
import { Ban, Banknote, RefreshCw, Scale, Undo2, type LucideIcon } from "lucide-react";
import { apiErrorMessage, get, post } from "@/lib/api";
import {
  Alert,
  Avatar,
  Button,
  ButtonLink,
  ConfirmDialog,
  DataTable,
  EmptyState,
  PageHeader,
  StatusBadge,
  type ButtonVariant,
  type Column,
} from "@/components/ds";
import type { Dispute, Paginated } from "@/lib/types";

type ResolveAction = "refund_client" | "release_artisan" | "reject";

interface ActionSpec {
  label: string;
  variant: ButtonVariant;
  icon: LucideIcon;
  tone: "primary" | "danger";
  title: string;
  /** Conséquence réelle de la décision (voir Dispute.resolve / Dispute.reject côté serveur). */
  describe: (d: Dispute) => string;
}

const ACTIONS: Record<ResolveAction, ActionSpec> = {
  refund_client: {
    label: "Rembourser le client",
    variant: "soft",
    icon: Undo2,
    tone: "primary",
    title: "Rembourser le client ?",
    describe: (d) =>
      `Le litige #${d.id} sera clos en faveur du client. Si le paiement de la réservation #${d.booking} est encore en attente ou en séquestre, il lui sera remboursé.`,
  },
  release_artisan: {
    label: "Verser à l’artisan",
    variant: "soft",
    icon: Banknote,
    tone: "primary",
    title: "Verser à l’artisan ?",
    describe: (d) =>
      `Le litige #${d.id} sera clos en faveur de l’artisan. Si le paiement de la réservation #${d.booking} est encore à libérer, il lui sera versé.`,
  },
  reject: {
    label: "Rejeter",
    variant: "ghost",
    icon: Ban,
    tone: "danger",
    title: "Rejeter le litige ?",
    describe: (d) => `Le litige #${d.id} sera clos sans aucun mouvement de fonds sur la réservation #${d.booking}.`,
  },
};

const ACTION_ORDER: ResolveAction[] = ["refund_client", "release_artisan", "reject"];

/** Libellé de la décision déjà prise (valeurs de Dispute.RESOLUTION_ACTIONS). */
const RESOLUTION_LABEL: Record<string, string> = {
  refund_client: "Décision : remboursement du client",
  release_artisan: "Décision : versement à l’artisan",
  none: "Aucune action",
};

const ROLE_LABEL: Record<string, string> = {
  client: "Client",
  employeur: "Employeur",
  handyman: "Artisan",
  entreprise: "Entreprise",
  admin: "Administrateur",
};

const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });

function formatDate(iso: string | undefined): string | null {
  if (!iso) return null;
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? null : DATE.format(t);
}

function Reporter({ user }: { user: Dispute["reporter_detail"] }) {
  const full = [user?.first_name, user?.last_name].filter(Boolean).join(" ").trim();
  const name = full || user?.email || (user?.id ? `Utilisateur #${user.id}` : "");
  if (!user || !name) return <span className="text-ash">—</span>;
  const role = user.user_type ? ROLE_LABEL[user.user_type] : undefined;
  return (
    <div className="flex items-center gap-3">
      <Avatar name={name} size={32} />
      <div className="min-w-0 text-left">
        <p className="break-words font-medium text-ink">{name}</p>
        {role ? <p className="text-xs text-ash">{role}</p> : null}
      </div>
    </div>
  );
}

export default function AdminDisputes() {
  const [items, setItems] = useState<Dispute[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  // La cible reste en mémoire à la fermeture pour que le dialogue ne se vide pas pendant son animation de sortie.
  const [target, setTarget] = useState<{ dispute: Dispute; action: ResolveAction } | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [actionError, setActionError] = useState("");

  const load = useCallback((skeleton = true) => {
    if (skeleton) setLoading(true);
    setLoadError("");
    get<Paginated<Dispute>>("/disputes/")
      .then((d) => {
        setItems(d.results ?? []);
        setTotal(d.count ?? d.results?.length ?? 0);
        setHasMore(Boolean(d.next));
      })
      .catch((requestError) => setLoadError(apiErrorMessage(requestError, "Les litiges ne peuvent pas être chargés.")))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function resolve(id: number, action: ResolveAction) {
    setBusy(id);
    setActionError("");
    try {
      await post(`/disputes/${id}/resolve/`, { action, resolution: "" });
      setDialogOpen(false);
      setNotice(`Décision enregistrée pour le litige #${id}.`);
      load(false);
    } catch (requestError) {
      setActionError(apiErrorMessage(requestError, "La décision n’a pas pu être enregistrée. Réessayez."));
    } finally {
      setBusy(null);
    }
  }

  function ask(dispute: Dispute, action: ResolveAction) {
    setTarget({ dispute, action });
    setActionError("");
    setDialogOpen(true);
  }

  const columns: Column<Dispute>[] = [
    {
      key: "litige",
      header: "Litige",
      primary: true,
      cell: (d) => (
        <>
          <span className="block font-semibold text-ink">Litige #{d.id}</span>
          <span className="mt-0.5 block text-xs font-normal text-ash">Réservation #{d.booking}</span>
          {formatDate(d.created_at) ? (
            <span className="block text-xs font-normal text-ash">Déclaré le {formatDate(d.created_at)}</span>
          ) : null}
          {/* Le statut vit ici (4 colonnes au lieu de 5) : le tableau tient de 768 à 1165 px. */}
          <span className="mt-2 block">
            <StatusBadge kind="dispute" status={d.status} />
          </span>
        </>
      ),
    },
    { key: "reporter", header: "Déclarant", cell: (d) => <Reporter user={d.reporter_detail} /> },
    {
      key: "reason",
      header: "Motif",
      cell: (d) => <p className="whitespace-pre-line break-words text-left leading-relaxed">{d.reason}</p>,
    },
    {
      key: "decision",
      header: "Décision",
      align: "right",
      cell: (d) => {
        if (d.status === "open") {
          return (
            <div className="ml-auto flex max-w-[16rem] flex-wrap justify-end gap-2">
              {ACTION_ORDER.map((action) => {
                const spec = ACTIONS[action];
                const Icon = spec.icon;
                return (
                  <Button
                    key={action}
                    size="sm"
                    variant={spec.variant}
                    disabled={busy === d.id}
                    leftIcon={<Icon aria-hidden className="h-4 w-4" />}
                    onClick={() => ask(d, action)}
                  >
                    {spec.label}
                  </Button>
                );
              })}
            </div>
          );
        }
        const label = d.resolution_action ? RESOLUTION_LABEL[d.resolution_action] : undefined;
        return (
          <div className="ml-auto max-w-[16rem] text-sm">
            {label ? <p className="font-semibold text-ink">{label}</p> : null}
            {d.resolution ? <p className="mt-0.5 whitespace-pre-line break-words text-ash">{d.resolution}</p> : null}
            {!label && !d.resolution ? <span className="text-ash">—</span> : null}
          </div>
        );
      },
    },
  ];

  const spec = target ? ACTIONS[target.action] : null;
  const showTable = loading || items.length > 0 || !loadError;

  return (
    <>
      <PageHeader
        eyebrow="Back-office"
        title="Litiges"
        description="Examinez les litiges déclarés par les clients et les artisans, puis décidez : remboursement, versement ou rejet."
        actions={
          <Button
            variant="outline"
            loading={loading}
            leftIcon={<RefreshCw aria-hidden className="h-4 w-4" />}
            onClick={() => load()}
          >
            Actualiser
          </Button>
        }
      />

      <div className="space-y-5">
        {notice ? (
          <Alert tone="success" onDismiss={() => setNotice("")}>
            {notice}
          </Alert>
        ) : null}

        {loadError ? (
          <Alert
            tone="danger"
            title="Chargement impossible"
            action={
              <Button size="sm" variant="outline" onClick={() => load()}>
                Réessayer
              </Button>
            }
          >
            {loadError}
          </Alert>
        ) : null}

        {hasMore && !loading ? (
          <Alert tone="info">
            Seuls {items.length} litiges sur {total} sont affichés ici.
          </Alert>
        ) : null}

        {showTable ? (
          <DataTable
            caption="Litiges"
            columns={columns}
            rows={items}
            rowKey={(d) => d.id}
            loading={loading}
            empty={
              <EmptyState
                icon={<Scale aria-hidden />}
                title="Aucun litige"
                description="Aucun litige n’a été déclaré pour le moment. Ils apparaissent ici dès qu’un client ou un artisan en ouvre un sur une réservation."
                actions={
                  <ButtonLink href="/admin" variant="outline">
                    Retour à la vue d’ensemble
                  </ButtonLink>
                }
              />
            }
          />
        ) : null}
      </div>

      <ConfirmDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onConfirm={() => target && void resolve(target.dispute.id, target.action)}
        title={spec?.title ?? ""}
        description={target && spec ? spec.describe(target.dispute) : undefined}
        confirmLabel={spec?.label ?? "Confirmer"}
        tone={spec?.tone ?? "primary"}
        loading={busy !== null}
      >
        {target ? (
          <div className="space-y-4 text-sm">
            <div className="rounded-panel border border-lineSoft bg-canvas p-4">
              <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ash">Motif déclaré</p>
              <p className="mt-1.5 whitespace-pre-line break-words leading-relaxed text-inkSoft">{target.dispute.reason}</p>
            </div>
            <p className="text-ash">Vous ne pourrez plus modifier cette décision depuis cette page.</p>
            {actionError ? <Alert tone="danger">{actionError}</Alert> : null}
          </div>
        ) : null}
      </ConfirmDialog>
    </>
  );
}
