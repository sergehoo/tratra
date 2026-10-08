"use client";
import { useState, type ReactNode } from "react";
import { ArrowRight, Bell, CalendarCheck, Inbox, Search, ShieldCheck, Wallet, Zap } from "lucide-react";
import tokens from "../../../design-system/tokens.json";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  DataTable,
  EmptyState,
  Field,
  Input,
  Modal,
  PageHeader,
  PasswordInput,
  Select,
  SelectField,
  SkeletonCard,
  SkeletonStats,
  SkeletonTable,
  SkeletonText,
  Stat,
  StatusBadge,
  Tabs,
  TextField,
  TextareaField,
  type BadgeTone,
  type ButtonVariant,
  type Column,
} from "@/components/ds";

const COLORS = tokens.color as Record<string, Record<string, string>>;

function Section({ id, title, hint, children }: { id: string; title: string; hint?: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-t`} className="scroll-mt-24 border-t border-line py-10 first:border-t-0">
      <h2 id={`${id}-t`} className="font-display text-2xl font-extrabold text-ink">
        {title}
      </h2>
      {hint ? <p className="mt-1 max-w-2xl text-sm text-ash">{hint}</p> : null}
      <div className="mt-6">{children}</div>
    </section>
  );
}

// Classes complètes (Tailwind ne génère pas de classe construite dynamiquement).
const SHADOWS: [string, string][] = [
  ["hair", "shadow-hair"],
  ["soft", "shadow-soft"],
  ["strong", "shadow-strong"],
  ["glow", "shadow-glow"],
  ["glowAccent", "shadow-glowAccent"],
];

const VARIANTS: ButtonVariant[] = ["primary", "accent", "night", "soft", "outline", "ghost", "danger"];
const TONES: BadgeTone[] = ["primary", "accent", "night", "gray", "success", "warning", "danger", "info"];

interface Row {
  id: number;
  name: string;
  trade: string;
  status: string;
  amount: string;
}
const ROWS: Row[] = [
  { id: 1, name: "Exemple A", trade: "Plomberie", status: "pending", amount: "15 000 FCFA" },
  { id: 2, name: "Exemple B", trade: "Électricité", status: "in_progress", amount: "32 500 FCFA" },
  { id: 3, name: "Exemple C", trade: "Peinture", status: "completed", amount: "58 000 FCFA" },
];
const COLUMNS: Column<Row>[] = [
  { key: "name", header: "Client", cell: (r) => r.name, primary: true },
  { key: "trade", header: "Métier", cell: (r) => r.trade },
  { key: "status", header: "Statut", cell: (r) => <StatusBadge kind="booking" status={r.status} /> },
  { key: "amount", header: "Montant", cell: (r) => r.amount, align: "right" },
];

export default function Styleguide() {
  const [tab, setTab] = useState<"all" | "open" | "done">("all");
  const [modal, setModal] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [loading, setLoading] = useState(false);

  return (
    <div className="min-h-screen bg-canvas">
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <PageHeader
          eyebrow="Design System · v1"
          title="Guide de style Tratra"
          description="Référence visuelle : la landing. Cette page est un outil de développement (indisponible en production) ; les données affichées sont des exemples de rendu."
        />

        <Section id="couleurs" title="Couleurs" hint="Vert de marque dominant, jaune et noir en accents. Texte blanc sur primaryDark (AA) ; primary pour grands titres, icônes et surfaces décoratives.">
          <div className="space-y-6">
            {Object.entries(COLORS).map(([group, colors]) => (
              <div key={group}>
                <h3 className="mb-3 text-xs font-bold uppercase tracking-[0.14em] text-ash">{group}</h3>
                <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                  {Object.entries(colors).map(([name, hex]) => (
                    <li key={name} className="overflow-hidden rounded-panel border border-line bg-white">
                      <div className="h-14" style={{ background: hex }} />
                      <div className="px-3 py-2">
                        <p className="text-sm font-semibold text-ink">{name}</p>
                        <p className="font-mono text-xs text-ash">{hex}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Section>

        <Section id="typo" title="Typographie" hint="Montserrat pour les titres, Poppins pour le texte.">
          <Card className="space-y-4">
            {Object.entries(tokens.type).map(([name, t]) => (
              <div key={name} className="flex flex-wrap items-baseline gap-x-6 gap-y-1 border-b border-lineSoft pb-3 last:border-0 last:pb-0">
                <span className="w-24 shrink-0 font-mono text-xs text-ash">{name}</span>
                <span
                  className={t.font === "display" ? "font-display" : "font-sans"}
                  style={{ fontSize: Math.min(t.size, 44), fontWeight: t.weight, lineHeight: t.line, letterSpacing: `${t.tracking}em`, textTransform: name === "eyebrow" ? "uppercase" : undefined }}
                >
                  L’artisan qu’il vous faut
                </span>
                <span className="ml-auto text-xs text-fog">
                  {t.size}/{t.sizeMobile} px · {t.weight}
                </span>
              </div>
            ))}
          </Card>
        </Section>

        <Section id="formes" title="Rayons, ombres, mouvement">
          <div className="grid gap-6 lg:grid-cols-3">
            <Card>
              <h3 className="mb-3 text-sm font-bold text-ink">Rayons</h3>
              <div className="flex flex-wrap gap-3">
                {Object.entries(tokens.radius).map(([name, px]) => (
                  <div key={name} className="text-center">
                    <div className="h-14 w-14 border-2 border-primary bg-primarySoft" style={{ borderRadius: Math.min(px, 28) }} />
                    <p className="mt-1 text-xs text-ash">
                      {name} {px < 999 ? px : "∞"}
                    </p>
                  </div>
                ))}
              </div>
            </Card>
            <Card>
              <h3 className="mb-3 text-sm font-bold text-ink">Ombres</h3>
              <div className="flex flex-wrap gap-4">
                {SHADOWS.map(([name, cls]) => (
                  <div key={name} className="text-center">
                    <div className={`h-14 w-14 rounded-2xl bg-white ${cls}`} />
                    <p className="mt-2 text-xs text-ash">{name}</p>
                  </div>
                ))}
              </div>
            </Card>
            <Card>
              <h3 className="mb-3 text-sm font-bold text-ink">Animations</h3>
              <div className="flex flex-wrap items-center gap-4">
                <span className="animate-rise rounded-xl bg-primarySoft px-3 py-2 text-xs font-semibold text-primaryDark">rise</span>
                <span className="animate-scaleIn rounded-xl bg-accentSoft px-3 py-2 text-xs font-semibold text-ink">scaleIn</span>
                <span className="inline-flex items-center gap-2 text-xs font-semibold text-successInk">
                  <span className="h-2 w-2 animate-pulseDot rounded-full bg-success" />
                  pulseDot
                </span>
                <div className="skeleton h-6 w-20" />
              </div>
            </Card>
          </div>
        </Section>

        <Section id="boutons" title="Boutons" hint="Pilule, cible tactile ≥ 44 px, retour d’appui discret.">
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-3">
              {VARIANTS.map((v) => (
                <Button key={v} variant={v}>
                  {v}
                </Button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button size="sm">Petit</Button>
              <Button size="md">Moyen</Button>
              <Button size="lg" rightIcon={<ArrowRight aria-hidden className="h-4 w-4" />}>
                Grand
              </Button>
              <Button loading>Chargement</Button>
              <Button disabled>Désactivé</Button>
              <ButtonLink href="/search" variant="outline" leftIcon={<Search aria-hidden className="h-4 w-4" />}>
                Lien-bouton
              </ButtonLink>
            </div>
            <div className="flex flex-wrap items-center gap-3 rounded-card bg-night p-6">
              <Button variant="accent" leftIcon={<Zap aria-hidden className="h-4 w-4" />}>
                Accent sur nuit
              </Button>
              <Button variant="outlineLight">Outline clair</Button>
            </div>
          </div>
        </Section>

        <Section id="formulaires" title="Champs de formulaire">
          <Card className="grid gap-5 md:grid-cols-2">
            <TextField label="Nom complet" placeholder="Prénom Nom" required hint="Tel qu’il apparaît sur votre pièce d’identité." />
            <TextField label="Téléphone" leading={<Search className="h-4 w-4" />} placeholder="07 00 00 00 00" />
            <TextField label="E-mail" type="email" defaultValue="adresse-invalide" error="Saisissez une adresse e-mail valide." />
            <Field label="Mot de passe" required>
              {(c) => <PasswordInput {...c} placeholder="••••••••" autoComplete="new-password" />}
            </Field>
            <SelectField label="Commune" defaultValue="">
              <option value="" disabled>
                Choisir…
              </option>
              <option>Cocody</option>
              <option>Marcory</option>
            </SelectField>
            <Field label="Champ désactivé">{(c) => <Input {...c} disabled defaultValue="Non modifiable" />}</Field>
            <TextareaField label="Description" className="md:col-span-2" fieldClassName="md:col-span-2" placeholder="Décrivez votre besoin…" optional />
            <Checkbox label="J’accepte les conditions d’utilisation" className="md:col-span-2" />
            <Select aria-label="Exemple sans étiquette" defaultValue="1" className="md:max-w-xs">
              <option value="1">Liste sans étiquette visible</option>
            </Select>
          </Card>
        </Section>

        <Section id="cartes" title="Cartes & indicateurs">
          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            <Card>
              <CardHeader title="Carte standard" description="Fond blanc, ombre douce." icon={<CalendarCheck className="h-5 w-5" />} action={<Badge>Actif</Badge>} />
              <p className="text-sm text-inkSoft">Contenu de la carte.</p>
            </Card>
            <Card variant="soft">
              <CardHeader title="Carte douce" description="Teinte verte de marque." />
            </Card>
            <Card variant="accent">
              <CardHeader title="Carte accent" description="Mise en avant jaune." />
            </Card>
            <Card variant="night" className="md:col-span-2 lg:col-span-1">
              <CardHeader title="Carte nuit" description="Surface sombre." />
            </Card>
            <Card interactive className="lg:col-span-2">
              <CardHeader title="Carte interactive" description="Survolez-moi : léger lift et ombre renforcée." />
            </Card>
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-3">
            <Stat label="Indicateur primaire" value="12" icon={<Wallet className="h-5 w-5" />} />
            <Stat label="Indicateur accent" value="3" icon={<Bell className="h-5 w-5" />} tone="accent" hint="Texte d’aide" />
            <Stat label="Indicateur nuit" value="98 %" icon={<ShieldCheck className="h-5 w-5" />} tone="night" />
          </div>
        </Section>

        <Section id="badges" title="Badges & statuts">
          <div className="flex flex-wrap gap-2">
            {TONES.map((t) => (
              <Badge key={t} tone={t} dot>
                {t}
              </Badge>
            ))}
            <Badge tone="night" pulse>
              En direct
            </Badge>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {["pending", "confirmed", "in_progress", "completed", "cancelled"].map((s) => (
              <StatusBadge key={s} kind="booking" status={s} />
            ))}
            {["pending", "approved", "rejected"].map((s) => (
              <StatusBadge key={s} kind="document" status={s} />
            ))}
            {["open", "under_review", "resolved"].map((s) => (
              <StatusBadge key={s} kind="dispute" status={s} />
            ))}
          </div>
          <div className="mt-4 flex items-center gap-3">
            <Avatar name="Aya Konan" size={48} />
            <Avatar name="Moussa Traoré" size={48} online />
            <Avatar name="T" size={32} />
          </div>
        </Section>

        <Section id="alertes" title="Alertes">
          <div className="grid gap-3 md:grid-cols-2">
            <Alert tone="info" title="Information">Votre demande a bien été enregistrée.</Alert>
            <Alert tone="success" title="Succès">Les modifications ont été enregistrées.</Alert>
            <Alert tone="warning" title="Attention" action={<Button size="sm" variant="outline">Compléter</Button>}>
              Un document est manquant.
            </Alert>
            <Alert tone="danger" title="Erreur" onDismiss={() => undefined}>
              L’action a échoué. Réessayez dans un instant.
            </Alert>
            <Alert tone="brand">Message de marque, sans titre.</Alert>
          </div>
        </Section>

        <Section id="navigation" title="Navigation & onglets" hint="L’AppShell (barre latérale ≥ lg, barre basse en mobile) est visible dans les espaces connectés.">
          <Tabs
            ariaLabel="Filtrer les exemples"
            value={tab}
            onChange={setTab}
            items={[
              { id: "all", label: "Tout", count: 3 },
              { id: "open", label: "En cours", count: 2 },
              { id: "done", label: "Terminées", count: 1 },
            ]}
          />
        </Section>

        <Section id="tableaux" title="Tableaux" hint="Tableau dès md, cartes empilées en mobile.">
          <DataTable columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} caption="Exemple de tableau" />
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <DataTable columns={COLUMNS} rows={[]} rowKey={(r) => r.id} caption="Tableau vide" empty={<EmptyState compact icon={<Inbox />} title="Aucune mission" description="Les missions apparaîtront ici dès qu’un client réservera l’un de vos services." />} />
            <SkeletonTable rows={3} cols={3} />
          </div>
        </Section>

        <Section id="squelettes" title="Squelettes & états vides">
          <div className="grid gap-5 lg:grid-cols-2">
            <div className="space-y-3">
              <SkeletonCard />
              <SkeletonText lines={3} />
              <SkeletonStats count={2} />
            </div>
            <EmptyState
              icon={<Inbox />}
              title="Rien à afficher pour le moment"
              description="Un état vide explique la situation réelle et propose une action utile."
              actions={<ButtonLink href="/search">Rechercher un artisan</ButtonLink>}
            />
          </div>
        </Section>

        <Section id="modales" title="Modales">
          <div className="flex flex-wrap gap-3">
            <Button variant="outline" onClick={() => setModal(true)}>
              Ouvrir une modale
            </Button>
            <Button variant="danger" onClick={() => setConfirm(true)}>
              Confirmation destructive
            </Button>
          </div>
          <Modal
            open={modal}
            onClose={() => setModal(false)}
            title="Titre de la modale"
            description="Feuille basse en mobile, carte centrée dès sm."
            footer={
              <>
                <Button variant="outline" onClick={() => setModal(false)}>
                  Fermer
                </Button>
                <Button onClick={() => setModal(false)}>Valider</Button>
              </>
            }
          >
            <TextField label="Champ de la modale" placeholder="Focus automatique" />
          </Modal>
          <ConfirmDialog
            open={confirm}
            onClose={() => setConfirm(false)}
            title="Rejeter ce document ?"
            description="Indiquez le motif communiqué à l’artisan."
            confirmLabel="Rejeter"
            tone="danger"
            loading={loading}
            onConfirm={() => {
              setLoading(true);
              window.setTimeout(() => {
                setLoading(false);
                setConfirm(false);
              }, 900);
            }}
          >
            <TextareaField label="Motif" placeholder="Document illisible…" />
          </ConfirmDialog>
        </Section>
      </div>
    </div>
  );
}
