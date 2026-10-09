"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { MessageSquare } from "lucide-react";
import { apiErrorMessage, post } from "@/lib/api";
import { Alert, Button } from "@/components/ds";

/** Ouvre (ou crée) la conversation liée à une réservation puis bascule sur la messagerie. */
export function MessageButton({ bookingId, label, block = true }: { bookingId: number; label: string; block?: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function open() {
    setBusy(true);
    setError("");
    try {
      const r = await post<{ id: number }>("/me/conversations/", { booking: bookingId });
      router.push(`/dashboard/messages?c=${r.id}`);
    } catch (e) {
      setError(apiErrorMessage(e, "La conversation n’a pas pu être ouverte."));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button variant="outline" block={block} loading={busy} leftIcon={<MessageSquare aria-hidden className="h-4 w-4" />} onClick={() => void open()}>
        {label}
      </Button>
      {error ? <Alert tone="danger">{error}</Alert> : null}
    </div>
  );
}
