"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Briefcase, CalendarCheck, ExternalLink, Hammer, Scale, ShieldCheck, type LucideIcon } from "lucide-react";
import { get } from "@/lib/api";
import { API_BASE } from "@/lib/config";
import { formatCount } from "@/lib/format";
import { Alert, Button, ButtonLink, PageHeader, SkeletonStats, Stat } from "@/components/ds";

type CountKey = "bookings" | "services" | "handymen" | "disputes";
type Counts = Record<CountKey, number | null>;

/** Compteur réel d'une ressource ; `null` si l'appel échoue (jamais un faux « 0 »). */
async function count(path: string): Promise<number | null> {
  try {
    const d = await get<{ count?: number; results?: unknown[] }>(`${path}?page_size=1`);
    return d.count ?? d.results?.length ?? 0;
  } catch {
    return null;
  }
}

const CARDS: { key: CountKey; label: string; icon: LucideIcon; tone: "primary" | "accent" }[] = [
  { key: "bookings", label: "Réservations", icon: CalendarCheck, tone: "primary" },
  { key: "services", label: "Services", icon: Briefcase, tone: "primary" },
  { key: "handymen", label: "Artisans", icon: Hammer, tone: "primary" },
  { key: "disputes", label: "Litiges", icon: Scale, tone: "accent" },
];

/** L'admin Django vit à la racine de l'hôte du back-end (même origine que l'API). */
function djangoAdminUrl(): string | null {
  try {
    return new URL("/admin/", API_BASE).href;
  } catch {
    return null;
  }
}

export default function AdminHome() {
  const [s, setS] = useState<Counts | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([count("/bookings/"), count("/services/"), count("/handymen/"), count("/disputes/")]).then(
      ([bookings, services, handymen, disputes]) => {
        if (!alive.current) return;
        setS({ bookings, services, handymen, disputes });
        setLoading(false);
      },
    );
  }, []);

  useEffect(() => {
    alive.current = true;
    load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  const unavailable = !loading && s !== null && CARDS.some((c) => s[c.key] === null);
  const adminUrl = djangoAdminUrl();

  return (
    <>
      <PageHeader
        eyebrow="Back-office"
        title="Vue d’ensemble"
        description="Les chiffres clés de la plateforme, à jour au chargement de la page."
        actions={
          <>
            <ButtonLink href="/admin/disputes" leftIcon={<Scale aria-hidden className="h-4 w-4" />}>
              Traiter les litiges
            </ButtonLink>
            <ButtonLink href="/admin/kyc" variant="outline" leftIcon={<ShieldCheck aria-hidden className="h-4 w-4" />}>
              Vérifications KYC
            </ButtonLink>
          </>
        }
      />

      <div className="space-y-6">
        {unavailable ? (
          <Alert
            tone="danger"
            title="Certains compteurs sont indisponibles"
            action={
              <Button size="sm" variant="outline" onClick={load}>
                Réessayer
              </Button>
            }
          >
            Les valeurs affichées « — » n’ont pas pu être chargées depuis le service. Elles ne sont pas égales à zéro.
          </Alert>
        ) : null}

        {loading || s === null ? (
          <SkeletonStats count={4} className="sm:!grid-cols-2 lg:!grid-cols-4" />
        ) : (
          <div className="grid animate-rise gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {CARDS.map(({ key, label, icon: Icon, tone }) => {
              const value = s[key];
              return (
                <Stat
                  key={key}
                  label={label}
                  value={value === null ? "—" : formatCount(value)}
                  hint={value === null ? "Indisponible" : undefined}
                  tone={tone}
                  icon={<Icon className="h-6 w-6" />}
                />
              );
            })}
          </div>
        )}

        <Alert
          tone="brand"
          title="Administration avancée"
          action={
            adminUrl ? (
              <ButtonLink
                href={adminUrl}
                target="_blank"
                size="sm"
                variant="outline"
                rightIcon={<ExternalLink aria-hidden className="h-4 w-4" />}
              >
                Ouvrir l’admin Django
              </ButtonLink>
            ) : undefined
          }
        >
          L’administration détaillée reste disponible via l’admin Django, en attendant l’extension du back-office React.
        </Alert>
      </div>
    </>
  );
}
