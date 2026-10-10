"use client";
import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Alert, Badge, Button, Checkbox, DataTable, EmptyState, Input, Modal, PageHeader, SkeletonPage, TextField, type Column } from "@/components/ds";
import { bo, boError, fieldErrors } from "@/lib/bo";
import { Section, dt, useNotice } from "../_components/ui";

interface Rule { id: number; category: number | null; category_name: string | null; fee_percent: string; fee_min_xof: number; active: boolean }
interface Policy { id: number; name: string; free_until_minutes: number; fee_percent: string; active: boolean }
interface Coupon { id: number; code: string; percent_off: string | null; amount_off: string | null; valid_from: string; valid_to: string; active: boolean; valid_now: boolean; used: number }
interface Integrations {
  push_fcm: { configured: boolean }; sms: { provider: string | null; ready: boolean }; email: { backend: string; real_delivery: boolean };
  payments: Record<string, boolean>; routing_osrm: { configured: boolean }; object_storage: { enabled: boolean };
}
interface Settings { pricing_rules: Rule[]; cancellation_policies: Policy[]; trust: Record<string, number>; trust_labels: Record<string, string>; coupons: Coupon[]; integrations: Integrations }

const PAY_FR: Record<string, string> = { om: "Orange Money", mtn: "MTN MoMo", card: "Carte bancaire", cash: "Espèces (confirmation manuelle)" };
const TRUST_GROUPS: [string, string[]][] = [
  ["Badge Expert", ["expert_min_certifications", "expert_min_completed", "expert_min_reviews", "expert_min_rating", "expert_min_experience_years"]],
  ["Badge Sûr", ["sure_min_completed", "sure_min_punctuality", "sure_min_punctuality_sample", "sure_max_dispute_rate", "sure_min_rating", "sure_min_reviews", "sure_window_days"]],
  ["Mesures", ["punctuality_tolerance_minutes", "min_sample", "reevaluation_hours"]],
  ["Poids du score de confiance", ["weight_identity", "weight_satisfaction", "weight_reliability", "weight_reactivity", "weight_track_record", "weight_certifications"]],
];

