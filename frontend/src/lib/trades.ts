import {
  Accessibility, Baby, Banknote, Bath, Bed, Bike, BookOpen, BrickWall, Briefcase, Brush, Building2, Bus, Cake, Camera, Car, CarFront, CarTaxiFront, Carrot, Cat,
  ClipboardCheck, Cog, Coffee, ConciergeBell, CookingPot, Cookie, Croissant, Dog, DoorClosed, DoorOpen, Droplet, Droplets, Dumbbell, Egg, Fan, Fish, Flame, Flower2,
  Frame, Fuel, GlassWater, Gem, Gift, GraduationCap, Grid3x3, Guitar, HandHeart, HandHelping, Handshake, HardHat, Headphones, Heart, HeartPulse, House, IceCreamCone,
  KeyRound, Laptop, Layers, Leaf, Lightbulb, Lock, Monitor, Music, Package, Boxes, Paintbrush, PaintRoller, Palette, PartyPopper, PawPrint, Pen, Pizza, Plug, Printer,
  Presentation, Recycle, Route, Ruler, Sandwich, Scissors, Settings, ShieldCheck, Shirt, ShowerHead, Smartphone, Snowflake, Soup, Sofa, Sparkles, SprayCan, Sprout,
  Star, Stethoscope, Store, Sun, Tag, Thermometer, TreeDeciduous, Tractor, Trash2, Truck, Tv, User, Users, Utensils, Video, Waves, Wifi, Wind, Wine, Wrench, Zap,
  Armchair, Blend, Hammer, type LucideIcon,
} from "lucide-react";
import type { Category } from "./types";

/**
 * Catalogue des métiers : AUCUNE liste écrite en dur. La source unique est la base (Django `ServiceCategory`), lue via `GET /handy/catalog/` :
 *   MÉTIER     = catégorie racine (« Jardinage », « Cuisine », « Nounou »)
 *   PRESTATION = sous-catégorie d'un métier
 *   OFFRE      = service publié par un professionnel (compté dans `offers_total`)
 * Un métier actif est toujours affiché, même sans offre. Le web et l'application mobile lisent la même réponse.
 */

/** Icône par clé du vocabulaire commun (noms Font Awesome 6 saisis dans l'administration) ; liste de référence : `handy/catalog.py` (ICON_KEYS). */
export const ICON_BY_KEY: Record<string, LucideIcon> = {
  wrench: Wrench, "screwdriver-wrench": Wrench, screwdriver: Wrench, hammer: Hammer, toolbox: Briefcase, "paint-roller": PaintRoller, paintbrush: Paintbrush, brush: Brush,
  faucet: Droplets, "faucet-drip": Droplets, droplet: Droplet, shower: ShowerHead, bath: Bath, toilet: Droplets, bolt: Zap, plug: Plug, lightbulb: Lightbulb, fire: Flame,
  "fire-flame-curved": Flame, "temperature-half": Thermometer, snowflake: Snowflake, wind: Wind, fan: Fan, key: KeyRound, lock: Lock, "door-open": DoorOpen,
  "door-closed": DoorClosed, house: House, "house-chimney": House, "house-chimney-crack": House, building: Building2, warehouse: Store, trowel: BrickWall,
  "trowel-bricks": BrickWall, "ruler-combined": Ruler, "border-all": Grid3x3, "layer-group": Layers, chair: Armchair, couch: Sofa, bed: Bed, "window-maximize": Frame,
  igloo: Snowflake, "helmet-safety": HardHat, gear: Settings, gears: Cog,
  utensils: Utensils, "kitchen-set": CookingPot, "bowl-food": Soup, "mug-hot": Coffee, burger: Sandwich, "pizza-slice": Pizza, "cake-candles": Cake, blender: Blend, jar: Package,
  "wine-glass": Wine, "cookie-bite": Cookie, "bread-slice": Croissant, carrot: Carrot, fish: Fish, egg: Egg, "ice-cream": IceCreamCone,
  "user-nurse": HeartPulse, baby: Baby, "baby-carriage": Baby, child: Baby, children: Users, person: User, "people-group": Users, "user-group": Users,
  "hands-holding-child": HandHeart, "hand-holding-heart": HandHeart, heart: Heart, "heart-pulse": HeartPulse, stethoscope: Stethoscope, wheelchair: Accessibility, "user-doctor": Stethoscope,
  broom: Sparkles, soap: Sparkles, "spray-can-sparkles": SprayCan, shirt: Shirt, "jug-detergent": SprayCan, trash: Trash2, "trash-can": Trash2, recycle: Recycle, dumpster: Trash2,
  truck: Truck, "truck-ramp-box": Truck, "truck-fast": Truck, car: Car, "car-side": CarFront, taxi: CarTaxiFront, bus: Bus, motorcycle: Bike, bicycle: Bike, "gas-pump": Fuel,
  road: Route, "van-shuttle": Bus,
  laptop: Laptop, "laptop-code": Laptop, computer: Monitor, "mobile-screen-button": Smartphone, wifi: Wifi, camera: Camera, video: Video, tv: Tv, headphones: Headphones, print: Printer,
  music: Music, guitar: Guitar, book: BookOpen, "graduation-cap": GraduationCap, "chalkboard-user": Presentation, pen: Pen, palette: Palette, "camera-retro": Camera,
  futbol: Star, dumbbell: Dumbbell, "champagne-glasses": PartyPopper, gift: Gift, ring: Gem,
  paw: PawPrint, dog: Dog, cat: Cat, seedling: Sprout, leaf: Leaf, tree: TreeDeciduous, tractor: Tractor, sun: Sun, "water-ladder": Waves, "person-swimming": Waves, spa: Flower2,
  handshake: Handshake, "handshake-angle": HandHelping, "bell-concierge": ConciergeBell, "shield-halved": ShieldCheck, "user-shield": ShieldCheck, box: Package, "boxes-stacked": Boxes,
  "clipboard-check": ClipboardCheck, scissors: Scissors, "glass-water": GlassWater, store: Store, briefcase: Briefcase, "money-bill-wave": Banknote, tag: Tag, star: Star,
};

