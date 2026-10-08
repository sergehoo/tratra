import {
  AirVent, Armchair, Baby, BookOpen, BrickWall, Car, CarFront, Cctv, Droplets, Flame, Fence, Frame,
  Grid3x3, Hammer, House, KeyRound, Laptop, Leaf, Music, Package, PaintRoller, PartyPopper, PawPrint,
  Smartphone, Sofa, Sparkles, SprayCan, Sprout, Thermometer, Trash2, Truck, Utensils, WashingMachine,
  Waves, Wrench, Zap, type LucideIcon,
} from "lucide-react";
import type { Category } from "./types";

/**
 * Familles de métiers mises en avant (landing, raccourcis de recherche).
 * Chaque famille est ADOSSÉE à des catégories réelles du backend via leurs
 * slugs : une famille dont aucune catégorie n'existe/n'est active n'est jamais
 * affichée (pas de lien mort, pas de métier fictif).
 */
export interface TradeFamily {
  key: string;
  label: string;
  /** Slugs backend couverts — le premier existant sert de référence. */
  slugs: string[];
  icon: LucideIcon;
  blurb: string;
}

export const TRADE_FAMILIES: TradeFamily[] = [
  { key: "plomberie", label: "Plomberie", slugs: ["plomberie"], icon: Droplets,
    blurb: "Fuites, sanitaires, chauffe-eau" },
  { key: "electricite", label: "Électricité", slugs: ["electricite"], icon: Zap,
    blurb: "Pannes, tableaux, éclairage" },
  { key: "climatisation", label: "Climatisation", slugs: ["climatisation", "chauffage"], icon: AirVent,
    blurb: "Installation, entretien, recharge" },
  { key: "serrurerie", label: "Serrurerie", slugs: ["serrurerie"], icon: KeyRound,
    blurb: "Ouverture de porte, serrures" },
  { key: "peinture", label: "Peinture", slugs: ["peinture"], icon: PaintRoller,
    blurb: "Intérieur, extérieur, finitions" },
  { key: "bricolage", label: "Bricolage", slugs: ["bricolage", "montage-meuble"], icon: Hammer,
    blurb: "Petits travaux, montage, fixation" },
  { key: "menage", label: "Ménage", slugs: ["menage", "nettoyage-apres-travaux"], icon: Sparkles,
    blurb: "Entretien régulier, grand nettoyage" },
  { key: "jardinage", label: "Jardinage", slugs: ["jardinage", "paysagisme", "entretien-piscine"], icon: Sprout,
    blurb: "Tonte, taille, espaces verts" },
  { key: "mecanique", label: "Mécanique", slugs: ["mecanique-auto", "carrosserie", "lavage-auto"], icon: CarFront,
    blurb: "Entretien, diagnostic, carrosserie" },
  { key: "informatique", label: "Informatique",
    slugs: ["assistance-informatique", "reparation-ordinateur", "reparation-smartphone"], icon: Laptop,
    blurb: "Dépannage PC, réseau, smartphone" },
  { key: "demenagement", label: "Déménagement", slugs: ["demenagement", "debarras"], icon: Truck,
    blurb: "Transport, manutention, débarras" },
  { key: "domestique", label: "Services domestiques",
    slugs: ["garde-denfants", "garde-danimaux", "service-traiteur", "surveillance-maison", "cours-particulier", "chauffeur-prive"],
    icon: House, blurb: "Garde, cuisine, aide à domicile" },
  { key: "batiment", label: "Maçonnerie & BTP",
    slugs: ["maconnerie", "carrelage", "toiture", "platrerie", "isolation", "cloture", "terrasse"], icon: BrickWall,
    blurb: "Gros œuvre, carrelage, toiture" },
  { key: "menuiserie", label: "Menuiserie",
    slugs: ["menuiserie", "ebenisterie", "ferronnerie", "pose-parquet", "vitrerie"], icon: Armchair,
    blurb: "Bois, métal, parquet, vitrerie" },
  { key: "electromenager", label: "Électroménager",
    slugs: ["installation-electromenager", "reparation-electromenager"], icon: WashingMachine,
    blurb: "Installation et réparation" },
];

/** Icône par slug de catégorie réelle (repli : clé à molette). */
const ICON_BY_SLUG: Record<string, LucideIcon> = {
  plomberie: Droplets, electricite: Zap, climatisation: AirVent, chauffage: Thermometer,
  serrurerie: KeyRound, peinture: PaintRoller, bricolage: Hammer, "montage-meuble": Sofa,
  menage: Sparkles, "nettoyage-apres-travaux": SprayCan, jardinage: Sprout, paysagisme: Leaf,
  "entretien-piscine": Waves, "mecanique-auto": CarFront, carrosserie: Car, "lavage-auto": Car,
  "assistance-informatique": Laptop, "reparation-ordinateur": Laptop, "reparation-smartphone": Smartphone,
  demenagement: Truck, debarras: Trash2, "garde-denfants": Baby, "garde-danimaux": PawPrint,
  "service-traiteur": Utensils, "surveillance-maison": Cctv, "cours-particulier": BookOpen,
  "chauffeur-prive": Car, maconnerie: BrickWall, carrelage: Grid3x3, toiture: House, platrerie: BrickWall,
  isolation: Flame, cloture: Fence, terrasse: Grid3x3, "allee-jardin": Leaf, menuiserie: Armchair,
  ebenisterie: Armchair, ferronnerie: Hammer, "pose-parquet": Grid3x3, vitrerie: Frame, "sol-pvc": Grid3x3,
  "installation-electromenager": WashingMachine, "reparation-electromenager": WashingMachine,
  "animation-evenement": Music, "decoration-evenement": PartyPopper,
};

export function iconForCategory(slug?: string | null): LucideIcon {
  return (slug && ICON_BY_SLUG[slug]) || Wrench;
}

export interface ResolvedTrade extends TradeFamily {
  /** Catégories réelles (actives) couvertes par la famille. */
  categories: Category[];
  /** Somme des services actifs (null si le backend ne fournit pas le compte). */
  servicesCount: number | null;
  /** Lien de recherche réel : /search?metier=slug1,slug2 */
  href: string;
}

/** Ne garde que les familles adossées à au moins une catégorie active réelle. */
export function resolveTrades(categories: Category[]): ResolvedTrade[] {
  const bySlug = new Map(categories.filter((c) => c.is_active !== false).map((c) => [c.slug, c]));
  return TRADE_FAMILIES.flatMap((family) => {
    const cats = family.slugs.map((s) => bySlug.get(s)).filter((c): c is Category => Boolean(c));
    if (!cats.length) return [];
    const counts = cats.map((c) => c.services_count);
    const servicesCount = counts.every((n) => typeof n === "number")
      ? (counts as number[]).reduce((a, b) => a + b, 0)
      : null;
    return [{
      ...family,
      categories: cats,
      servicesCount,
      href: `/search?metier=${cats.map((c) => c.slug).join(",")}`,
    }];
  });
}

/** Icône neutre exportée pour les états vides. */
export const FallbackTradeIcon = Package;
