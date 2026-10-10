"use client";
import { Alert, Checkbox, SelectField, TextField, TextareaField } from "@/components/ds";
import type { Category } from "@/lib/types";
import {
  MISSION_TYPE_FR, PERIOD_FR, PERIOD_LABEL, RELATIONSHIP_FR, type ContractDetail, type MissionType, type PayPeriod, type Posting, type Relationship, type Rules, type ScheduleSlot,
} from "@/lib/engagements";
import { ScheduleEditor } from "./common";

/** Conditions d'un besoin ou d'un contrat : un seul formulaire, deux modes (le serveur revalide tout). */
export interface TermsValue {
  category: string; title: string; description: string; conditions: string; mission_type: MissionType; work_relationship: Relationship; ack: boolean; city: string; address: string;
  start_date: string; end_date: string; application_deadline: string; schedule: ScheduleSlot[]; amount: string; period: PayPeriod; payment_day: string; auto_renew: boolean;
  renewal_term_months: string; proration_mode: string; overtime_hourly_rate: string; notice_period_days: string; bookings_mode: string; organization: string;
}

export const emptyTerms = (): TermsValue => ({
  category: "", title: "", description: "", conditions: "", mission_type: "long_term", work_relationship: "independent", ack: false, city: "", address: "", start_date: "", end_date: "",
  application_deadline: "", schedule: [], amount: "", period: "monthly", payment_day: "5", auto_renew: false, renewal_term_months: "12", proration_mode: "none", overtime_hourly_rate: "",
  notice_period_days: "7", bookings_mode: "none", organization: "",
});

const num = (v: string | null | undefined) => (v ? String(Math.round(Number(v) * 100) / 100).replace(/\.0+$/, "") : "");

export function termsFromPosting(p: Posting): TermsValue {
  return { ...emptyTerms(), category: String(p.category.id), title: p.title, description: p.description ?? "", conditions: p.conditions ?? "", mission_type: p.mission_type, work_relationship: p.work_relationship,
    ack: Boolean(p.employment_notice_ack), city: p.city, address: p.location_note ?? "", start_date: p.start_date ?? "", end_date: p.end_date ?? "", application_deadline: p.application_deadline ?? "",
    schedule: p.schedule ?? [], amount: num(p.amount), period: p.period, organization: p.organization ? String(p.organization.id) : "" };
}

export function termsFromContract(c: ContractDetail): TermsValue {
  return { ...emptyTerms(), category: String(c.category.id), title: c.title, description: c.description, conditions: c.conditions, mission_type: c.mission_type, work_relationship: c.work_relationship, ack: c.legal_notice_ack,
    city: c.location_city, address: c.location_address, start_date: c.start_date, end_date: c.end_date ?? "", schedule: c.schedule, amount: num(c.amount), period: c.period,
    payment_day: String(c.payment_day ?? 5), auto_renew: c.auto_renew, renewal_term_months: String(c.renewal_term_months ?? 12), proration_mode: c.proration_mode,
    overtime_hourly_rate: num(c.overtime_hourly_rate), notice_period_days: String(c.notice_period_days), bookings_mode: c.bookings_mode };
}

/** Corps d'un besoin publié. */
export function postingBody(v: TermsValue) {
  return { category: Number(v.category) || null, title: v.title.trim(), description: v.description.trim(), conditions: v.conditions.trim(), mission_type: v.mission_type, work_relationship: v.work_relationship,
    employment_notice_ack: v.work_relationship === "employment" && v.ack, city: v.city.trim(), location_note: v.address.trim(), start_date: v.start_date || null, end_date: v.end_date || null,
    application_deadline: v.application_deadline || null, schedule: v.schedule, amount: v.amount.trim(), period: v.period, ...(v.organization ? { organization: Number(v.organization) } : {}) };
}

/** Corps d'un contrat (brouillon). */
export function contractBody(v: TermsValue) {
  return { category_id: Number(v.category) || null, title: v.title.trim(), description: v.description.trim(), conditions: v.conditions.trim(), mission_type: v.mission_type, work_relationship: v.work_relationship,
    legal_notice_ack: v.work_relationship === "employment" && v.ack, location_city: v.city.trim(), location_address: v.address.trim(), start_date: v.start_date, end_date: v.end_date || null,
    auto_renew: v.auto_renew && Boolean(v.end_date), renewal_term_months: v.auto_renew && v.end_date ? Number(v.renewal_term_months) || null : null, schedule: v.schedule, amount: v.amount.trim(), period: v.period,
    payment_day: Number(v.payment_day) || null, proration_mode: v.proration_mode, overtime_hourly_rate: v.overtime_hourly_rate.trim() || null,
    notice_period_days: Number(v.notice_period_days), bookings_mode: v.bookings_mode };
}

