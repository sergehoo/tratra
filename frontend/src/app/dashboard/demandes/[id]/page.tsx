"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { UserSearch, Zap } from "lucide-react";
import { Alert, Badge, Button, ButtonLink, Card, ConfirmDialog, PageHeader, SkeletonList } from "@/components/ds";
import { ProPicker, type ProChoice } from "@/components/flash/ProPicker";
import { apiErrorMessage } from "@/lib/api";
import { MATCHING_LABEL, STATUS_TONE, cancelRequest, chooseQuote, getRequest, intentKey, relaunchRequest, switchMode, type FlashRequest } from "@/lib/flash";

/* Suivi d'une demande (commande unique) : progression réelle, professionnel choisi, « votre choix est attendu », bascule confirmée entre
   « Trouvez-moi un professionnel » et « Choisir mon professionnel » sans rien ressaisir, devis à retenir, réservation créée. */
export default function RequestPage() {
  const { id } = useParams<{ id: string }>();
  const rid = Number(id);
  const router = useRouter();
  const [d, setD] = useState<FlashRequest | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{ to: "auto" | "direct"; choice?: ProChoice } | null>(null);
  const [picker, setPicker] = useState(false);

  const load = useCallback(async () => {
    try { setD(await getRequest(rid)); setError(""); } catch (e) { setError(apiErrorMessage(e, "Cette demande n’a pas pu être chargée.")); }
  }, [rid]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!d || !["searching", "quoting", "awaiting"].includes(d.status)) return;
    const t = setInterval(() => void load(), 5000);           // suivi en direct tant que la demande est ouverte
    return () => clearInterval(t);
  }, [d, load]);

  async function act(call: () => Promise<FlashRequest>) {
    setBusy(true);
    setError("");
    try {
      const next = await call();
      if (next.id !== rid) router.push(`/dashboard/demandes/${next.id}`); else setD(next);
    } catch (e) {
      setError(apiErrorMessage(e, "Action impossible pour le moment."));
      void load();
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  if (!d) return error ? <Alert tone="danger">{error}</Alert> : <SkeletonList />;
  const open = ["searching", "quoting", "awaiting"].includes(d.status);
  const direct = d.matching === "direct";
  const exclude = d.target ? [d.target.id] : [];

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title={d.category.name} description={`${d.commune || d.address} · ${d.when_label} · ${d.amount_label}`} />
      <Card className="space-y-3">
        <p className="flex flex-wrap gap-2">
          <Badge tone={STATUS_TONE[d.status]}>{d.status_label}</Badge>
          <Badge tone="night" data-testid="matching">{MATCHING_LABEL[d.matching]}</Badge>
        </p>
        {direct && d.target && d.status !== "assigned" ? <p className="text-sm">Professionnel choisi : <strong>{d.target.name}</strong></p> : null}
        {d.status === "searching" ? (
          <p className="text-sm text-inkSoft">{d.progress.contacted} professionnel(s) contacté(s) · {d.progress.waiting} en train de répondre
            {d.progress.declined || d.progress.no_answer ? ` · ${d.progress.declined} indisponible(s), ${d.progress.no_answer} sans réponse` : ""}</p>
        ) : null}
        {d.status === "awaiting" ? (
          <Alert tone="warning" data-testid="awaiting">{d.target?.name ?? "Le professionnel choisi"} {d.awaiting_reason ?? "n’est pas disponible"}. Votre demande est conservée : choisissez la suite.</Alert>
        ) : null}
        {d.assigned_to ? (
          <div className="rounded-panel bg-successSoft p-3 text-sm text-successInk">
            <strong>{d.assigned_to.name}</strong> a accepté votre mission.
            {d.booking ? <> <Link href={`/dashboard/bookings/${d.booking}`} className="font-semibold underline">Suivre la réservation</Link></> : null}
          </div>
        ) : null}
        {d.status === "unfulfilled" ? <Alert tone="warning">{d.close_reason || "Aucun professionnel disponible."} Vous pouvez relancer.</Alert> : null}
      </Card>

      {d.quotes?.length ? (
        <Card className="space-y-3">
          <h2 className="font-display text-lg font-bold text-ink">Devis reçus</h2>
          {d.quotes.map((q) => (
            <div key={q.offer} className="flex flex-wrap items-center justify-between gap-3 rounded-panel border border-line p-3">
              <div><p className="font-semibold">{q.pro.name} — {q.amount_label}</p>{q.message ? <p className="text-sm text-inkSoft">« {q.message} »</p> : null}</div>
              {open && q.status === "quoted" ? <Button size="sm" loading={busy} onClick={() => void act(() => chooseQuote(rid, q.offer))}>Choisir ce devis</Button> : null}
            </div>
          ))}
        </Card>
      ) : null}

      {error ? <Alert tone="danger">{error}</Alert> : null}
      <div className="flex flex-col gap-2">
        {d.can_switch && (direct || d.status === "awaiting") ? (
          <Button variant={d.status === "awaiting" ? "primary" : "outline"} leftIcon={<Zap aria-hidden className="h-4 w-4" />} onClick={() => setConfirm({ to: "auto" })} data-testid="switch-auto">
            Trouvez-moi un professionnel
          </Button>
        ) : null}
        {d.can_switch ? (
          <Button variant="outline" leftIcon={<UserSearch aria-hidden className="h-4 w-4" />} onClick={() => setPicker(true)} data-testid="switch-direct">
            {direct ? "Choisir un autre professionnel" : "Choisir mon professionnel"}
          </Button>
        ) : null}
        {d.can_cancel ? <Button variant="ghost" loading={busy} onClick={() => void act(() => cancelRequest(rid))}>Annuler ma demande</Button> : null}
        {d.can_relaunch ? <Button loading={busy} onClick={() => void act(() => relaunchRequest(rid, intentKey("flash-relaunch")))}>Relancer la recherche</Button> : null}
        <ButtonLink href="/dashboard/demandes" variant="ghost">Toutes mes demandes</ButtonLink>
      </div>

      <ProPicker open={picker} onClose={() => setPicker(false)} category={d.category.id} commune={d.commune} when={d.scheduled_for} exclude={exclude}
        onPick={(c) => { setPicker(false); setConfirm({ to: "direct", choice: c }); }} />
      <ConfirmDialog open={confirm !== null} onClose={() => setConfirm(null)} loading={busy}
        title={confirm?.to === "auto" ? "Trouvez-moi un professionnel ?" : `Choisir ${confirm?.choice?.pro.name ?? "ce professionnel"} ?`}
        description={confirm?.to === "auto"
          ? `${d.status === "searching" && d.target ? `La proposition à ${d.target.name} sera retirée. ` : ""}Tratra proposera votre demande aux professionnels disponibles. Adresse, date et prix sont conservés.`
          : "Il recevra votre demande. Les propositions en cours seront retirées ; les devis déjà reçus restent valables."}
        confirmLabel="Confirmer"
        onConfirm={() => void act(() => switchMode(rid, confirm!.to, d.version, confirm!.choice?.pro.id))} />
    </div>
  );
}
