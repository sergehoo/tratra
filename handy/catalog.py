"""Catalogue unique des métiers : arbre, icônes normalisées, offres publiées, charge utile publique (web, application mobile).

Source de vérité = `ServiceCategory` (PostgreSQL) ; aucun catalogue n'est écrit en dur côté web ou mobile.

  MÉTIER     catégorie racine (`parent` vide)                      « Jardinage », « Cuisine », « Nounou »
  PRESTATION sous-catégorie (`parent` renseigné)                    « Entretien de fleurs » sous « Jardinage »
  OFFRE      `Service` publié par un professionnel éligible         comptée dans `offers_count` (directe) et `offers_total` (avec les prestations)

Règles : un métier ACTIF reste visible même sans offre ; une catégorie désactivée disparaît avec ses prestations ; l'ordre est `position` puis le
nom ; `is_featured` désigne les métiers mis en avant ; les identifiants ne changent jamais."""
import hashlib
import json
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Set

from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone

CACHE_KEY = "handy:catalog:v1"
CACHE_SECONDS = 30

# Vocabulaire d'icônes COMMUN (noms Font Awesome 6, tels que saisis dans l'administration : « fa-solid fa-utensils »).
# Chaque client (web : Lucide ; mobile : Font Awesome) doit savoir dessiner chacune de ces clés ; une clé inconnue donne l'icône par défaut.
ICON_KEYS = (
    # bricolage, construction, maison
    "wrench", "screwdriver-wrench", "screwdriver", "hammer", "toolbox", "paint-roller", "paintbrush", "brush", "faucet", "faucet-drip", "droplet", "shower", "bath",
    "toilet", "bolt", "plug", "lightbulb", "fire", "fire-flame-curved", "temperature-half", "snowflake", "wind", "fan", "key", "lock", "door-open", "door-closed",
    "house", "house-chimney", "house-chimney-crack", "building", "warehouse", "trowel", "trowel-bricks", "ruler-combined", "border-all", "layer-group", "chair",
    "couch", "bed", "window-maximize", "igloo", "helmet-safety", "gear", "gears",
    # cuisine et restauration
    "utensils", "kitchen-set", "bowl-food", "mug-hot", "burger", "pizza-slice", "cake-candles", "blender", "jar", "wine-glass", "cookie-bite", "bread-slice",
    "carrot", "fish", "egg", "ice-cream",
    # personnes, enfants, santé
    "user-nurse", "baby", "baby-carriage", "child", "children", "person", "people-group", "user-group", "hands-holding-child", "hand-holding-heart", "heart",
    "heart-pulse", "stethoscope", "wheelchair", "user-doctor",
    # entretien et ménage
    "broom", "soap", "spray-can-sparkles", "shirt", "jug-detergent", "trash", "trash-can", "recycle", "dumpster",
    # transport
    "truck", "truck-ramp-box", "truck-fast", "car", "car-side", "taxi", "bus", "motorcycle", "bicycle", "gas-pump", "road", "van-shuttle",
    # numérique
    "laptop", "laptop-code", "computer", "mobile-screen-button", "wifi", "camera", "video", "tv", "headphones", "print",
    # enseignement, loisirs, événements
    "music", "guitar", "book", "graduation-cap", "chalkboard-user", "pen", "palette", "camera-retro", "futbol", "dumbbell", "champagne-glasses", "gift", "ring",
    # animaux, jardin, extérieur
    "paw", "dog", "cat", "seedling", "leaf", "tree", "tractor", "sun", "water-ladder", "person-swimming", "spa",
    # services divers
    "handshake", "handshake-angle", "bell-concierge", "shield-halved", "user-shield", "box", "boxes-stacked", "clipboard-check", "scissors", "glass-water",
    "store", "briefcase", "money-bill-wave", "tag", "star",
)
DEFAULT_ICON_KEY = "screwdriver-wrench"

# Anciens noms Font Awesome 5 (encore présents dans la base) → nom Font Awesome 6 du vocabulaire.
ALIASES = {
    "home": "house", "tools": "screwdriver-wrench", "trash-alt": "trash-can", "house-damage": "house-chimney-crack", "swimming-pool": "water-ladder",
    "truck-moving": "truck-ramp-box", "border-style": "border-all", "tint": "droplet", "paint-brush": "paintbrush", "birthday-cake": "cake-candles",
    "hard-hat": "helmet-safety", "chalkboard-teacher": "chalkboard-user", "user-friends": "user-group", "hands-helping": "handshake-angle",
    "concierge-bell": "bell-concierge", "mobile-alt": "mobile-screen-button", "car-alt": "car-side", "shield-alt": "shield-halved", "glass-martini": "wine-glass",
    "broadcast-tower": "wifi", "baby-bottle": "baby", "fire-alt": "fire-flame-curved", "thermometer-half": "temperature-half", "hand-holding-heart": "hand-holding-heart",
    "money-bill-alt": "money-bill-wave", "tools-alt": "screwdriver-wrench", "user-md": "user-doctor", "swimmer": "person-swimming", "pizza": "pizza-slice", "hamburger": "burger", "coffee": "mug-hot",
}