export function TermsFields({
  mode, value, onChange, errors, categories, rules, disabled, organizations,
}: {
  mode: "posting" | "contract"; value: TermsValue; onChange: (v: TermsValue) => void; errors: Record<string, string>; categories: Category[]; rules: (categoryId: string) => Rules | null;
  disabled?: boolean; organizations?: { id: number; name: string }[];
}) {
  const set = <K extends keyof TermsValue>(k: K, v: TermsValue[K]) => onChange({ ...value, [k]: v });
  const r = rules(value.category);
  const employmentOk = r?.allow_employment ?? false;
  const e = (k: string) => errors[k];
  const isContract = mode === "contract";
  return (
    <div className="space-y-5">
      {organizations && organizations.length > 0 && mode === "posting" ? (
        <SelectField label="Publier au nom de" optional disabled={disabled} value={value.organization} onChange={(ev) => set("organization", ev.target.value)} hint="Votre organisation Tratra Business, si vous y êtes habilité.">
          <option value="">Moi-même</option>
          {organizations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </SelectField>
      ) : null}
      <TextField label="Intitulé" required disabled={disabled} value={value.title} maxLength={160} error={e("title")} onChange={(ev) => set("title", ev.target.value)} placeholder="Ex. Gardien de nuit — résidence Les Palmiers" />
      <SelectField label="Métier" required disabled={disabled} value={value.category} error={e("category") ?? e("category_id")} onChange={(ev) => set("category", ev.target.value)}>
        <option value="">Choisir un métier</option>
        {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </SelectField>
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Type de mission" required disabled={disabled} value={value.mission_type} error={e("mission_type")} onChange={(ev) => set("mission_type", ev.target.value as MissionType)}
          hint="Une intervention unique se réserve depuis « Explorer les services ».">
          {(Object.keys(MISSION_TYPE_FR) as MissionType[]).map((k) => (
            <option key={k} value={k} disabled={r ? (k === "long_term" ? !r.allow_long_term : !r.allow_recurring) : false}>{MISSION_TYPE_FR[k]}</option>
          ))}
        </SelectField>
        <SelectField label="Nature de la relation" required disabled={disabled} value={value.work_relationship} error={e("work_relationship")} onChange={(ev) => set("work_relationship", ev.target.value as Relationship)}>
          <option value="independent">{RELATIONSHIP_FR.independent}</option>
          <option value="employment" disabled={!employmentOk}>{RELATIONSHIP_FR.employment}{employmentOk ? "" : " (non ouvert pour ce métier)"}</option>
        </SelectField>
      </div>
      {value.work_relationship === "employment" ? (
        <Alert tone="warning" title="Emploi salarié">
          <p>Un emploi salarié relève du droit du travail applicable. Tratra met en relation et garde la trace de vos accords, mais n’est pas un conseil juridique et ne calcule ni cotisations, ni impôts, ni congés payés : vous restez responsables de vos obligations légales.</p>
          <div className="mt-3">
            <Checkbox disabled={disabled} checked={value.ack} onChange={(ev) => set("ack", ev.target.checked)} label="J’ai compris que Tratra ne gère pas le volet légal de l’emploi salarié." />
            {e("employment_notice_ack") ?? e("legal_notice_ack") ? <p role="alert" className="mt-1 text-xs font-medium text-dangerInk">{e("employment_notice_ack") ?? e("legal_notice_ack")}</p> : null}
          </div>
        </Alert>
      ) : null}
      <TextareaField label={isContract ? "Missions confiées" : "Description du besoin"} required={!isContract} disabled={disabled} rows={5} value={value.description} maxLength={4000} error={e("description")} onChange={(ev) => set("description", ev.target.value)} />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Ville" required disabled={disabled} value={value.city} error={e("city") ?? e("location_city")} onChange={(ev) => set("city", ev.target.value)} />
        <TextField label={isContract ? "Adresse du lieu de travail" : "Quartier ou zone"} optional disabled={disabled} value={value.address} error={e("location_note") ?? e("location_address")} onChange={(ev) => set("address", ev.target.value)}
          hint={isContract ? "Visible des deux parties une fois le contrat proposé." : "Ne mettez pas l’adresse exacte dans une offre publique."} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label={isContract ? "Début" : "Début souhaité"} type="date" required={isContract} optional={!isContract} disabled={disabled} value={value.start_date} error={e("start_date")} onChange={(ev) => set("start_date", ev.target.value)} />
        <TextField label={isContract ? "Fin (vide = durée indéterminée)" : "Fin souhaitée (vide = indéterminée)"} type="date" optional disabled={disabled} value={value.end_date} error={e("end_date")} onChange={(ev) => set("end_date", ev.target.value)}
          hint={r ? `Durée maximale pour ce métier : ${r.max_duration_months} mois.` : undefined} />
      </div>
      {mode === "posting" ? (
        <TextField label="Date limite de candidature" type="date" optional disabled={disabled} value={value.application_deadline} error={e("application_deadline")} onChange={(ev) => set("application_deadline", ev.target.value)} />
      ) : null}
      <ScheduleEditor value={value.schedule} onChange={(s) => set("schedule", s)} error={e("schedule")} disabled={disabled} />
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Rémunération" required disabled={disabled} value={value.period} error={e("period")} onChange={(ev) => set("period", ev.target.value as PayPeriod)}>
          {(Object.keys(PERIOD_LABEL) as PayPeriod[]).map((k) => <option key={k} value={k}>{PERIOD_LABEL[k]}</option>)}
        </SelectField>
        <TextField label={`Montant (FCFA ${PERIOD_FR[value.period]})`} required inputMode="decimal" disabled={disabled} value={value.amount} error={e("amount")} onChange={(ev) => set("amount", ev.target.value)} />
      </div>
      {isContract ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="Jour de paiement du mois" inputMode="numeric" disabled={disabled} value={value.payment_day} error={e("payment_day")} onChange={(ev) => set("payment_day", ev.target.value)} hint="Entre 1 et 31 ; le paiement est déclaré puis confirmé par l’autre partie." />
            <TextField label="Préavis (jours)" inputMode="numeric" disabled={disabled} value={value.notice_period_days} error={e("notice_period_days")} onChange={(ev) => set("notice_period_days", ev.target.value)}
              hint={r ? `Minimum pour ce métier : ${value.work_relationship === "employment" ? r.min_notice_days_employment : r.min_notice_days_independent} jours.` : undefined} />
          </div>
          {value.period === "monthly" ? (
            <SelectField label="Dernière période incomplète" disabled={disabled} value={value.proration_mode} error={e("proration_mode")} onChange={(ev) => set("proration_mode", ev.target.value)}
              hint="Tratra n’invente aucun prorata : sans clause, la dernière période est payée au montant du contrat.">
              <option value="none">Montant du contrat (aucun prorata)</option>
              <option value="calendar_days">Prorata au nombre de jours calendaires (convenu entre nous)</option>
            </SelectField>
          ) : null}
          <TextField label="Taux horaire des heures supplémentaires (FCFA, facultatif)" inputMode="decimal" optional disabled={disabled} value={value.overtime_hourly_rate} error={e("overtime_hourly_rate")} onChange={(ev) => set("overtime_hourly_rate", ev.target.value)}
            hint="Sans taux au contrat, les heures supplémentaires sont enregistrées mais jamais valorisées par Tratra." />
          <div className="space-y-3 rounded-panel border border-lineSoft p-4">
            <Checkbox disabled={disabled || !value.end_date} checked={value.auto_renew && Boolean(value.end_date)} onChange={(ev) => set("auto_renew", ev.target.checked)} label="Renouveler automatiquement à l’échéance (sauf non-renouvellement dans le délai de préavis)" />
            {value.auto_renew && value.end_date ? <TextField label="Durée de chaque renouvellement (mois)" inputMode="numeric" disabled={disabled} value={value.renewal_term_months} error={e("renewal_term_months")} onChange={(ev) => set("renewal_term_months", ev.target.value)} /> : null}
            {!value.end_date ? <p className="text-xs text-ash">Le renouvellement ne concerne que les contrats à durée déterminée.</p> : null}
          </div>
          {value.work_relationship === "independent" && value.schedule.length > 0 ? (
            <Checkbox disabled={disabled} checked={value.bookings_mode === "per_occurrence"} onChange={(ev) => set("bookings_mode", ev.target.checked ? "per_occurrence" : "none")}
              label="Créer une réservation Tratra par intervention (suivi, avis et litiges de chaque intervention)" />
          ) : null}
          {errors.bookings_mode ? <p role="alert" className="text-xs font-medium text-dangerInk">{errors.bookings_mode}</p> : null}
        </>
      ) : null}
      <TextareaField label="Conditions particulières" optional disabled={disabled} rows={4} value={value.conditions} maxLength={4000} error={e("conditions")} onChange={(ev) => set("conditions", ev.target.value)}
        hint="Tenue, matériel fourni, déplacements… Tout ce dont vous convenez doit figurer ici." />
    </div>
  );
}