export const DEFAULT_ICON: LucideIcon = Wrench;

/** Icône d'une catégorie : clé normalisée du serveur (`icon_key`), sinon icône par défaut. Jamais de table par slug côté web. */
export function iconForCategory(category?: Pick<Category, "icon_key"> | null): LucideIcon {
  return (category?.icon_key && ICON_BY_KEY[category.icon_key]) || DEFAULT_ICON;
}

/** Un métier du catalogue, prêt à afficher (landing, recherche, pied de page). */
export interface ResolvedTrade {
  /** Slug du métier (stable). */
  key: string;
  id: number;
  label: string;
  /** Slugs du métier et de ses prestations actives (filtre de recherche `?metier=`). */
  slugs: string[];
  icon: LucideIcon;
  /** Description saisie dans l'administration, sinon les premières prestations. */
  blurb: string;
  featured: boolean;
  position: number;
  /** Métier + prestations, dans l'ordre du catalogue. */
  categories: Category[];
  /** Prestations seules (sous-catégories actives). */
  prestations: Category[];
  /** Offres publiées dans le métier et ses prestations (null si le serveur ne le fournit pas). */
  offersTotal: number | null;
  /** Alias de `offersTotal` (anciens consommateurs). */
  servicesCount: number | null;
  /** Lien de recherche réel : /search?metier=slug1,slug2 */
  href: string;
}

const DEFAULT_POSITION = 100;
const collator = new Intl.Collator("fr", { sensitivity: "base" });

function byOrder(a: Category, b: Category): number {
  if (a.order != null && b.order != null) return a.order - b.order;      // rang calculé par le serveur : identique pour le site et l'application
  return (a.position ?? DEFAULT_POSITION) - (b.position ?? DEFAULT_POSITION) || collator.compare(a.name, b.name) || a.id - b.id;
}

/**
 * Construit les métiers à partir du catalogue (liste à plat). Le métier est la racine (`parent` vide) ; ses prestations sont les catégories actives
 * qui en descendent. Un métier actif sans prestation ni offre est CONSERVÉ : seule une désactivation dans l'administration le retire.
 */
export function resolveTrades(items: Category[]): ResolvedTrade[] {
  const active = items.filter((c) => c.is_active !== false);
  const byId = new Map(active.map((c) => [c.id, c]));
  const rootOf = (c: Category): number | null => {
    const seen = new Set<number>();
    let node: Category | undefined = c;
    while (node && node.parent != null) {
      if (seen.has(node.id)) return null;
      seen.add(node.id);
      node = byId.get(node.parent);
      if (!node) return null;     // parent absent ou masqué : la prestation disparaît avec son métier
    }
    return node ? node.id : null;
  };
  const roots = active.filter((c) => c.parent == null).sort(byOrder);
  const members = new Map<number, Category[]>();
  for (const c of active) {
    if (c.parent == null) continue;
    const root = rootOf(c);
    if (root !== null) members.set(root, [...(members.get(root) ?? []), c]);
  }
  return roots.map((root) => {
    const prestations = (members.get(root.id) ?? []).sort(byOrder);
    const categories = [root, ...prestations];
    const total = typeof root.offers_total === "number" ? root.offers_total : typeof root.services_count === "number" ? root.services_count : null;
    const blurb = (root.description ?? "").trim() || prestations.slice(0, 3).map((p) => p.name).join(", ");
    return {
      key: root.slug,
      id: root.id,
      label: root.name,
      slugs: categories.map((c) => c.slug),
      icon: iconForCategory(root),
      blurb,
      featured: Boolean(root.is_featured),
      position: root.position ?? DEFAULT_POSITION,
      categories,
      prestations,
      offersTotal: total,
      servicesCount: total,
      href: `/search?metier=${categories.map((c) => c.slug).join(",")}`,
    };
  });
}

/** Métiers mis en avant (page d'accueil) ; si l'administration n'en a marqué aucun, les premiers du catalogue — la page n'est jamais vide. */
export function featuredTrades(trades: ResolvedTrade[], fallbackLimit = 10): ResolvedTrade[] {
  const featured = trades.filter((t) => t.featured);
  return featured.length ? featured : trades.slice(0, fallbackLimit);
}

/** Icône neutre exportée pour les états vides. */
export const FallbackTradeIcon = Package;
