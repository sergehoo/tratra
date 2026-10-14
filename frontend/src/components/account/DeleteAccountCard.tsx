"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import { ApiError, apiErrorMessage, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Alert, Button, Card, CardHeader, Field, Modal, PasswordInput, TextField } from "@/components/ds";

interface Blocker { code: string; detail: string }
interface Status { allowed: boolean; blockers: Blocker[]; confirm_word: string }

/** Suppression définitive de son propre compte (exigence des boutiques d'applications et droit à l'effacement) : mot de passe redemandé + confirmation écrite. */
export function DeleteAccountCard() {
  const { logout } = useAuth();
  const router = useRouter();
  const [status, setStatus] = useState<Status | null>(null);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    get<Status>("/me/account/deletion/").then(setStatus).catch(() => setStatus(null));
  }, [open]);

  async function erase() {
    setBusy(true);
    setError("");
    try {
      await post("/me/account/deletion/", { password, confirm });
      await logout().catch(() => undefined);
      router.replace("/?compte=supprime");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setStatus({ allowed: false, blockers: ((e.data as { blockers?: Blocker[] })?.blockers ?? []), confirm_word: status?.confirm_word ?? "SUPPRIMER" });
        setError("Suppression impossible pour le moment : réglez d’abord les éléments en cours.");
      } else setError(apiErrorMessage(e, "Le compte n’a pas pu être supprimé."));
    } finally {
      setBusy(false);
    }
  }

  const word = status?.confirm_word ?? "SUPPRIMER";
  return (
    <Card id="suppression">
      <CardHeader title="Supprimer mon compte" icon={<Trash2 className="h-5 w-5" />} description="Action définitive : elle ne peut pas être annulée." />
      <p className="text-sm text-inkSoft">
        Votre nom, téléphone, e-mail, photo, adresses, messages, statuts, pièces d’identité et images du visage sont effacés. L’historique des
        réservations et paiements est conservé sans lien avec votre identité, comme la loi l’impose.
      </p>
      {status && !status.allowed ? (
        <Alert tone="warning" title="À régler avant la suppression" className="mt-3">
          <ul className="list-disc space-y-1 pl-5">{status.blockers.map((b) => <li key={b.code}>{b.detail}</li>)}</ul>
        </Alert>
      ) : null}
      <Button className="mt-4" variant="danger" onClick={() => { setError(""); setOpen(true); }} disabled={status ? !status.allowed : false}>
        Supprimer mon compte
      </Button>
      <Modal open={open} onClose={() => !busy && setOpen(false)} dismissible={!busy} title="Supprimer définitivement votre compte ?" description="Cette action est irréversible."
        footer={<div className="flex w-full gap-2"><Button variant="ghost" block onClick={() => setOpen(false)} disabled={busy}>Annuler</Button>
          <Button variant="danger" block loading={busy} disabled={!password || confirm.trim().toUpperCase() !== word} onClick={() => void erase()}>Supprimer</Button></div>}>
        <div className="space-y-4">
          <Field label="Votre mot de passe" required>{(p) => <PasswordInput {...p} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />}</Field>
          <TextField label={`Tapez « ${word} » pour confirmer`} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
          {error ? <Alert tone="danger">{error}</Alert> : null}
        </div>
      </Modal>
    </Card>
  );
}
