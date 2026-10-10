"use client";
import { useState, type FormEvent } from "react";
import { Download, FileText } from "lucide-react";
import { Alert, Button, Card, CardHeader, DataTable, EmptyState, PageHeader, TextField, type Column } from "@/components/ds";
import { apiErrorMessage, post, privateFileUrl } from "@/lib/api";
import { money, shortDate, useBusiness, useOrgData } from "@/lib/business";

interface Invoice { id: number; number: string; period_start: string; period_end: string; total: string; created_at: string; lines: { site_name: string; description: string; amount: string }[] }

export default function InvoicesPage() {
  const { org, path } = useBusiness();
  const { data, loading, error, reload } = useOrgData<Invoice[]>("invoices/", "Les factures ne peuvent pas être chargées.");
  const now = new Date();
  const [start, setStart] = useState(`${now.toISOString().slice(0, 8)}01`);
  const [end, setEnd] = useState(now.toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [notice, setNotice] = useState("");
  const cur = org?.currency;

  async function generate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFailure("");
    setNotice("");
    try {
      const inv = await post<Invoice & { skipped_unpriced: number }>(path("invoices/generate/"), { start, end });
      setNotice(`Facture ${inv.number} émise : ${inv.lines.length} intervention(s), ${money(inv.total, cur)}.${inv.skipped_unpriced ? ` ${inv.skipped_unpriced} intervention(s) sans montant n’ont pas été facturées.` : ""}`);
      await reload();
    } catch (err) {
      setFailure(apiErrorMessage(err, "La facture n’a pas pu être générée."));
    } finally {
      setBusy(false);
    }
  }
  async function download(inv: Invoice) {
    try {
      const url = await privateFileUrl(path(`invoices/${inv.id}/export.csv`));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${inv.number}.csv`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch {
      setFailure("Le fichier n’a pas pu être téléchargé.");
    }
  }
  const columns: Column<Invoice>[] = [
    { key: "n", header: "N°", primary: true, cell: (i) => <span className="font-mono text-sm font-semibold">{i.number}</span> },
    { key: "p", header: "Période", cell: (i) => `${shortDate(i.period_start)} → ${shortDate(i.period_end)}` },
    { key: "l", header: "Interventions", hideOnMobile: true, align: "right", cell: (i) => i.lines.length },
    { key: "t", header: "Total", align: "right", cell: (i) => <strong>{money(i.total, cur)}</strong> },
    { key: "d", header: "", align: "right", cell: (i) => <Button size="sm" variant="outline" leftIcon={<Download aria-hidden className="h-4 w-4" />} onClick={() => download(i)}>CSV</Button> },
  ];
  return (
    <>
      <PageHeader eyebrow="Tratra Business" title="Facturation consolidée" description="Regroupe les interventions terminées et chiffrées d’une période. Chaque intervention n’est facturée qu’une fois ; les paiements restent gérés mission par mission." />
      <Card as="section" aria-label="Générer" className="mb-6">
        <CardHeader icon={<FileText className="h-5 w-5" />} title="Émettre une facture consolidée" />
        <form onSubmit={generate} className="grid grid-cols-1 items-end gap-4 sm:grid-cols-3">
          <TextField label="Du" type="date" required value={start} onChange={(e) => setStart(e.target.value)} />
          <TextField label="Au" type="date" required value={end} onChange={(e) => setEnd(e.target.value)} />
          <Button type="submit" loading={busy}>Générer</Button>
        </form>
        {failure ? <Alert tone="danger" className="mt-4">{failure}</Alert> : null}
        {notice ? <Alert tone="success" className="mt-4">{notice}</Alert> : null}
      </Card>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <DataTable caption="Factures consolidées" columns={columns} rows={data ?? []} rowKey={(i) => i.id} loading={loading} empty={<EmptyState title="Aucune facture" description="Les factures émises apparaîtront ici." />} />
    </>
  );
}