# Icône par défaut d'une catégorie SANS icône renseignée (jamais écrite en base) : une seule table, côté serveur.
DEFAULT_ICON_BY_SLUG = {
    "plomberie": "faucet", "electricite": "bolt", "climatisation": "snowflake", "chauffage": "fire", "serrurerie": "key", "peinture": "paint-roller",
    "bricolage": "screwdriver-wrench", "montage-meuble": "couch", "menage": "broom", "nettoyage": "broom", "nettoyage-apres-travaux": "spray-can-sparkles",
    "jardinage": "seedling", "paysagisme": "leaf", "entretien-piscine": "water-ladder", "mecanique-auto": "car-side", "carrosserie": "car", "lavage-auto": "car",
    "assistance-informatique": "laptop-code", "reparation-ordinateur": "laptop-code", "reparation-smartphone": "mobile-screen-button", "demenagement": "truck",
    "debarras": "trash-can", "garde-denfants": "baby", "garde-danimaux": "paw", "service-traiteur": "utensils", "surveillance-maison": "shield-halved",
    "cours-particulier": "book", "chauffeur-prive": "car", "maconnerie": "trowel-bricks", "carrelage": "border-all", "toiture": "house-chimney", "platrerie": "trowel",
    "isolation": "igloo", "cloture": "layer-group", "terrasse": "border-all", "menuiserie": "hammer", "ebenisterie": "chair", "ferronnerie": "hammer",
    "pose-parquet": "border-all", "vitrerie": "window-maximize", "sol-pvc": "border-all", "installation-electromenager": "blender",
    "reparation-electromenager": "blender", "animation-evenement": "music", "decoration-evenement": "champagne-glasses", "cuisine": "utensils", "nounou": "baby",
}

_STYLE = re.compile(r"^fa-(solid|regular|brands|light|thin|duotone|sharp|fw|lg|xs|sm|[0-9]+x|spin|pulse|beat|fade|bounce|flip|shake)$")


def icon_key(raw: Optional[str], slug: str = "") -> Optional[str]:
    """Clé d'icône normalisée : « fa-solid fa-utensils » → « utensils », « fas fa-home » → « house ». Sans icône : valeur par défaut du slug, sinon None."""
    tokens = (raw or "").lower().split()
    names = [t[3:] for t in tokens if t.startswith("fa-") and not _STYLE.match(t)]
    if not names and len(tokens) == 1 and re.fullmatch(r"[a-z0-9-]+", tokens[0]) and not tokens[0].startswith("fa-") and not re.fullmatch(r"fa[srbltd]?", tokens[0]):
        names = [tokens[0]]
    key = ALIASES.get(names[-1], names[-1]) if names else None
    return key or DEFAULT_ICON_BY_SLUG.get(slug)


def icon_known(key: Optional[str]) -> bool:
    return bool(key) and key in ICON_KEYS


def kind_of(parent_id: Optional[int]) -> str:
    return "trade" if parent_id is None else "service"


def _plain(text: str) -> str:
    """Nom sans accents ni casse : « Élagage » se range avec les E, comme en français (même ordre sur tous les clients)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).casefold()


def _sort_key(row: Dict):
    return (row["position"], _plain(row["name"]), row["id"])


def _load_rows() -> List[Dict]:
    from handy.models import ServiceCategory

    return list(ServiceCategory.objects.values("id", "name", "slug", "description", "icon", "is_active", "parent_id", "position", "is_featured"))


def _direct_offers() -> Dict[int, int]:
    """Offres PUBLIÉES par catégorie : services actifs d'artisans éligibles (même règle que la recherche publique)."""
    from handy.eligibility import publishable_user_ids
    from handy.models import Service

    rows = Service.objects.filter(is_active=True, handyman_id__in=publishable_user_ids()).values("category_id").annotate(n=Count("id")).order_by()
    return {r["category_id"]: r["n"] for r in rows}


def build_payload() -> Dict:
    """Arbre public complet, à plat et dans l'ordre d'affichage (métier, puis ses prestations), catégories ACTIVES seulement."""
    rows = _load_rows()
    children: Dict[Optional[int], List[Dict]] = {}
    for row in rows:
        children.setdefault(row["parent_id"], []).append(row)
    for siblings in children.values():
        siblings.sort(key=_sort_key)
    direct = _direct_offers()
    items: List[Dict] = []

    def visit(row: Dict, trade_id: int, depth: int) -> int:
        item = {
            "id": row["id"], "name": row["name"], "slug": row["slug"], "description": row["description"] or "", "icon": row["icon"] or None,
            "icon_key": icon_key(row["icon"], row["slug"]), "parent": row["parent_id"], "trade": trade_id, "kind": kind_of(row["parent_id"]), "depth": depth,
            "position": row["position"], "order": len(items), "is_featured": bool(row["is_featured"]), "is_active": True,
            "offers_count": direct.get(row["id"], 0), "offers_total": 0, "prestations_count": 0,
        }
        items.append(item)
        total = item["offers_count"]
        for child in children.get(row["id"], []):
            if child["is_active"]:
                item["prestations_count"] += 1
                total += visit(child, trade_id, depth + 1)
        item["offers_total"] = total
        item["services_count"] = total            # alias historique de la liste /categories/ (offres publiées)
        return total

    for root in children.get(None, []):
        if root["is_active"]:
            visit(root, root["id"], 0)
    digest = hashlib.sha1(json.dumps(items, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return {"count": len(items), "next": None, "previous": None, "version": digest, "generated_at": timezone.now().isoformat(), "results": items}


def get_payload() -> Dict:
    payload = cache.get(CACHE_KEY)
    if payload is None:
        payload = build_payload()
        cache.set(CACHE_KEY, payload, CACHE_SECONDS)
    return payload


def invalidate() -> None:
    cache.delete(CACHE_KEY)


def with_descendants(ids: Iterable[int]) -> Set[int]:
    """Identifiants demandés + toutes leurs prestations ACTIVES : choisir un métier couvre ses prestations."""
    wanted = {int(i) for i in ids}
    if not wanted:
        return wanted
    from handy.models import ServiceCategory

    children: Dict[Optional[int], List[int]] = {}
    for pk, parent_id in ServiceCategory.objects.filter(is_active=True).values_list("id", "parent_id"):
        children.setdefault(parent_id, []).append(pk)
    found, stack = set(wanted), list(wanted)
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found