/** Modale de formulaire : validation serveur par champ, erreur globale, aucune valeur affichée comme appliquée avant confirmation. */
function FormModal({ open, title, description, children, onClose, onSubmit, submitLabel = "Enregistrer" }: { open: boolean; title: string; description?: string; children: React.ReactNode; onClose: () => void; onSubmit: () => Promise<void>; submitLabel?: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal open={open} onClose={onClose} dismissible={!busy} title={title} description={description}
      footer={<><Button variant="outline" onClick={onClose} disabled={busy}>Annuler</Button><Button loading={busy} onClick={async () => { setBusy(true); try { await onSubmit(); } finally { setBusy(false); } }}>{submitLabel}</Button></>}>
      <div className="space-y-4">{children}</div>
    </Modal>
  );
}

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useNotice();
  const [cats, setCats] = useState<{ id: number; name: string }[]>([]);
  const load = useCallback(async () => {
    setError("");
    try { setS(await bo.get<Settings>("/settings/")); } catch (e) { setError(boError(e, "Les réglages n’ont pas pu être chargés.")); }
  }, []);
  useEffect(() => void load(), [load]);
  useEffect(() => { bo.get<{ results: { id: number; name: string }[] }>("/services/categories/?page_size=100").then((r) => setCats(r.results)).catch(() => setCats([])); }, []);

  // ── Règles de commission ────────────────────────────────────────────────
  const [rule, setRule] = useState<{ item: Rule | null } | null>(null);
  const [rf, setRf] = useState({ fee_percent: "", fee_min_xof: "", category: "", active: true });
  const [ruleErr, setRuleErr] = useState<Record<string, string>>({});
  const [ruleFail, setRuleFail] = useState("");
  function openRule(item: Rule | null) { setRule({ item }); setRuleErr({}); setRuleFail(""); setRf(item ? { fee_percent: item.fee_percent, fee_min_xof: String(item.fee_min_xof), category: item.category ? String(item.category) : "", active: item.active } : { fee_percent: "11", fee_min_xof: "500", category: "", active: true }); }
  async function saveRule() {
    setRuleErr({}); setRuleFail("");
    try {
      if (rule?.item) await bo.patch(`/settings/pricing-rules/${rule.item.id}/`, { fee_percent: rf.fee_percent.replace(",", "."), fee_min_xof: rf.fee_min_xof, active: rf.active });
      else await bo.post("/settings/pricing-rules/", { fee_percent: rf.fee_percent.replace(",", "."), fee_min_xof: rf.fee_min_xof || 0, category: rf.category || null, active: rf.active });
      setRule(null); setNotice("Règle de commission enregistrée."); await load();
    } catch (e) { setRuleErr(fieldErrors(e)); setRuleFail(boError(e, "La règle n’a pas pu être enregistrée.")); }
  }

  // ── Politique d'annulation ──────────────────────────────────────────────
  const [pol, setPol] = useState<{ item: Policy | null } | null>(null);
  const [pf, setPf] = useState({ name: "", free_until_minutes: "", fee_percent: "", active: true });
  const [polErr, setPolErr] = useState<Record<string, string>>({});
  const [polFail, setPolFail] = useState("");
  function openPol(item: Policy | null) { setPol({ item }); setPolErr({}); setPolFail(""); setPf(item ? { name: item.name, free_until_minutes: String(item.free_until_minutes), fee_percent: item.fee_percent, active: item.active } : { name: "", free_until_minutes: "60", fee_percent: "0", active: true }); }
  async function savePol() {
    setPolErr({}); setPolFail("");
    const body = { name: pf.name, free_until_minutes: pf.free_until_minutes, fee_percent: pf.fee_percent.replace(",", "."), active: pf.active };
    try {
      if (pol?.item) await bo.post(`/settings/cancellation-policies/${pol.item.id}/`, body); else await bo.post("/settings/cancellation-policies/", body);
      setPol(null); setNotice("Politique d’annulation enregistrée."); await load();
    } catch (e) { setPolErr(fieldErrors(e)); setPolFail(boError(e, "La politique n’a pas pu être enregistrée.")); }
  }

  // ── Tratra Trust ────────────────────────────────────────────────────────
  const [tf, setTf] = useState<Record<string, string>>({});
  const [trustErr, setTrustErr] = useState<Record<string, string>>({});
  const [trustFail, setTrustFail] = useState("");
  const [trustBusy, setTrustBusy] = useState(false);
  useEffect(() => { if (s) setTf(Object.fromEntries(Object.entries(s.trust).map(([k, v]) => [k, String(v)]))); }, [s]);
  async function saveTrust() {
    if (!s) return;
    setTrustBusy(true); setTrustErr({}); setTrustFail("");
    const changed = Object.fromEntries(Object.entries(tf).filter(([k, v]) => String(s.trust[k]) !== v.replace(",", ".")).map(([k, v]) => [k, v.replace(",", ".")]));
    if (!Object.keys(changed).length) { setTrustBusy(false); setNotice("Aucun changement à enregistrer."); return; }
    try {
      const r = await bo.patch<{ applied_by: string }>("/settings/trust/", changed);
      setNotice(`Seuils enregistrés — appliqués à la ${r.applied_by}.`); await load();
    } catch (e) { setTrustErr(fieldErrors(e)); setTrustFail(boError(e, "Les seuils n’ont pas pu être enregistrés.")); } finally { setTrustBusy(false); }
  }

  // ── Codes promotionnels ─────────────────────────────────────────────────
  const [cou, setCou] = useState(false);
  const [cf, setCf] = useState({ code: "", kind: "percent", value: "", valid_from: "", valid_to: "" });
  const [couErr, setCouErr] = useState<Record<string, string>>({});
  const [couFail, setCouFail] = useState("");
  const iso = (v: string) => (v ? new Date(v).toISOString() : "");
  async function saveCoupon() {
    setCouErr({}); setCouFail("");
    try {
      await bo.post("/settings/coupons/", { code: cf.code, [cf.kind === "percent" ? "percent_off" : "amount_off"]: cf.value.replace(",", "."), valid_from: iso(cf.valid_from), valid_to: iso(cf.valid_to) });
      setCou(false); setNotice("Code promotionnel créé."); await load();
    } catch (e) { const f = fieldErrors(e); setCouErr({ ...f, value: f.percent_off ?? f.amount_off ?? "" }); setCouFail(boError(e, "Le code n’a pas pu être créé.")); }
  }
  async function toggleCoupon(c: Coupon) {
    try { await bo.patch(`/settings/coupons/${c.id}/`, { active: !c.active }); setNotice(c.active ? "Code désactivé." : "Code réactivé."); await load(); } catch (e) { setNotice(boError(e, "Mise à jour impossible.")); }
  }

  if (error && !s) return (<><PageHeader title="Réglages" /><Alert tone="danger" title="Réglages indisponibles" action={<Button size="sm" variant="outline" onClick={() => void load()}>Réessayer</Button>}>{error}</Alert></>);
  if (!s) return <SkeletonPage />;

  const ruleCols: Column<Rule>[] = [
    { key: "c", header: "Périmètre", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.category_name ?? "Toutes les catégories"}</span> },
    { key: "f", header: "Commission", align: "right", cell: (r) => `${r.fee_percent} %` },
    { key: "m", header: "Minimum", align: "right", cell: (r) => `${r.fee_min_xof} FCFA` },
    { key: "a", header: "Statut", cell: (r) => <Badge tone={r.active ? "success" : "gray"}>{r.active ? "Active" : "Inactive"}</Badge> },
    { key: "x", header: "", align: "right", cell: (r) => <Button size="sm" variant="outline" onClick={() => openRule(r)}>Modifier</Button> },
  ];
  const polCols: Column<Policy>[] = [
    { key: "n", header: "Politique", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.name}</span> },
    { key: "free", header: "Annulation gratuite jusqu’à", cell: (r) => `${r.free_until_minutes} min avant` },
    { key: "fee", header: "Pénalité ensuite", align: "right", cell: (r) => `${r.fee_percent} %` },
    { key: "a", header: "Statut", cell: (r) => <Badge tone={r.active ? "success" : "gray"}>{r.active ? "Appliquée" : "Inactive"}</Badge> },
    { key: "x", header: "", align: "right", cell: (r) => <Button size="sm" variant="outline" onClick={() => openPol(r)}>Modifier</Button> },
  ];
  const couCols: Column<Coupon>[] = [
    { key: "c", header: "Code", primary: true, cell: (r) => <span className="font-mono font-semibold text-ink">{r.code}</span> },
    { key: "v", header: "Réduction", cell: (r) => (r.percent_off ? `${r.percent_off} %` : `${r.amount_off} FCFA`) },
    { key: "p", header: "Validité", hideOnMobile: true, cell: (r) => `${dt(r.valid_from)} → ${dt(r.valid_to)}` },
    { key: "u", header: "Utilisations", align: "right", cell: (r) => r.used },
    { key: "a", header: "Statut", cell: (r) => <Badge tone={r.valid_now ? "success" : "gray"}>{r.valid_now ? "Valide" : r.active ? "Hors période" : "Désactivé"}</Badge> },
    { key: "x", header: "", align: "right", cell: (r) => <Button size="sm" variant="outline" onClick={() => void toggleCoupon(r)}>{r.active ? "Désactiver" : "Réactiver"}</Button> },
  ];
  const i = s.integrations;
  return (
    <>
      <PageHeader title="Réglages" description="Règles métier et état des intégrations. Chaque modification est validée, puis journalisée avec l’ancienne et la nouvelle valeur." />
      {notice ? <Alert tone="success" className="mb-4">{notice}</Alert> : null}

      <Section title="Intégrations" className="mb-6">
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 text-sm">
          <li className="flex items-center justify-between rounded-panel border border-lineSoft p-3"><span>Notifications push (Firebase)</span><Badge tone={i.push_fcm.configured ? "success" : "warning"}>{i.push_fcm.configured ? "Configuré" : "Non configuré"}</Badge></li>
          <li className="flex items-center justify-between rounded-panel border border-lineSoft p-3"><span>SMS{i.sms.provider ? ` (${i.sms.provider})` : ""}</span><Badge tone={i.sms.ready ? "success" : "warning"}>{i.sms.ready ? "Prêt" : "Non prêt"}</Badge></li>
          <li className="flex items-center justify-between rounded-panel border border-lineSoft p-3"><span>E-mail</span><Badge tone={i.email.real_delivery ? "success" : "warning"}>{i.email.real_delivery ? "Envoi réel" : "Console / test"}</Badge></li>
          {Object.entries(i.payments).map(([k, ok]) => <li key={k} className="flex items-center justify-between rounded-panel border border-lineSoft p-3"><span>{PAY_FR[k] ?? k}</span><Badge tone={ok ? "success" : "danger"}>{ok ? "Disponible" : "Non branché"}</Badge></li>)}
          <li className="flex items-center justify-between rounded-panel border border-lineSoft p-3"><span>Itinéraires (OSRM)</span><Badge tone={i.routing_osrm.configured ? "success" : "gray"}>{i.routing_osrm.configured ? "Configuré" : "Estimation simple"}</Badge></li>
          <li className="flex items-center justify-between rounded-panel border border-lineSoft p-3"><span>Stockage objet</span><Badge tone={i.object_storage.enabled ? "success" : "gray"}>{i.object_storage.enabled ? "Activé" : "Disque local"}</Badge></li>
        </ul>
        <p className="mt-3 text-xs text-ash">Lecture seule : seuls l’état (configuré ou non) est affiché, jamais une clé ou un identifiant. Les clés se règlent dans l’environnement du serveur.</p>
      </Section>

      <Section title="Commissions de la plateforme" className="mb-6" actions={<Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => openRule(null)}>Nouvelle règle</Button>}>
        <DataTable caption="Règles de commission" columns={ruleCols} rows={s.pricing_rules} rowKey={(r) => r.id} empty={<EmptyState title="Aucune règle de commission" compact />} />
      </Section>
      <Section title="Politique d’annulation" className="mb-6" actions={<Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => openPol(null)}>Nouvelle politique</Button>}>
        <p className="mb-3 text-xs text-ash">Une seule politique est appliquée : en activer une désactive les autres.</p>
        <DataTable caption="Politiques d’annulation" columns={polCols} rows={s.cancellation_policies} rowKey={(r) => r.id} empty={<EmptyState title="Aucune politique : l’annulation est toujours gratuite" compact />} />
      </Section>

      <Section title="Tratra Trust — seuils et poids" className="mb-6" actions={<Button size="sm" loading={trustBusy} onClick={() => void saveTrust()}>Enregistrer les seuils</Button>}>
        <Alert tone="info" className="mb-4">Les nouveaux seuils s’appliquent à la prochaine réévaluation (périodique ou déclenchée par un événement). Rien n’est attribué ni retiré à l’instant de l’enregistrement.</Alert>
        {trustFail ? <Alert tone="danger" className="mb-4">{trustFail}</Alert> : null}
        <div className="space-y-6">
          {TRUST_GROUPS.map(([title, keys]) => (
            <fieldset key={title}><legend className="mb-2 text-sm font-bold text-ink">{title}</legend>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {keys.filter((k) => k in tf).map((k) => <TextField key={k} label={s.trust_labels[k] ?? k} inputMode="decimal" value={tf[k]} error={trustErr[k]} onChange={(e) => setTf({ ...tf, [k]: e.target.value })} />)}
              </div></fieldset>
          ))}
        </div>
      </Section>

      <Section title="Codes promotionnels" actions={<Button size="sm" leftIcon={<Plus aria-hidden className="h-4 w-4" />} onClick={() => { setCf({ code: "", kind: "percent", value: "", valid_from: "", valid_to: "" }); setCouErr({}); setCouFail(""); setCou(true); }}>Nouveau code</Button>}>
        <p className="mb-3 text-xs text-ash">Une fois créé, seule l’activation d’un code est modifiable (jamais sa valeur).</p>
        <DataTable caption="Codes promotionnels" columns={couCols} rows={s.coupons} rowKey={(r) => r.id} empty={<EmptyState title="Aucun code promotionnel" compact />} />
      </Section>

      <FormModal open={Boolean(rule)} title={rule?.item ? "Modifier la règle de commission" : "Nouvelle règle de commission"} onClose={() => setRule(null)} onSubmit={saveRule}>
        <TextField label="Commission (%)" hint="Entre 0 et 50." inputMode="decimal" value={rf.fee_percent} error={ruleErr.fee_percent} onChange={(e) => setRf({ ...rf, fee_percent: e.target.value })} />
        <TextField label="Commission minimale (FCFA)" inputMode="numeric" value={rf.fee_min_xof} error={ruleErr.fee_min_xof} onChange={(e) => setRf({ ...rf, fee_min_xof: e.target.value })} />
        {!rule?.item ? (
          <label className="block text-sm font-semibold text-ink">Catégorie <span className="text-xs font-normal text-ash">(vide = règle générale)</span>
            <select className="mt-1.5 min-h-[48px] w-full rounded-control border border-line bg-white px-4 text-[15px]" value={rf.category} onChange={(e) => setRf({ ...rf, category: e.target.value })}><option value="">Toutes les catégories</option>{cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            {ruleErr.category ? <span role="alert" className="text-xs text-dangerInk">{ruleErr.category}</span> : null}</label>
        ) : null}
        <Checkbox label="Règle active" checked={rf.active} onChange={(e) => setRf({ ...rf, active: e.target.checked })} />
        {ruleFail && !Object.keys(ruleErr).length ? <Alert tone="danger">{ruleFail}</Alert> : null}
      </FormModal>
      <FormModal open={Boolean(pol)} title={pol?.item ? "Modifier la politique d’annulation" : "Nouvelle politique d’annulation"} onClose={() => setPol(null)} onSubmit={savePol}>
        <TextField label="Nom" value={pf.name} error={polErr.name} onChange={(e) => setPf({ ...pf, name: e.target.value })} />
        <TextField label="Annulation gratuite jusqu’à (minutes avant l’intervention)" inputMode="numeric" value={pf.free_until_minutes} error={polErr.free_until_minutes} onChange={(e) => setPf({ ...pf, free_until_minutes: e.target.value })} />
        <TextField label="Pénalité ensuite (% du montant)" inputMode="decimal" value={pf.fee_percent} error={polErr.fee_percent} onChange={(e) => setPf({ ...pf, fee_percent: e.target.value })} />
        <Checkbox label="Appliquer cette politique" checked={pf.active} onChange={(e) => setPf({ ...pf, active: e.target.checked })} />
        {polFail && !Object.keys(polErr).length ? <Alert tone="danger">{polFail}</Alert> : null}
      </FormModal>
      <FormModal open={cou} title="Nouveau code promotionnel" onClose={() => setCou(false)} onSubmit={saveCoupon} submitLabel="Créer le code">
        <TextField label="Code" hint="4 à 30 caractères : lettres, chiffres, - _" value={cf.code} error={couErr.code} onChange={(e) => setCf({ ...cf, code: e.target.value })} />
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm font-semibold text-ink">Type de réduction
            <select className="mt-1.5 min-h-[48px] w-full rounded-control border border-line bg-white px-4 text-[15px]" value={cf.kind} onChange={(e) => setCf({ ...cf, kind: e.target.value })}><option value="percent">Pourcentage</option><option value="amount">Montant fixe (FCFA)</option></select></label>
          <TextField label={cf.kind === "percent" ? "Pourcentage (1 à 100)" : "Montant (FCFA)"} inputMode="decimal" value={cf.value} error={couErr.value || undefined} onChange={(e) => setCf({ ...cf, value: e.target.value })} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm font-semibold text-ink">Début<Input className="mt-1.5" type="datetime-local" value={cf.valid_from} onChange={(e) => setCf({ ...cf, valid_from: e.target.value })} />{couErr.valid_from ? <span role="alert" className="text-xs text-dangerInk">{couErr.valid_from}</span> : null}</label>
          <label className="block text-sm font-semibold text-ink">Fin<Input className="mt-1.5" type="datetime-local" value={cf.valid_to} onChange={(e) => setCf({ ...cf, valid_to: e.target.value })} />{couErr.valid_to ? <span role="alert" className="text-xs text-dangerInk">{couErr.valid_to}</span> : null}</label>
        </div>
        {couFail && !Object.values(couErr).some(Boolean) ? <Alert tone="danger">{couFail}</Alert> : null}
      </FormModal>
    </>
  );
}
