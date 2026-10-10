"use client";
import { Badge } from "@/components/ds";
import { CASH_STATE_FR, CASH_STATUS_FR, type CashSummary } from "@/lib/cash";
import { dateFr, fcfa } from "@/lib/engagements";

/** Règlement en espèces entre les parties, en LECTURE SEULE : le Back-Office ne confirme jamais un paiement et n'a pas accès aux justificatifs. */
export function CashBlock({ cash }: { cash: CashSummary }) {
  return (
    <div className="space-y-3">
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={cash.state === "paid" ? "success" : cash.state === "contested" ? "danger" : cash.state === "none" ? "gray" : "accent"}>{CASH_STATE_FR[cash.state]}</Badge>
        {cash.due ? <span className="text-inkSoft">Convenu {fcfa(cash.due, cash.currency)} · confirmé {fcfa(cash.confirmed, cash.currency)}</span> : null}
      </p>
      {cash.history.length ? (
        <ul className="divide-y divide-lineSoft text-sm" aria-label="Déclarations d’espèces">
          {cash.history.map((d) => (
            <li key={d.id} className="py-1.5">
              <strong>{fcfa(d.amount, cash.currency)}</strong> · déclaré par {d.declared_by_role === "artisan" ? "l’artisan" : "le client"} · remis le {dateFr(d.paid_on)} · <span className="font-semibold">{CASH_STATUS_FR[d.status]}</span>
              {d.rejection_reason ? <span className="block text-dangerInk">Motif : {d.rejection_reason}</span> : null}
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-inkSoft">Aucune déclaration d’espèces.</p>}
      <p className="text-xs text-ash">{cash.note} Lecture seule : le Back-Office ne confirme jamais un paiement et ne voit pas les justificatifs.</p>
    </div>
  );
}
