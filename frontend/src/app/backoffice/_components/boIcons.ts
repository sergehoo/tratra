import {
  Award, BarChart3, Bell, Briefcase, Building2, CalendarCheck, FileSignature, IdCard, LayoutDashboard, LifeBuoy, Lock, MapPin, Megaphone, RefreshCw, Settings,
  ShieldCheck, Star, Users, Wallet, type LucideIcon,
} from "lucide-react";
import type { GroupId } from "@/lib/boNavModel";

/** Icônes des modules (le serveur envoie leur nom : `backoffice/modules.py`). */
export const MODULE_ICONS: Record<string, LucideIcon> = {
  "layout-dashboard": LayoutDashboard, users: Users, "shield-check": ShieldCheck, award: Award, "id-card": IdCard, briefcase: Briefcase,
  "calendar-check": CalendarCheck, "map-pin": MapPin, star: Star, "building-2": Building2, wallet: Wallet, megaphone: Megaphone, bell: Bell,
  "file-signature": FileSignature, "refresh-cw": RefreshCw, "life-buoy": LifeBuoy, "bar-chart-3": BarChart3, settings: Settings, lock: Lock,
};

/** Icône de chaque rubrique. */
export const GROUP_ICONS: Record<GroupId, LucideIcon> = {
  overview: LayoutDashboard,
  people: Users,
  missions: Briefcase,
  business: Building2,
  finance: Wallet,
  communication: Megaphone,
  administration: Settings,
};

export const ROLE_LABEL: Record<string, string> = {
  super_admin: "Super administrateur",
  ops: "Opérations",
  support: "Support",
  finance: "Finances",
  marketing: "Marketing",
  analyst: "Analyste",
};
